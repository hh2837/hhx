"""上下文压缩、历史归档与本地检索。

本模块刻意保持简单：

* 归档使用 JSONL（每行一条消息），便于人工查看和逐行检索；
* 检索只做本地全文关键词匹配，不依赖向量数据库或 Embedding；
* Token 统计优先使用模型 API 返回值，拿不到时用字符数做粗略估算。

它是纯业务模块，不依赖任何界面框架。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import Message

DEFAULT_CONTEXT_WINDOW = 128_000
"""无法从配置或 API 获得上下文窗口时的默认值（128k）。"""

DEFAULT_COMPACTION_RATIO = 0.7
"""上下文使用量达到该比例时提示用户压缩。"""

DEFAULT_COMPACTION_TARGET_TOKENS = 5_000
"""压缩摘要的目标长度（约 5,000 Tokens）。"""

ARCHIVE_DIRNAME = Path(".agents") / "context"
"""原始上下文归档目录（相对于项目根目录）。"""

MAX_SEARCH_RESULTS = 8
"""recallContext 单次最多返回的片段数，避免再次占满上下文。"""

SNIPPET_CHARS = 400
"""每个检索结果最多展示的字符数。"""

COMPACTION_PROMPT = """你是一名 AI Agent 的上下文管理助手。当前会话即将达到上下文窗口限制，需要将历史对话压缩为一份高质量的工作摘要，以便 Agent 在新的上下文中继续执行任务。

请认真阅读提供的历史上下文，提取对后续工作仍然有价值的信息，并生成一份约 5,000 Tokens 的 Markdown 摘要。

摘要应重点保留以下内容：

1. **用户目标与要求**：用户希望完成什么任务？有哪些必须遵守的约束、偏好和验收条件？
2. **已经完成的工作**：哪些任务已经完成？实现了哪些功能？获得了哪些已经验证的结果？
3. **当前工作状态**：Agent 正在处理什么任务？当前进展到哪一步？是否存在尚未解决的问题？
4. **关键技术信息**：保留重要的文件路径、函数名称、接口定义、配置项、执行命令、错误信息和必要的代码片段。
5. **关键决策与原因**：记录用户和 Agent 已经确定的技术方案，以及重要的设计取舍。
6. **下一步任务**：明确接下来应该执行的操作，以及需要继续验证的事项。

请遵守以下要求：

- 优先保留对后续任务有直接影响的信息，删除寒暄、重复讨论、过时的尝试和无关内容。
- 对已经验证的事实与尚未验证的推测作出明确区分。
- 不要将计划完成的任务描述为已经完成。
- 重要的文件路径、函数名称、配置名称和命令应保留准确原文。
- 对失败的尝试，只保留有助于避免重复错误的信息。
- 如果信息存在冲突，应优先保留用户最新确认的要求，并简要说明仍然存在的冲突。
- 如果某些历史细节无法在摘要中完整保留，可简要说明它们已保存到原始上下文归档中，后续可以通过 `recallContext` 工具重新检索。
- 使用清晰的 Markdown 结构输出摘要，不要附加解释或无关内容。

**最终目标：使一个从未阅读过原始对话的 Agent，仅凭这份摘要，就能够理解当前任务、继承关键决策，并继续开展工作。**"""


def default_context_directory(
    workspace: Path | str | None = None,
    archive_dirname: Path | str = ARCHIVE_DIRNAME,
) -> Path:
    """返回默认归档目录：``<workspace>/<archive_dirname>``。"""
    base = Path(workspace) if workspace is not None else Path.cwd()
    return base / Path(archive_dirname)


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return (
        0x3000 <= code <= 0x303F  # 中文标点
        or 0x3040 <= code <= 0x30FF  # 日文假名
        or 0x3400 <= code <= 0x4DBF  # 中文扩展 A
        or 0x4E00 <= code <= 0x9FFF  # 中文常用字
        or 0xAC00 <= code <= 0xD7AF  # 韩文
        or 0xFF00 <= code <= 0xFFEF  # 全角字符
    )


def estimate_tokens(text: str) -> int:
    """粗略估算文本 Token 数。

    中文等 CJK 字符通常接近 1 字 1 Token，英文约为 4 字符 1 Token。
    该估算只用于 API 没有返回 usage 的降级场景。
    """
    if not text:
        return 0
    cjk = sum(1 for char in text if _is_cjk(char))
    other = len(text) - cjk
    return int(cjk + other / 4 + 0.999)


def estimate_messages_tokens(messages: Iterable[Message]) -> int:
    """估算整个消息列表的 Token 数（含少量消息结构开销）。"""
    total = 0
    for message in messages:
        total += 4
        total += estimate_tokens(message.content)
        for call in message.tool_calls or []:
            total += 4
            total += estimate_tokens(call.name)
            total += estimate_tokens(json.dumps(call.arguments, ensure_ascii=False))
        if message.tool_call_id:
            total += 4
    return total


def format_token_count(tokens: int) -> str:
    """把 Token 数格式化成便于阅读的 k 形式。"""
    if tokens < 1000:
        return str(tokens)
    value = f"{tokens / 1000:.1f}".rstrip("0").rstrip(".")
    return f"{value}k"


def render_transcript(messages: Iterable[Message]) -> str:
    """把消息列表渲染成供压缩模型阅读的 Markdown 文本。"""
    labels = {"system": "系统", "user": "用户", "assistant": "助手", "tool": "工具结果"}
    lines: list[str] = []
    for index, message in enumerate(messages, 1):
        header = f"### [{index}] {labels.get(message.role, message.role)}"
        if message.name:
            header += f"（{message.name}）"
        lines.append(header)
        if message.content:
            lines.append(message.content)
        for call in message.tool_calls or []:
            arguments = json.dumps(call.arguments, ensure_ascii=False)
            lines.append(f"[工具调用] {call.name}({arguments})")
        if message.tool_call_id:
            lines.append(f"[tool_call_id] {message.tool_call_id}")
        lines.append("")
    return "\n".join(lines).strip()


def build_archive_note(archive_id: str, created_at: str) -> str:
    """生成追加在压缩摘要末尾的归档说明。"""
    return (
        f"> 此前上下文已于 {created_at} 完成压缩，原始上下文保存在编号为 {archive_id} 的归档文件中。"
        "如需查找历史信息，请使用 recallContext 工具。"
    )


@dataclass(frozen=True, slots=True)
class ContextStats:
    """当前上下文的 Token 使用情况。"""

    used_tokens: int = 0
    window_tokens: int = DEFAULT_CONTEXT_WINDOW
    ratio: float = 0.0
    window_is_default: bool = True
    needs_compaction: bool = False
    compacting: bool = False
    tokens_estimated: bool = True
    last_archive_id: str | None = None


@dataclass(frozen=True, slots=True)
class ArchiveRecord:
    """一次归档的输出信息。"""

    archive_id: str
    path: Path
    message_count: int
    created_at: str


@dataclass(frozen=True, slots=True)
class SearchHit:
    """一条检索命中记录。"""

    archive_id: str
    index: int
    role: str
    snippet: str


@dataclass(frozen=True, slots=True)
class CompactionResult:
    """一次上下文压缩的结果。"""

    archive_id: str
    path: Path
    summary: str
    message_count: int
    original_text: str = ""
    """压缩前的完整上下文（已渲染成便于阅读的文本，供界面展示）。"""


class ContextStore:
    """基于本地 JSONL 文件的上下文归档仓库。"""

    def __init__(
        self,
        directory: Path | str | None = None,
        max_results: int = MAX_SEARCH_RESULTS,
        snippet_chars: int = SNIPPET_CHARS,
    ) -> None:
        self._directory = Path(directory) if directory is not None else default_context_directory()
        self._max_results = max_results
        self._snippet_chars = snippet_chars

    @property
    def directory(self) -> Path:
        return self._directory

    @property
    def max_results(self) -> int:
        return self._max_results

    @property
    def snippet_chars(self) -> int:
        return self._snippet_chars

    def path_for(self, archive_id: str) -> Path:
        """根据归档编号返回文件路径，并阻止路径穿越。"""
        if not archive_id or Path(archive_id).name != archive_id:
            raise ValueError(f"非法的归档编号：{archive_id}")
        if "/" in archive_id or "\\" in archive_id:
            raise ValueError(f"非法的归档编号：{archive_id}")
        return self._directory / f"{archive_id}.jsonl"

    def _next_id(self) -> str:
        base = datetime.now().strftime("%Y%m%d-%H%M%S")
        candidate = base
        suffix = 1
        while self.path_for(candidate).exists():
            suffix += 1
            candidate = f"{base}-{suffix}"
        return candidate

    def archive(self, messages: Sequence[Message], archive_id: str | None = None) -> ArchiveRecord:
        """把完整消息列表保存为 JSONL 归档。

        返回前会校验文件确实写入成功；写入失败会抛异常，调用方不得继续替换上下文。
        """
        records = list(messages)
        archive_id = archive_id or self._next_id()
        path = self.path_for(archive_id)
        self._directory.mkdir(parents=True, exist_ok=True)

        lines: list[str] = []
        for index, message in enumerate(records):
            payload = message.to_payload()
            payload["index"] = index
            lines.append(json.dumps(payload, ensure_ascii=False))

        with path.open("w", encoding="utf-8") as handle:
            for line in lines:
                handle.write(f"{line}\n")
            handle.flush()

        if not path.exists() or path.stat().st_size == 0:
            raise OSError(f"上下文归档写入失败：{path}")

        return ArchiveRecord(
            archive_id=archive_id,
            path=path,
            message_count=len(records),
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    def list_archives(self) -> list[str]:
        """列出全部归档编号（新的在前）。"""
        if not self._directory.exists():
            return []
        return sorted((path.stem for path in self._directory.glob("*.jsonl")), reverse=True)

    def search(
        self,
        text: str,
        archive_id: str | None = None,
        max_results: int | None = None,
    ) -> list[SearchHit]:
        """在所有归档或指定归档中做全文关键词检索。"""
        limit = self._max_results if max_results is None else max_results
        keywords = [word.lower() for word in re.split(r"\s+", text.strip()) if word]
        if not keywords:
            return []

        archive_ids = [archive_id] if archive_id else self.list_archives()
        scored: list[tuple[int, SearchHit]] = []

        for current_id in archive_ids:
            path = self.path_for(current_id)
            if not path.exists():
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line_number, raw_line in enumerate(lines):
                try:
                    record = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                readable = _record_text(record)
                haystack = readable.lower()
                score = sum(haystack.count(keyword) for keyword in keywords)
                if score <= 0:
                    continue
                keyword = next(item for item in keywords if item in haystack)
                hit = SearchHit(
                    archive_id=current_id,
                    index=int(record.get("index", line_number)),
                    role=str(record.get("role", "")),
                    snippet=_make_snippet(readable, keyword, width=self._snippet_chars),
                )
                scored.append((score, hit))

        scored.sort(key=lambda item: (-item[0], item[1].archive_id, item[1].index))
        return [hit for _, hit in scored[:limit]]


def _record_text(record: dict) -> str:
    """把一条归档记录转换成可读、可检索的文本。"""
    parts: list[str] = []
    content = record.get("content")
    if content:
        parts.append(str(content))
    for call in record.get("tool_calls") or []:
        function = call.get("function") or {}
        name = function.get("name", "")
        arguments = function.get("arguments", "")
        parts.append(f"工具调用 {name}({arguments})")
    if record.get("tool_call_id"):
        parts.append(f"tool_call_id: {record['tool_call_id']}")
    return "\n".join(parts)


def _make_snippet(text: str, keyword: str, width: int = SNIPPET_CHARS) -> str:
    """围绕关键词截取一段上下文，控制返回长度。"""
    position = text.lower().find(keyword)
    if position < 0:
        position = 0
    start = max(0, position - width // 2)
    end = min(len(text), start + width)
    snippet = text[start:end].replace("\r", "").strip()
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{snippet}{suffix}"


__all__ = [
    "ARCHIVE_DIRNAME",
    "COMPACTION_PROMPT",
    "DEFAULT_COMPACTION_RATIO",
    "DEFAULT_COMPACTION_TARGET_TOKENS",
    "DEFAULT_CONTEXT_WINDOW",
    "MAX_SEARCH_RESULTS",
    "SNIPPET_CHARS",
    "ArchiveRecord",
    "CompactionResult",
    "ContextStats",
    "ContextStore",
    "SearchHit",
    "build_archive_note",
    "default_context_directory",
    "estimate_messages_tokens",
    "estimate_tokens",
    "format_token_count",
    "render_transcript",
]

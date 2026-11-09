"""Agent 编排：把"模型 → 工具 → 模型"的循环收敛在一处。

这一层只产生 :mod:`core.events` 事件，不做任何界面相关的事情。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

from ..config import AgentConfig
from ..context import (
    COMPACTION_PROMPT,
    DEFAULT_COMPACTION_RATIO,
    DEFAULT_CONTEXT_WINDOW,
    CompactionResult,
    ContextStats,
    ContextStore,
    build_archive_note,
    default_context_directory,
    estimate_messages_tokens,
    format_token_count,
    render_transcript,
)
from ..errors import AgentError, ContextCompactionRequired, ContextError, MaxToolRoundsExceeded
from ..events import (
    AgentsInjected,
    AssistantMessage,
    AssistantMessageStarted,
    CompactionFinished,
    CompactionStarted,
    ContextWarning,
    ErrorOccurred,
    Event,
    EventEmitter,
    RunFinished,
    RunStarted,
    ToolCallFinished,
    ToolCallRequested,
    UserMessageEcho,
)
from ..llm.client import LLMClient, TokenUsage
from ..models import Message, ToolCall
from ..skills import SkillRegistry
from ..tools.registry import ToolRegistry
from ..tools.skill_tools import register_create_skill_tool, register_load_skill_tool
from .session import build_agents_message, has_agents_message, read_agents_file

logger = logging.getLogger(__name__)


class Agent:
    """一个可复用的智能体。

    典型用法::

        agent = Agent(client=OpenAICompatibleClient(config.llm),
                      tools=register_builtin_tools(ToolRegistry()))
        answer = agent.run("现在几点？", emit=print)
    """

    def __init__(
        self,
        client: LLMClient,
        tools: ToolRegistry,
        config: AgentConfig | None = None,
        system_prompt: str | None = None,
        skills: SkillRegistry | None = None,
        context_window: int | None = None,
        context_dir: Path | str | None = None,
        workspace: Path | str | None = None,
        agents_file: str | None = None,
        agents_max_bytes: int = 200_000,
    ) -> None:
        self._client = client
        self._tools = tools
        self._config = config or AgentConfig()
        self._skills = skills if skills is not None else SkillRegistry.discover()
        base_prompt = system_prompt if system_prompt is not None else self._config.system_prompt
        self._system_prompt = self._compose_system_prompt(base_prompt)
        if self._skills:
            register_load_skill_tool(self._tools, self._skills)
        register_create_skill_tool(self._tools, self._skills)
        self._messages: list[Message] = []
        if self._system_prompt:
            self._messages.append(Message.system(self._system_prompt))

        self._workspace = Path(workspace) if workspace else None
        self._agents_file = agents_file or self._config.agents_file
        self._agents_max_bytes = agents_max_bytes or self._config.agents_max_bytes
        self._inject_agents_md()

        self._context_store = ContextStore(
            context_dir if context_dir is not None else default_context_directory()
        )
        self._window_is_default = not context_window or context_window <= 0
        self._window_tokens = (
            self._config.default_context_window or DEFAULT_CONTEXT_WINDOW
            if self._window_is_default
            else int(context_window)
        )
        self._context_tokens = estimate_messages_tokens(self._messages)
        self._tokens_estimated = True
        self._compaction_required = False
        self._compacting = False
        self._warning_emitted = False
        self._last_archive_id: str | None = None

    # ------------------------------------------------------------------ 状态

    @property
    def client(self) -> LLMClient:
        return self._client

    @property
    def tools(self) -> ToolRegistry:
        return self._tools

    @property
    def skills(self) -> SkillRegistry:
        return self._skills

    @property
    def config(self) -> AgentConfig:
        return self._config

    @property
    def messages(self) -> list[Message]:
        return list(self._messages)

    @property
    def context_store(self) -> ContextStore:
        return self._context_store

    @property
    def is_compacting(self) -> bool:
        """是否正在执行上下文压缩。"""
        return self._compacting

    @property
    def compaction_required(self) -> bool:
        """上下文是否已达到阈值、需要用户执行 /compact。"""
        return self._compaction_required or self.context_stats().needs_compaction

    def context_stats(self) -> ContextStats:
        """返回当前上下文 Token 使用情况。"""
        ratio = self._context_tokens / self._window_tokens if self._window_tokens else 0.0
        threshold = self._config.compact_threshold or DEFAULT_COMPACTION_RATIO
        reached = ratio >= threshold
        return ContextStats(
            used_tokens=self._context_tokens,
            window_tokens=self._window_tokens,
            ratio=ratio,
            window_is_default=self._window_is_default,
            needs_compaction=self._compaction_required or reached,
            compacting=self._compacting,
            tokens_estimated=self._tokens_estimated,
            last_archive_id=self._last_archive_id,
        )

    @property
    def agents_md_injected(self) -> bool:
        """当前会话历史中是否已包含项目约定注入消息。"""
        return has_agents_message(self._messages)

    def reset(self) -> None:
        """清空会话历史（保留系统提示词），并重新注入项目约定。"""
        self._messages = [Message.system(self._system_prompt)] if self._system_prompt else []
        self._inject_agents_md()
        self._context_tokens = estimate_messages_tokens(self._messages)
        self._tokens_estimated = True
        self._compaction_required = False
        self._warning_emitted = False
        self._last_archive_id = None

    def set_messages(self, messages: Iterable[Message]) -> None:
        """用外部历史覆盖当前历史。

        若恢复的历史中还没有项目约定消息，且工作区存在项目约定文件，
        则补注入一次，保证"一次注入、全程复用"。
        """
        self._messages = list(messages)
        self._inject_agents_md()
        self._context_tokens = estimate_messages_tokens(self._messages)
        self._tokens_estimated = True
        self._warning_emitted = False
        self._compaction_required = False
        self._compaction_required = self.context_stats().needs_compaction

    # ------------------------------------------------------------------ 项目约定（AGENTS.md）

    def inject_agents_md(self, emit: EventEmitter | None = None) -> bool:
        """把项目约定文件作为一条消息注入历史，返回是否发生了注入。

        已注入过（历史中存在同名消息）或工作区没有约定文件时不重复注入。
        """
        return self._inject_agents_md(emit)

    def _inject_agents_md(self, emit: EventEmitter | None = None) -> bool:
        if has_agents_message(self._messages) or self._workspace is None:
            return False
        content = read_agents_file(self._workspace, self._agents_file, self._agents_max_bytes)
        if content is None:
            return False
        self._messages.append(build_agents_message(self._agents_file, content))
        self._refresh_estimate()
        if emit is not None:
            self._safe_emit(emit, AgentsInjected(filename=self._agents_file, chars=len(content)))
        return True

    # ------------------------------------------------------------------ 运行

    def run(self, user_input: str, emit: EventEmitter | None = None) -> str:
        """处理一次用户输入，返回最终回答文本。"""
        emitter: EventEmitter = emit or (lambda event: None)

        if self._compacting:
            raise AgentError("上下文压缩进行中，暂时不能执行其他任务或工具。")

        stats = self.context_stats()
        if stats.needs_compaction:
            self._compaction_required = True
            self._emit_context_warning(emitter, stats)
            raise ContextCompactionRequired(
                "上下文已接近窗口上限，请先执行 /compact 压缩上下文，再继续对话。"
            )

        self._safe_emit(emitter, RunStarted(user_input=user_input))

        self._messages.append(Message.user(user_input))
        self._safe_emit(emitter, UserMessageEcho(text=user_input))
        self._trim_history()
        if self._tokens_estimated:
            self._refresh_estimate()

        rounds = 0
        while rounds < self._config.max_tool_rounds:
            rounds += 1
            answer, tool_calls = self._chat_once(emitter)

            if not tool_calls:
                self._messages.append(Message.assistant(answer))
                if self._tokens_estimated:
                    self._refresh_estimate()
                self._safe_emit(emitter, RunFinished(answer=answer, rounds=rounds))
                return answer

            self._messages.append(Message.assistant(answer, tool_calls))
            for call in tool_calls:
                self._safe_emit(emitter, ToolCallRequested(call=call))
                result = self._tools.execute(call.name, call.arguments)
                output = result.content if result.ok else f"[工具执行失败] {result.error}"
                self._safe_emit(
                    emitter,
                    ToolCallFinished(call=call, ok=result.ok, output=output),
                )
                self._messages.append(Message.tool(output, call.id, call.name))
            if self._tokens_estimated:
                self._refresh_estimate()

        message = f"工具调用轮次超过上限（{self._config.max_tool_rounds}），已终止本轮对话。"
        self._safe_emit(emitter, ErrorOccurred(message=message))
        raise MaxToolRoundsExceeded(message)

    # ------------------------------------------------------------------ 压缩

    def compact(self, emit: EventEmitter | None = None) -> CompactionResult:
        """归档原始上下文，并调用 LLM 生成摘要替换历史。

        压缩期间只允许调用 LLM；归档保存失败或摘要生成失败时，原上下文保持不变。
        """
        emitter: EventEmitter = emit or (lambda event: None)

        if self._compacting:
            raise ContextError("上下文压缩正在进行中，请勿重复执行。")

        history = [message for message in self._messages if message.role != "system"]
        if not history:
            raise ContextError("当前没有可压缩的对话历史。")

        original_text = render_transcript(self._messages)
        self._compacting = True
        self._safe_emit(emitter, CompactionStarted(message_count=len(self._messages)))
        try:
            try:
                record = self._context_store.archive(self._messages)
            except OSError as exc:
                raise ContextError(f"原始上下文归档失败，压缩已中止：{exc}") from exc

            transcript = render_transcript(history)
            request = [
                Message.system(COMPACTION_PROMPT),
                Message.user(
                    "以下是需要压缩的历史上下文。请按要求生成摘要，不要调用工具。\n"
                    f"摘要目标长度约为 {self._config.compact_target_tokens} Tokens。\n\n"
                    f"{transcript}"
                ),
            ]
            response = self._client.chat(request, tools=None)
            summary = (response.content or "").strip()
            if not summary:
                raise ContextError("模型没有返回有效的上下文摘要，原上下文已保留，可重新执行 /compact。")

            note = build_archive_note(record.archive_id, record.created_at)
            new_messages: list[Message] = []
            if self._system_prompt:
                new_messages.append(Message.system(self._system_prompt))
            new_messages.append(
                Message.user(f"## 此前会话压缩摘要\n\n{summary}\n\n{note}")
            )

            self._messages = new_messages
            self._last_archive_id = record.archive_id
            self._compaction_required = False
            self._warning_emitted = False
            self._context_tokens = estimate_messages_tokens(self._messages)
            self._tokens_estimated = True

            result = CompactionResult(
                archive_id=record.archive_id,
                path=record.path,
                summary=summary,
                message_count=record.message_count,
                original_text=original_text,
            )
            self._safe_emit(
                emitter,
                CompactionFinished(
                    archive_id=record.archive_id,
                    path=str(record.path),
                    summary_chars=len(summary),
                    message_count=record.message_count,
                ),
            )
            return result
        finally:
            self._compacting = False

    # ------------------------------------------------------------------ 内部实现

    def _chat_once(self, emitter: EventEmitter) -> tuple[str, list[ToolCall]]:
        """请求一次模型，返回完整回答文本与工具调用。"""
        response = self._client.chat(self._messages, self._tools.schemas())
        answer = response.content or ""
        tool_calls = list(response.tool_calls)
        self._update_context_usage(response.usage, emitter)

        if answer:
            self._safe_emit(emitter, AssistantMessageStarted())
            self._safe_emit(emitter, AssistantMessage(text=answer))

        return answer, tool_calls

    def _compose_system_prompt(self, prompt: str | None) -> str:
        """把 Skill 元数据附加到系统提示词，正文仍然按需加载。"""
        block = self._skills.prompt_block()
        if not block:
            return prompt or ""
        if not prompt:
            return block.strip()
        return f"{prompt.rstrip()}\n{block}"

    def _trim_history(self) -> None:
        """限制历史长度，保留系统提示词与最近的若干条消息。"""
        limit = self._config.max_history_messages
        if limit <= 0 or len(self._messages) <= limit:
            return
        head = self._messages[:1] if self._messages and self._messages[0].role == "system" else []
        tail = self._messages[len(head) :][-limit:]
        self._messages = head + tail

    def _refresh_estimate(self) -> None:
        self._context_tokens = estimate_messages_tokens(self._messages)
        self._tokens_estimated = True

    def _update_context_usage(self, usage: TokenUsage | None, emitter: EventEmitter) -> None:
        """优先使用 API 返回的 Token 信息，否则退化为本地估算。"""
        if usage is not None and usage.total_tokens > 0:
            self._context_tokens = usage.total_tokens
            self._tokens_estimated = False
        else:
            self._refresh_estimate()

        self._check_context_threshold(emitter)

    def _check_context_threshold(self, emitter: EventEmitter) -> None:
        stats = self.context_stats()
        threshold = self._config.compact_threshold or DEFAULT_COMPACTION_RATIO
        if stats.ratio < threshold:
            return
        self._compaction_required = True
        self._emit_context_warning(emitter, stats)

    def _emit_context_warning(self, emitter: EventEmitter, stats: ContextStats) -> None:
        if self._warning_emitted:
            return
        self._warning_emitted = True
        percent = stats.ratio * 100
        message = (
            f"上下文已使用 {format_token_count(stats.used_tokens)} / "
            f"{format_token_count(stats.window_tokens)}（{percent:.1f}%），"
            "请执行 /compact 压缩上下文后再继续。"
        )
        self._safe_emit(
            emitter,
            ContextWarning(
                used_tokens=stats.used_tokens,
                window_tokens=stats.window_tokens,
                ratio=stats.ratio,
                message=message,
            ),
        )

    @staticmethod
    def _safe_emit(emitter: EventEmitter, event: Event) -> None:
        """事件回调异常不应中断 Agent 主循环。"""
        try:
            emitter(event)
        except Exception:
            logger.exception("事件回调执行失败：%s", type(event).__name__)


__all__ = ["Agent"]

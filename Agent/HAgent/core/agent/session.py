"""会话持久化：把对话历史保存成 JSON，方便前端做"新建 / 恢复"。

存储层与界面无关，TUI 之外，Web / Desktop 也可以直接复用。
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import DEFAULT_AGENTS_FILENAME
from ..models import ROLE_USER, Message

AGENTS_MESSAGE_NAME = DEFAULT_AGENTS_FILENAME
"""注入到历史中的项目约定消息名称，用于去重。"""


@dataclass(slots=True)
class Session:
    """一次会话（多轮对话）的元信息与消息列表。"""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = "新会话"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    messages: list[Message] = field(default_factory=list)
    agents_md_injected: bool = False
    """项目约定文件是否已经注入过（用于跨压缩 / 恢复时去重）。"""

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": [message.to_payload() for message in self.messages],
            "agents_md_injected": self.agents_md_injected,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Session:
        return cls(
            id=payload.get("id") or uuid.uuid4().hex[:12],
            title=payload.get("title") or "未命名会话",
            created_at=float(payload.get("created_at", time.time())),
            updated_at=float(payload.get("updated_at", time.time())),
            messages=[Message.from_payload(item) for item in payload.get("messages") or []],
            agents_md_injected=bool(payload.get("agents_md_injected", False)),
        )

    def touch(self) -> None:
        self.updated_at = time.time()


def has_agents_message(messages: list[Message]) -> bool:
    """判断历史中是否已经包含项目约定注入消息。"""
    return any(message.name == AGENTS_MESSAGE_NAME for message in messages)


def read_agents_file(
    workspace: Path | str,
    filename: str = DEFAULT_AGENTS_FILENAME,
    max_bytes: int = 200_000,
) -> str | None:
    """读取工作区中的项目约定文件；不存在或为空时返回 ``None``。"""
    path = Path(workspace) / filename
    if not path.is_file():
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    truncated = len(data) > max_bytes
    content = data[:max_bytes].decode("utf-8", errors="replace").lstrip("\ufeff")
    content = content.strip()
    if not content:
        return None
    if truncated:
        content = f"{content}\n\n…（{filename} 内容超过 {max_bytes} 字节，已截断）"
    return content


def build_agents_message(filename: str, content: str) -> Message:
    """把项目约定内容包装成历史消息。"""
    body = (
        f"## 项目约定（来自 {filename}）\n\n"
        "以下内容由系统在会话首次加载时自动注入，请在本会话后续所有回答中遵守。\n\n"
        f"{content}"
    )
    return Message(role=ROLE_USER, content=body, name=AGENTS_MESSAGE_NAME)


def inject_agents_md(
    session: Session,
    workspace: Path | str,
    filename: str = DEFAULT_AGENTS_FILENAME,
    max_bytes: int = 200_000,
) -> bool:
    """在会话首次加载时注入项目约定，返回是否发生了注入。"""
    if session.agents_md_injected or has_agents_message(session.messages):
        session.agents_md_injected = True
        return False
    content = read_agents_file(workspace, filename=filename, max_bytes=max_bytes)
    if content is None:
        return False
    session.messages.append(build_agents_message(filename, content))
    session.agents_md_injected = True
    session.touch()
    return True


class SessionStore:
    """基于 JSON 文件的会话仓库。

    每个会话一个文件，存放于 ``directory`` 下。
    """

    def __init__(self, directory: Path | str) -> None:
        self._directory = Path(directory)

    @property
    def directory(self) -> Path:
        return self._directory

    def path_for(self, session_id: str) -> Path:
        return self._directory / f"{session_id}.json"

    def save(self, session: Session) -> Path:
        """保存会话，返回文件路径。"""
        self._directory.mkdir(parents=True, exist_ok=True)
        session.touch()
        path = self.path_for(session.id)
        path.write_text(
            json.dumps(session.to_payload(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def load(self, session_id: str) -> Session | None:
        """按 id 读取会话；不存在返回 ``None``。"""
        path = self.path_for(session_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return Session.from_payload(payload)

    def list_sessions(self) -> list[Session]:
        """列出全部会话（按更新时间倒序）。"""
        if not self._directory.exists():
            return []
        sessions: list[Session] = []
        for path in self._directory.glob("*.json"):
            session = self.load(path.stem)
            if session is not None:
                sessions.append(session)
        sessions.sort(key=lambda item: item.updated_at, reverse=True)
        return sessions

    def delete(self, session_id: str) -> bool:
        path = self.path_for(session_id)
        if path.exists():
            path.unlink()
            return True
        return False


__all__ = [
    "AGENTS_MESSAGE_NAME",
    "Session",
    "SessionStore",
    "build_agents_message",
    "has_agents_message",
    "inject_agents_md",
    "read_agents_file",
]

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

from ..models import Message


@dataclass(slots=True)
class Session:
    """一次会话（多轮对话）的元信息与消息列表。"""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = "新会话"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    messages: list[Message] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": [message.to_payload() for message in self.messages],
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Session:
        return cls(
            id=payload.get("id") or uuid.uuid4().hex[:12],
            title=payload.get("title") or "未命名会话",
            created_at=float(payload.get("created_at", time.time())),
            updated_at=float(payload.get("updated_at", time.time())),
            messages=[Message.from_payload(item) for item in payload.get("messages") or []],
        )

    def touch(self) -> None:
        self.updated_at = time.time()


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


__all__ = ["Session", "SessionStore"]

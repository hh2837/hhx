"""领域模型：与界面无关的纯数据结构。

这一层只描述"消息长什么样"，不关心谁在消费它，因此 TUI / Web / Desktop
都可以复用同一套模型。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]

ROLE_SYSTEM: Role = "system"
ROLE_USER: Role = "user"
ROLE_ASSISTANT: Role = "assistant"
ROLE_TOOL: Role = "tool"


@dataclass(slots=True)
class ToolCall:
    """一次工具调用请求。"""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": json.dumps(self.arguments, ensure_ascii=False)},
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ToolCall:
        function = payload.get("function") or {}
        raw_arguments = function.get("arguments") or "{}"
        if isinstance(raw_arguments, dict):
            arguments = raw_arguments
        else:
            try:
                arguments = json.loads(raw_arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
        return cls(
            id=payload.get("id", ""),
            name=function.get("name", ""),
            arguments=arguments,
        )


@dataclass(slots=True)
class Message:
    """一条对话消息。"""

    role: Role
    content: str = ""
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def to_payload(self) -> dict[str, Any]:
        """转换为 OpenAI 兼容接口的 wire 格式。"""
        payload: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            payload["tool_calls"] = [call.to_payload() for call in self.tool_calls]
        if self.tool_call_id:
            payload["tool_call_id"] = self.tool_call_id
        if self.name:
            payload["name"] = self.name
        return payload

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Message:
        raw_tool_calls = payload.get("tool_calls") or []
        return cls(
            role=payload.get("role", ROLE_USER),  # type: ignore[arg-type]
            content=payload.get("content") or "",
            tool_calls=[ToolCall.from_payload(item) for item in raw_tool_calls] or None,
            tool_call_id=payload.get("tool_call_id"),
            name=payload.get("name"),
        )

    @classmethod
    def system(cls, content: str) -> Message:
        return cls(role=ROLE_SYSTEM, content=content)

    @classmethod
    def user(cls, content: str) -> Message:
        return cls(role=ROLE_USER, content=content)

    @classmethod
    def assistant(cls, content: str = "", tool_calls: Iterable[ToolCall] | None = None) -> Message:
        return cls(role=ROLE_ASSISTANT, content=content, tool_calls=list(tool_calls) if tool_calls else None)

    @classmethod
    def tool(cls, content: str, tool_call_id: str, name: str | None = None) -> Message:
        return cls(role=ROLE_TOOL, content=content, tool_call_id=tool_call_id, name=name)


__all__ = [
    "ROLE_ASSISTANT",
    "ROLE_SYSTEM",
    "ROLE_TOOL",
    "ROLE_USER",
    "Message",
    "Role",
    "ToolCall",
]

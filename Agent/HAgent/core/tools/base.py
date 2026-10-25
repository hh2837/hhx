"""工具的抽象定义：工具规格与执行结果。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """一个工具的静态描述与执行入口。

    ``parameters`` 为 JSON Schema 描述，直接用于 OpenAI function calling。
    """

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any]

    def to_openai_schema(self) -> dict[str, Any]:
        """转换为 OpenAI ``tools`` 数组中的元素。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True, slots=True)
class ToolResult:
    """工具执行结果。

    ``ok=False`` 时 ``error`` 给出可读的错误原因，``content`` 为空串。
    """

    ok: bool
    content: str = ""
    error: str | None = None

    @classmethod
    def success(cls, content: str = "") -> ToolResult:
        return cls(ok=True, content=content)

    @classmethod
    def failure(cls, error: str) -> ToolResult:
        return cls(ok=False, content="", error=error)


__all__ = ["ToolResult", "ToolSpec"]

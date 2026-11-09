"""大模型客户端抽象。

核心层只依赖 :class:`LLMClient` 这一抽象，具体实现（OpenAI 兼容、Ollama、
本地推理框架……）放在子模块中，便于替换与单元测试。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from ..models import Message, ToolCall


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """模型 API 返回的 Token 使用信息。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> TokenUsage:
        prompt_tokens = int(payload.get("prompt_tokens") or 0)
        completion_tokens = int(payload.get("completion_tokens") or 0)
        total_tokens = int(payload.get("total_tokens") or (prompt_tokens + completion_tokens))
        return cls(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )


@dataclass(slots=True)
class ChatResponse:
    """一次非流式对话的完整响应。"""

    content: str = ""
    reasoning: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    usage: TokenUsage | None = None


class LLMClient(ABC):
    """大模型客户端接口。

    实现者只需要关心"把消息发给模型，并一次性返回完整结果"。
    """

    @abstractmethod
    def chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        """发送一次对话请求，返回完整响应。"""

    def close(self) -> None:  # noqa: B027 - 可选钩子，默认无操作
        """释放底层资源（默认无操作）。"""


__all__ = ["ChatResponse", "LLMClient", "TokenUsage"]

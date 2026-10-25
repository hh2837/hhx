"""大模型客户端抽象。

核心层只依赖 :class:`LLMClient` 这一抽象，具体实现（OpenAI 兼容、Ollama、
本地推理框架……）放在子模块中，便于替换与单元测试。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..models import Message


@dataclass(slots=True)
class ToolCallDelta:
    """流式响应中的工具调用增量。"""

    index: int = 0
    id: str = ""
    name: str = ""
    arguments: str = ""


@dataclass(slots=True)
class StreamChunk:
    """一次流式返回的增量数据。"""

    content: str = ""
    reasoning: str = ""
    tool_call_deltas: list[ToolCallDelta] = field(default_factory=list)
    finish_reason: str | None = None


class LLMClient(ABC):
    """大模型客户端接口。

    实现者只需要关心"把消息发给模型，并流式产出增量"。
    """

    @abstractmethod
    def stream_chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> Iterator[StreamChunk]:
        """发送一次对话请求，产出流式增量。"""

    def close(self) -> None:  # noqa: B027 - 可选钩子，默认无操作
        """释放底层资源（默认无操作）。"""


__all__ = ["LLMClient", "StreamChunk", "ToolCallDelta"]

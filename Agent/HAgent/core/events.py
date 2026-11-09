"""事件定义：核心层与前端层之间的唯一通信契约。

设计要点
--------
1. 核心层（:mod:`core`）只负责"发生什么"，不关心"如何展示"。
2. 核心层通过 :data:`EventEmitter` 把事件推给订阅者。
3. 任何前端（TUI / Web / Desktop / Mobile）只需实现对事件的处理，即可复用同一套
   Agent 业务逻辑，无需改动核心代码。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .models import ToolCall


@dataclass(frozen=True, kw_only=True, slots=True)
class Event:
    """所有事件的基类。

    ``timestamp`` 为事件产生时刻（Unix 时间戳），供前端做节流、日志或排序使用。
    """

    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, kw_only=True, slots=True)
class RunStarted(Event):
    """一次用户输入触发的完整运行开始。"""

    user_input: str = ""


@dataclass(frozen=True, kw_only=True, slots=True)
class UserMessageEcho(Event):
    """用户输入已写入会话历史。"""

    text: str = ""


@dataclass(frozen=True, kw_only=True, slots=True)
class AssistantMessageStarted(Event):
    """助手开始输出（用于前端创建消息气泡）。"""


@dataclass(frozen=True, kw_only=True, slots=True)
class AssistantMessage(Event):
    """助手回答完成（最终文本）。"""

    text: str = ""


@dataclass(frozen=True, kw_only=True, slots=True)
class ToolCallRequested(Event):
    """模型请求调用某个工具。"""

    call: ToolCall = field(default_factory=lambda: ToolCall(id="", name=""))


@dataclass(frozen=True, kw_only=True, slots=True)
class ToolCallFinished(Event):
    """工具执行结束。"""

    call: ToolCall = field(default_factory=lambda: ToolCall(id="", name=""))
    ok: bool = True
    output: str = ""


@dataclass(frozen=True, kw_only=True, slots=True)
class ErrorOccurred(Event):
    """运行过程中出现错误。"""

    message: str = ""
    detail: str = ""


@dataclass(frozen=True, kw_only=True, slots=True)
class RunFinished(Event):
    """一次运行结束。"""

    answer: str = ""
    rounds: int = 0


@dataclass(frozen=True, kw_only=True, slots=True)
class ContextWarning(Event):
    """上下文使用量达到阈值，提示用户执行 /compact。"""

    used_tokens: int = 0
    window_tokens: int = 0
    ratio: float = 0.0
    message: str = ""


@dataclass(frozen=True, kw_only=True, slots=True)
class CompactionStarted(Event):
    """开始压缩上下文（此时禁止其他工具调用与任务处理）。"""

    message_count: int = 0


@dataclass(frozen=True, kw_only=True, slots=True)
class CompactionFinished(Event):
    """上下文压缩成功完成。"""

    archive_id: str = ""
    path: str = ""
    summary_chars: int = 0
    message_count: int = 0


@dataclass(frozen=True, kw_only=True, slots=True)
class AgentsInjected(Event):
    """项目约定文件（如 AGENTS.md）已作为一条消息注入会话历史。"""

    filename: str = ""
    chars: int = 0


EventType = (
    RunStarted
    | UserMessageEcho
    | AssistantMessageStarted
    | AssistantMessage
    | ToolCallRequested
    | ToolCallFinished
    | ErrorOccurred
    | RunFinished
    | ContextWarning
    | CompactionStarted
    | CompactionFinished
    | AgentsInjected
)

EventEmitter = Callable[[Event], None]
"""事件回调签名：接收一个事件，抛出异常由调用方负责捕获。"""


class NullEmitter:
    """空事件接收器，用于不需要 UI 的场景（例如脚本 / 测试）。"""

    def __call__(self, event: Event) -> None:  # pragma: no cover - 平凡实现
        return None


__all__ = [
    "AgentsInjected",
    "AssistantMessage",
    "AssistantMessageStarted",
    "CompactionFinished",
    "CompactionStarted",
    "ContextWarning",
    "ErrorOccurred",
    "Event",
    "EventEmitter",
    "EventType",
    "NullEmitter",
    "RunFinished",
    "RunStarted",
    "ToolCallFinished",
    "ToolCallRequested",
    "UserMessageEcho",
]

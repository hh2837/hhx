"""控制器：核心层事件 → 界面动作。

这一层是"翻译器"，把 :mod:`core.events` 中与业务语义相关的事件转换成界面能
理解的动作。它不依赖 Textual，因此可以在没有界面的环境下做单元测试。
"""

from __future__ import annotations

from typing import Protocol

from core import (
    Agent,
    AssistantDelta,
    AssistantMessage,
    AssistantMessageStarted,
    ErrorOccurred,
    Event,
    RunFinished,
    RunStarted,
    ToolCall,
    ToolCallFinished,
    ToolCallRequested,
    UserMessageEcho,
)


class ChatViewPort(Protocol):
    """界面端需要实现的最小接口（TUI / Web / Desktop 各自实现一份）。"""

    def show_user_message(self, text: str) -> None:
        """显示一条用户消息。"""

    def start_assistant_message(self) -> None:
        """开始渲染一条助手消息。"""
    def append_assistant_delta(self, text: str) -> None:
        """追加助手消息的流式片段。"""

    def finish_assistant_message(self, text: str) -> None:
        """结束助手消息。"""

    def show_tool_call(self, call: ToolCall) -> None:
        """显示工具调用请求。"""

    def show_tool_result(self, call: ToolCall, ok: bool, output: str) -> None:
        """显示工具执行结果。"""

    def show_error(self, message: str, detail: str = "") -> None:
        """显示错误。"""

    def set_status(self, status: str) -> None:
        """更新状态提示。"""

    def clear_transcript(self) -> None:
        """清空对话记录。"""


class ChatController:
    """驱动一次对话并把事件翻译给界面。"""

    def __init__(self, agent: Agent, viewport: ChatViewPort) -> None:
        self._agent = agent
        self._viewport = viewport

    @property
    def agent(self) -> Agent:
        return self._agent

    @property
    def viewport(self) -> ChatViewPort:
        return self._viewport

    def submit(self, text: str) -> str:
        """提交一条用户输入，返回助手最终回答。"""
        text = text.strip()
        if not text:
            return ""
        self._viewport.set_status("思考中…")
        try:
            return self._agent.run(text, emit=self.handle_event)
        finally:
            self._viewport.set_status("就绪")

    def handle_event(self, event: Event) -> None:
        """把核心事件翻译成界面动作。"""
        if isinstance(event, RunStarted):
            self._viewport.set_status("思考中…")
        elif isinstance(event, UserMessageEcho):
            self._viewport.show_user_message(event.text)
        elif isinstance(event, AssistantMessageStarted):
            self._viewport.start_assistant_message()
        elif isinstance(event, AssistantDelta):
            self._viewport.append_assistant_delta(event.text)
        elif isinstance(event, AssistantMessage):
            self._viewport.finish_assistant_message(event.text)
        elif isinstance(event, ToolCallRequested):
            self._viewport.show_tool_call(event.call)
        elif isinstance(event, ToolCallFinished):
            self._viewport.show_tool_result(event.call, event.ok, event.output)
        elif isinstance(event, ErrorOccurred):
            self._viewport.show_error(event.message, event.detail)
        elif isinstance(event, RunFinished):
            self._viewport.set_status("就绪")

    def reset(self) -> None:
        """清空会话历史与界面记录。"""
        self._agent.reset()
        self._viewport.clear_transcript()
        self._viewport.set_status("就绪")


__all__ = ["ChatController", "ChatViewPort"]

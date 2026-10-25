"""对话区控件：负责渲染用户、助手、工具与错误消息。"""

from __future__ import annotations

from textual.containers import VerticalScroll
from textual.widgets import Markdown, Static

from core import ToolCall

MAX_INLINE_LENGTH = 800
"""工具输出在对话区中最多展示的字符数。"""


def truncate(text: str, limit: int = MAX_INLINE_LENGTH) -> str:
    """超长文本截断，避免刷屏。"""
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n…（内容过长，已截断，共 {len(text)} 字符）"


class ChatView(VerticalScroll):
    """对话记录视图。

    只负责"把内容显示出来"，不包含任何业务逻辑。
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._assistant: Markdown | None = None
        self._assistant_buffer = ""

    # ------------------------------------------------------------------ 消息

    def add_user_message(self, text: str) -> None:
        """追加一条用户消息。"""
        self._append(Static(f"你 › {text}", classes="user-message", markup=False))

    def start_assistant_message(self) -> None:
        """开始一条助手消息（后续增量会不断刷新它）。"""
        self._assistant_buffer = ""
        widget = Markdown("")
        self._assistant = widget
        self._append(widget)

    def append_assistant_delta(self, text: str) -> None:
        """追加助手回答的流式片段。"""
        self._assistant_buffer += text
        if self._assistant is not None:
            self._assistant.update(self._assistant_buffer)

    def finish_assistant_message(self, text: str) -> None:
        """结束助手消息并定格最终内容。"""
        if self._assistant is not None:
            self._assistant.update(text or self._assistant_buffer)
        self._assistant = None
        self._assistant_buffer = ""

    def add_tool_call(self, call: ToolCall) -> None:
        """展示一次工具调用请求。"""
        arguments = ", ".join(f"{key}={value!r}" for key, value in call.arguments.items())
        label = f"⚙ 调用工具 {call.name}"
        if arguments:
            label = f"{label}({arguments})"
        self._append(Static(label, classes="tool-call", markup=False))

    def add_tool_result(self, call: ToolCall, ok: bool, output: str) -> None:
        """展示工具执行结果。"""
        classes = "tool-result" if ok else "tool-result tool-result-error"
        self._append(Static(truncate(output), classes=classes, markup=False))

    def add_error(self, message: str) -> None:
        """展示错误信息。"""
        self._append(Static(f"✖ {message}", classes="error-message", markup=False))

    def add_info(self, message: str) -> None:
        """展示普通提示信息。"""
        self._append(Static(message, classes="info-message", markup=False))

    def clear(self) -> None:
        """清空整个对话区。"""
        self.remove_children()
        self._assistant = None
        self._assistant_buffer = ""

    # ------------------------------------------------------------------ 内部

    def _append(self, widget) -> None:
        self.mount(widget)
        self.scroll_end(animate=False)


__all__ = ["ChatView", "truncate"]

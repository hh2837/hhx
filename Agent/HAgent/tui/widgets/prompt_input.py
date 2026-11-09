"""输入框控件。"""

from __future__ import annotations

from textual import events
from textual.message import Message
from textual.widgets import Input

DEFAULT_PLACEHOLDER = "输入你的问题，回车发送…"
COMPLETION_KEYS = frozenset({"up", "down", "enter", "tab", "escape"})


class PromptInput(Input):
    """底部提问输入框。

    继承自 Textual 的 :class:`~textual.widgets.Input`，回车即提交。
    当斜杠命令补全面板打开时，把方向键 / 回车 / Esc 转发给应用层处理。
    """

    class CompletionKey(Message):
        """补全面板打开时产生的导航按键。"""

        def __init__(self, key: str) -> None:
            super().__init__()
            self.key = key

    def __init__(self, placeholder: str = DEFAULT_PLACEHOLDER, **kwargs) -> None:
        kwargs.setdefault("id", "prompt")
        super().__init__(placeholder=placeholder, **kwargs)
        self._completion_active = False

    def set_completion_active(self, active: bool) -> None:
        self._completion_active = active

    async def _on_key(self, event: events.Key) -> None:
        if self._completion_active and event.key in COMPLETION_KEYS:
            event.stop()
            event.prevent_default()
            self.post_message(self.CompletionKey(event.key))
            return
        await super()._on_key(event)


__all__ = ["COMPLETION_KEYS", "DEFAULT_PLACEHOLDER", "PromptInput"]

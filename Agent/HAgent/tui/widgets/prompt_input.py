"""输入框控件。"""

from __future__ import annotations

from textual.widgets import Input

DEFAULT_PLACEHOLDER = "输入你的问题，回车发送…"


class PromptInput(Input):
    """底部提问输入框。

    继承自 Textual 的 :class:`~textual.widgets.Input`，回车即提交。
    """

    def __init__(self, placeholder: str = DEFAULT_PLACEHOLDER, **kwargs) -> None:
        kwargs.setdefault("id", "prompt")
        super().__init__(placeholder=placeholder, **kwargs)


__all__ = ["DEFAULT_PLACEHOLDER", "PromptInput"]

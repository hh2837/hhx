"""斜杠命令补全引导面板。

当用户在输入框输入 ``/`` 开头的内容时，界面层会把这个面板显示在输入框上方，
展示匹配的命令；支持上下键选择、回车执行、Tab 补全、Esc 关闭。

面板本身不包含任何业务逻辑，只负责"展示候选 + 记住当前选择"，
命令的真正执行由 :class:`~tui.app.HAgentApp` 完成。

实现说明：用 :class:`Vertical` 容器承载一个 :class:`Static` 文本，
通过容器自身的 ``display`` 控制显隐（容器渲染子节点，不依赖自身的
``_render`` 结果，避免 Textual 在 display 切换时的渲染问题）。
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from ..commands import SlashCommand


class CommandPalette(Vertical):
    """命令补全面板。

    使用 :meth:`show_commands` 展示候选、:meth:`hide` 收起；
    通过 :meth:`select_next` / :meth:`select_previous` 移动高亮；
    :meth:`selected_command` 返回当前选中的命令。
    """

    def __init__(self, limit: int = 8, **kwargs) -> None:
        kwargs.setdefault("id", "command-palette")
        super().__init__(**kwargs)
        self._content = Static(" ", id="palette-content", markup=False)
        self._limit = max(limit, 1)
        self._commands: list[SlashCommand] = []
        self._index = 0
        self.display = False

    def compose(self) -> ComposeResult:
        yield self._content

    # ------------------------------------------------------------------ 可见性

    @property
    def visible(self) -> bool:
        return self.display

    def show_commands(self, commands: list[SlashCommand]) -> None:
        """展示候选命令并复位选择。"""
        self._commands = list(commands)[: self._limit]
        self._index = 0
        self._redraw()
        self.display = True

    def hide(self) -> None:
        """收起面板。"""
        self.display = False
        self._commands = []
        self._index = 0

    # ------------------------------------------------------------------ 选择

    @property
    def selected_command(self) -> SlashCommand | None:
        if 0 <= self._index < len(self._commands):
            return self._commands[self._index]
        return None

    def select_next(self) -> None:
        if not self._commands:
            return
        self._index = (self._index + 1) % len(self._commands)
        self._redraw()

    def select_previous(self) -> None:
        if not self._commands:
            return
        self._index = (self._index - 1) % len(self._commands)
        self._redraw()

    def update_limit(self, limit: int) -> None:
        self._limit = max(limit, 1)

    # ------------------------------------------------------------------ 内部

    def _redraw(self) -> None:
        if not self._commands:
            self._content.update("（没有匹配的命令）")
            return
        lines: list[str] = []
        for index, command in enumerate(self._commands):
            marker = "▸" if index == self._index else " "
            lines.append(f"{marker} {command.name}  {command.description}")
        self._content.update("\n".join(lines))


__all__ = ["CommandPalette"]

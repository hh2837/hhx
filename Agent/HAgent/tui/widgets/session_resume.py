"""会话恢复面板：列出历史会话，供用户选择恢复。

这是一个模态界面：上下键选择会话、回车恢复、Esc 取消。
选择后通过 :meth:`dismiss` 把选中的 :class:`~core.agent.session.Session`
返回给应用层；取消时返回 ``None``。
"""

from __future__ import annotations

import time
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, ListItem, ListView, Static

from core import Session


def _format_time(timestamp: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))


class SessionResumeScreen(ModalScreen[Session | None]):
    """历史会话选择面板。"""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "dismiss", "取消"),
        Binding("enter", "restore", "恢复"),
    ]

    def __init__(self, sessions: list[Session]) -> None:
        super().__init__()
        self._sessions = list(sessions)

    def compose(self) -> ComposeResult:
        with Vertical(id="resume-dialog"):
            yield Static("恢复历史会话", id="resume-title", markup=False)
            if not self._sessions:
                yield Static("（暂无已保存的会话，可用 /save 保存当前会话）", id="resume-empty", markup=False)
            else:
                yield Label(f"共 {len(self._sessions)} 个会话，↑↓ 选择，回车恢复，Esc 取消", id="resume-hint")
                with VerticalScroll(id="resume-list-scroll"):
                    yield ListView(
                        *[
                            ListItem(
                                Static(
                                    f"{_format_time(session.updated_at)}  │  {session.title}  │  "
                                    f"{len(session.messages)} 条消息",
                                    markup=False,
                                )
                            )
                            for session in self._sessions
                        ],
                        id="resume-list",
                    )
                with Vertical(id="resume-actions"):
                    yield Button("取消", id="resume-cancel", variant="default")
                    yield Button("恢复", id="resume-confirm", variant="primary")

    def on_mount(self) -> None:
        if self._sessions:
            self.query_one("#resume-list", ListView).focus()
        else:
            self.query_one("#resume-cancel", Button).focus()

    def action_restore(self) -> None:
        """回车：恢复当前高亮的会话。"""
        if not self._sessions:
            self.dismiss(None)
            return
        index = self.query_one("#resume-list", ListView).index
        self.dismiss(self._sessions[index])

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        index = event.list_view.index
        if 0 <= index < len(self._sessions):
            self.dismiss(self._sessions[index])

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "resume-cancel":
            self.dismiss(None)
        elif event.button.id == "resume-confirm":
            self.action_restore()


__all__ = ["SessionResumeScreen"]

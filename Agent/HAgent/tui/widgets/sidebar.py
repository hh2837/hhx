"""侧边栏控件：会话信息 + 工具活动日志。"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Label, RichLog, Static


class Sidebar(VerticalScroll):
    """右侧信息面板。"""

    def compose(self) -> ComposeResult:
        yield Label("会话信息", classes="panel-title")
        yield Static("（暂无）", id="session-info")
        yield Label("工具活动", classes="panel-title")
        yield RichLog(id="tool-log", markup=False, highlight=False, wrap=True)

    def update_session_info(self, text: str) -> None:
        """刷新会话信息区域。"""
        self.query_one("#session-info", Static).update(text)

    def log(self, text: str) -> None:
        """向工具活动日志追加一行。"""
        self.query_one("#tool-log", RichLog).write(text)


__all__ = ["Sidebar"]

"""配置缺失提示面板。

当启动时发现没有 ``config.ini``，程序会自动生成一份含 mock 信息的配置，
并弹出本面板告知用户：请编辑配置后重新启动程序，才能正常工作。

本面板是模态的，只提供退出程序一个动作，不进入正常对话流程。
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfigNoticeScreen(ModalScreen[None]):
    """提示用户修改配置后重启的模态面板。"""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "quit_app", "退出"),
        Binding("ctrl+q", "quit_app", "退出"),
    ]

    def __init__(self, config_path: str, restart_command: str = "python main.py") -> None:
        super().__init__()
        self.config_path = config_path
        self.restart_command = restart_command

    def compose(self) -> ComposeResult:
        with Vertical(id="config-notice-dialog"):
            yield Static("未找到配置文件", id="config-notice-title", markup=False)
            yield Static(
                f"未找到 config.ini，已为你自动生成一份包含 mock 信息的配置：\n\n"
                f"  {self.config_path}\n\n"
                "请用编辑器打开该文件，填写真实的模型接口（base_url / api_key / model 等）"
                "后再重新启动程序：\n\n"
                f"  {self.restart_command}\n\n"
                "直接使用当前的 mock 配置无法正常调用大模型。",
                id="config-notice-body",
                markup=False,
            )
            yield Static("（按 Esc 或点击下方按钮退出程序）", id="config-notice-hint", markup=False)
            yield Button("退出程序", id="config-notice-quit", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#config-notice-quit", Button).focus()

    def action_quit_app(self) -> None:
        self.app.exit(0)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "config-notice-quit":
            self.action_quit_app()


__all__ = ["ConfigNoticeScreen"]

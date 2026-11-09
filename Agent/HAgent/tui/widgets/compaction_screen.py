"""上下文压缩结果面板：左侧原文，右侧压缩摘要。"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Markdown, Static


class CompactionScreen(ModalScreen[None]):
    """展示压缩前后内容的模态面板。

    左右两栏都放在 :class:`VerticalScroll` 中，鼠标滚轮可直接滚动；
    按 ``Esc`` 或点击「关闭」按钮返回对话界面。
    """

    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "dismiss", "关闭")]

    def __init__(
        self,
        original_text: str,
        summary_text: str,
        archive_id: str = "",
        archive_path: str = "",
        message_count: int = 0,
    ) -> None:
        super().__init__()
        self.original_text = original_text
        self.summary_text = summary_text
        self.archive_id = archive_id
        self.archive_path = archive_path
        self.message_count = message_count

    def compose(self) -> ComposeResult:
        meta = f"归档编号：{self.archive_id}  │  原始消息：{self.message_count} 条"
        if self.archive_path:
            meta = f"{meta}  │  {self.archive_path}"

        with Vertical(id="compaction-dialog"):
            yield Static("上下文压缩结果", id="compaction-title", markup=False)
            yield Static(meta, id="compaction-meta", markup=False)
            with Horizontal(id="compaction-panes"):
                with Vertical(id="compaction-original-pane", classes="compaction-pane"):
                    yield Label("压缩前原文", classes="compaction-pane-title")
                    with VerticalScroll(id="compaction-original-scroll"):
                        yield Static(
                            self.original_text or "（无原始内容）",
                            classes="compaction-content",
                            markup=False,
                        )
                with Vertical(id="compaction-summary-pane", classes="compaction-pane"):
                    yield Label("压缩后内容", classes="compaction-pane-title")
                    with VerticalScroll(id="compaction-summary-scroll"):
                        yield Markdown(self.summary_text or "（无摘要内容）")
            with Horizontal(id="compaction-actions"):
                yield Button("关闭", id="close-compaction", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#close-compaction", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-compaction":
            self.dismiss()


__all__ = ["CompactionScreen"]

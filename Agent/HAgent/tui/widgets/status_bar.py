"""状态栏控件：展示模型、上下文占用、工作目录与当前状态。"""

from __future__ import annotations

from textual.widgets import Static

from core import format_token_count


def format_context(
    used_tokens: int,
    window_tokens: int,
    ratio: float,
    is_default: bool,
) -> str:
    """格式化上下文占用信息，例如 ``12.3k / 128k (9.6%，默认)``。"""
    percent = ratio * 100
    default_note = "，默认" if is_default else ""
    return (
        f"{format_token_count(used_tokens)} / {format_token_count(window_tokens)}"
        f"（{percent:.1f}%{default_note}）"
    )


class StatusBar(Static):
    """底部一行状态信息。"""

    def __init__(
        self,
        model: str = "",
        workspace: str = "",
        status: str = "就绪",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._model = model
        self._workspace = workspace
        self._status = status
        self._used_tokens = 0
        self._window_tokens = 0
        self._ratio = 0.0
        self._window_is_default = True
        self._needs_compaction = False
        self._refresh_text()

    def set_status(self, status: str) -> None:
        """更新右侧状态文本（如"思考中…"）。"""
        self._status = status
        self._refresh_text()

    def set_model(self, model: str) -> None:
        self._model = model
        self._refresh_text()

    def set_workspace(self, workspace: str) -> None:
        self._workspace = workspace
        self._refresh_text()

    def set_context(
        self,
        used_tokens: int,
        window_tokens: int,
        ratio: float,
        window_is_default: bool,
        needs_compaction: bool = False,
    ) -> None:
        """更新上下文占用信息。"""
        self._used_tokens = used_tokens
        self._window_tokens = window_tokens
        self._ratio = ratio
        self._window_is_default = window_is_default
        self._needs_compaction = needs_compaction
        self._refresh_text()

    def _refresh_text(self) -> None:
        context = format_context(
            self._used_tokens,
            self._window_tokens,
            self._ratio,
            self._window_is_default,
        )
        prefix = "⚠ " if self._needs_compaction else ""
        self.update(
            f"模型：{self._model}  │  {prefix}上下文：[b]{context}[/b]  │  "
            f"工作目录：{self._workspace}  │  状态：{self._status}"
        )
        if self._needs_compaction:
            self.add_class("status-warning")
        else:
            self.remove_class("status-warning")


__all__ = ["StatusBar", "format_context"]

"""状态栏控件：展示模型、工作目录与当前状态。"""

from __future__ import annotations

from textual.widgets import Static


class StatusBar(Static):
    """底部一行状态信息。"""

    def __init__(self, model: str = "", workspace: str = "", status: str = "就绪", **kwargs) -> None:
        super().__init__(**kwargs)
        self._model = model
        self._workspace = workspace
        self._status = status
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

    def _refresh_text(self) -> None:
        self.update(f"模型：{self._model}  │  工作目录：{self._workspace}  │  状态：{self._status}")


__all__ = ["StatusBar"]

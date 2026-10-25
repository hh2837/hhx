"""xAgent 的终端界面（TUI）前端。

前端只依赖 :mod:`core` 暴露的公共 API；后续新增 ``web`` / ``desktop`` /
``mobile`` 前端时，也遵循同样的依赖方向。
"""

from .app import XAgentApp, create_app
from .controller import ChatController, ChatViewPort

__all__ = ["ChatController", "ChatViewPort", "XAgentApp", "create_app"]

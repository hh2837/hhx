"""``python -m tui`` 入口。"""

from __future__ import annotations

from core import ConfigLoader

from .app import XAgentApp


def main() -> None:
    """加载配置并启动 TUI。"""
    config = ConfigLoader().load()
    XAgentApp(config).run()


if __name__ == "__main__":
    main()

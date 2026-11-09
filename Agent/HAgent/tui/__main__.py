"""``python -m tui`` 入口。"""

from __future__ import annotations

from pathlib import Path

from core import ConfigLoader

from .app import HAgentApp


def main() -> None:
    """加载配置并启动 TUI。

    若项目目录下没有 config.ini，会自动生成一份含 mock 信息的配置，
    并弹出提示面板，告知用户修改后重新启动。
    """
    loader = ConfigLoader()
    config_missing = not Path(loader.target_config_path()).exists()
    config = loader.load()
    HAgentApp(config, config_notice=config_missing).run()


if __name__ == "__main__":
    main()

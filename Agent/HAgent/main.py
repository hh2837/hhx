#!/usr/bin/env python
"""xAgent 统一启动入口。

当前提供 TUI 前端；后续新增 web / desktop / mobile 前端时，只需在此增加
对应的子命令，核心业务逻辑保持不变。

示例::

    python main.py                                  # 使用 config.ini 启动 TUI
    python main.py --workspace D:\\work             # 指定工作目录
    python main.py --model "DeepSeek V4.1 Flash"    # 临时覆盖模型
    python main.py --list-tools                     # 查看内置工具后退出
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path

from core import AppConfig, ConfigError, ConfigLoader, build_tools
from tui import XAgentApp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xagent",
        description="xAgent：核心与界面分离的多端 Agent 框架（当前内置 TUI 前端）。",
    )
    parser.add_argument("--config", type=Path, default=None, help="配置文件路径（默认 xAgent/config.ini）")
    parser.add_argument("--workspace", type=Path, default=None, help="工作目录（同时作为文件工具沙箱根目录）")
    parser.add_argument("--base-url", default=None, help="覆盖大模型 base_url")
    parser.add_argument("--api-key", default=None, help="覆盖大模型 api_key")
    parser.add_argument("--model", default=None, help="覆盖模型名")
    parser.add_argument("--theme", default=None, help="Textual 主题名，例如 textual-dark")
    parser.add_argument("--no-sidebar", action="store_true", help="隐藏右侧信息栏")
    parser.add_argument("--list-tools", action="store_true", help="列出内置工具后退出")
    return parser


def apply_overrides(config: AppConfig, args: argparse.Namespace) -> AppConfig:
    """把命令行参数合并进配置。"""
    llm = config.llm
    if args.base_url:
        llm = dataclasses.replace(llm, base_url=args.base_url)
    if args.api_key:
        llm = dataclasses.replace(llm, api_key=args.api_key)
    if args.model:
        llm = dataclasses.replace(llm, model=args.model)
    config = dataclasses.replace(config, llm=llm)

    ui = config.ui
    if args.theme:
        ui = dataclasses.replace(ui, theme=args.theme)
    if args.no_sidebar:
        ui = dataclasses.replace(ui, show_sidebar=False)
    config = dataclasses.replace(config, ui=ui)

    if args.workspace:
        config = config.with_workspace(Path(args.workspace))
    return config


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        config = ConfigLoader(config_path=args.config).load()
    except ConfigError as exc:
        print(f"[配置错误] {exc}", file=sys.stderr)
        return 1

    config = apply_overrides(config, args)

    if args.list_tools:
        registry = build_tools(config)
        print(f"已注册 {len(registry)} 个工具：")
        for spec in registry.specs():
            print(f"  - {spec.name}: {spec.description}")
        return 0

    if not config.llm.model:
        print("[配置错误] 未配置模型名，请在 config.ini 的 [LLM] 段填写 model，或使用 --model 指定。", file=sys.stderr)
        return 1

    XAgentApp(config).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

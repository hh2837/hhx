from __future__ import annotations

import subprocess
from typing import Any

from .base import ToolResult
from .registry import ToolRegistry


class RunCliTools:
    def __init__(self) -> None:
        pass

    def runcli(self, command: str, args: list[str] | None = None) -> str:
        """调用本地已安装的命令行程序。
        Args:
            command: 程序名称或可执行文件路径
            args: 参数列表
        """
        cmd_name = str(command).strip() if command is not None else ""
        if not cmd_name:
            err = ToolResult.failure("程序名称不能为空。").error
            return err or "程序名称不能为空。"

        if args is None:
            args_list: list[str] = []
        elif isinstance(args, list):
            args_list = []
            for item in args:
                args_list.append(str(item))
        else:
            # try to be flexible
            args_list = [str(args)]

        cmd = [cmd_name] + args_list

        try:
            proc = subprocess.run(cmd, capture_output=True, shell=False, timeout=60)
        except subprocess.TimeoutExpired:
            err = ToolResult.failure("命令执行超时（60秒）。").error
            return err or "命令执行超时（60秒）。"
        except FileNotFoundError:
            err = ToolResult.failure(f"未找到命令或可执行文件：{cmd_name}").error
            return err or f"未找到命令或可执行文件：{cmd_name}"
        except OSError as exc:
            err = ToolResult.failure(f"执行命令失败：{exc}").error
            return err or f"执行命令失败：{exc}"
        except Exception as exc:
            err = ToolResult.failure(f"执行命令失败：{exc}").error
            return err or f"执行命令失败：{exc}"

        stdout = proc.stdout.decode("utf-8", errors="replace") if proc.stdout is not None else ""
        stderr = proc.stderr.decode("utf-8", errors="replace") if proc.stderr is not None else ""

        max_len = 8000
        truncated = False
        if len(stdout) > max_len:
            stdout = stdout[:max_len] + "\n\n[...输出已截断...]\n"
            truncated = True
        if len(stderr) > max_len:
            stderr = stderr[:max_len] + "\n\n[...输出已截断...]\n"
            truncated = True

        lines: list[str] = []
        lines.append(f"命令: {cmd_name} {' '.join(args_list)}".rstrip())
        lines.append(f"退出码: {proc.returncode}")
        if truncated:
            lines.append("注意：输出过长已截断（单项最多8000字符）")
        lines.append("")
        lines.append("=== 标准输出 (stdout) ===")
        lines.append(stdout if stdout else "(空)")
        lines.append("")
        lines.append("=== 标准错误 (stderr) ===")
        lines.append(stderr if stderr else "(空)")
        return "\n".join(lines)


def register_runcli_tools(registry: ToolRegistry) -> ToolRegistry:
    tools = RunCliTools()
    registry.tool(name="RunCli")(tools.runcli)
    return registry


__all__ = ["RunCliTools", "register_runcli_tools"]

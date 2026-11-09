"""斜杠命令注册表。

命令只描述界面层可以执行的交互动作，不包含任何模型或工具调用逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SlashCommand:
    """一条斜杠命令的元信息。"""

    name: str
    description: str
    aliases: tuple[str, ...] = field(default_factory=tuple)

    @property
    def keyword(self) -> str:
        return self.name.lstrip("/")

    def matches(self, query: str) -> bool:
        query = query.lower()
        if not query:
            return True
        return self.keyword.startswith(query) or any(
            alias.lstrip("/").startswith(query) for alias in self.aliases
        )


COMMANDS: tuple[SlashCommand, ...] = (
    SlashCommand("/help", "查看全部命令与用法"),
    SlashCommand("/new", "新建会话（自动保存当前会话）", aliases=("/reset",)),
    SlashCommand("/resume", "列出并恢复历史会话", aliases=("/sessions",)),
    SlashCommand("/save", "保存当前会话到磁盘"),
    SlashCommand("/compact", "压缩上下文并归档原始记录"),
    SlashCommand("/status", "查看模型、上下文与会话状态"),
    SlashCommand("/clear", "清空界面（保留历史）"),
    SlashCommand("/quit", "退出程序", aliases=("/exit",)),
)

_COMMAND_INDEX: dict[str, SlashCommand] = {}
for _command in COMMANDS:
    _COMMAND_INDEX[_command.name] = _command
    for _alias in _command.aliases:
        _COMMAND_INDEX[_alias] = _command


def match_commands(text: str, limit: int = 8) -> list[SlashCommand]:
    """根据输入框内容返回补全候选；输入不是斜杠命令时返回空列表。"""
    stripped = text.strip()
    if not stripped.startswith("/") or any(char.isspace() for char in stripped):
        return []
    query = stripped[1:].lower()
    matches = [command for command in COMMANDS if command.matches(query)]
    return matches[: max(limit, 0)]


def resolve_command(text: str) -> SlashCommand | None:
    """解析完整输入中的命令部分，支持别名。"""
    parts = text.strip().split(maxsplit=1)
    if not parts:
        return None
    return _COMMAND_INDEX.get(parts[0].lower())


def command_help_text() -> str:
    """生成帮助面板 / 对话区使用的命令说明。"""
    lines = ["可用命令："]
    for command in COMMANDS:
        aliases = f"（别名：{'、'.join(command.aliases)}）" if command.aliases else ""
        lines.append(f"  {command.name:<10} {command.description}{aliases}")
    return "\n".join(lines)


__all__ = [
    "COMMANDS",
    "SlashCommand",
    "command_help_text",
    "match_commands",
    "resolve_command",
]

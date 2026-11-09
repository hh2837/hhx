"""Skill 工具：按需加载 Skill，并按用户要求创建新的 Skill。"""

from __future__ import annotations

from ..errors import SkillError
from ..skills import SkillRegistry
from .base import ToolResult
from .registry import ToolRegistry


def register_load_skill_tool(registry: ToolRegistry, skills: SkillRegistry) -> ToolRegistry:
    """注册 ``loadSkill`` 工具。"""
    if "loadSkill" in registry:
        return registry

    @registry.tool(
        name="loadSkill",
        description=(
            "加载指定 Skill 的完整说明，或加载该 Skill 目录内的附加文件。"
            "当任务与可用 Skill 匹配时，先调用本工具获取操作步骤。"
        ),
    )
    def load_skill(name: str, filename: str | None = None) -> ToolResult:
        """加载 Skill 说明或附加文件。

        Args:
            name: Skill 名称（见系统提示词中的可用 Skills 列表）
            filename: 可选。附加文件路径，可相对于 Skill 目录、项目根目录，或使用绝对路径；
                只提供文件名时会递归搜索 Skill 目录，同名文件不唯一时返回候选列表
        """
        try:
            if filename is None or not filename.strip():
                instructions = skills.load_instructions(name)
                return ToolResult.success(f"# Skill: {name}\n\n{instructions}")

            skill_dir = skills.get(name).directory.resolve()
            result = skills.load_file(name, filename)
            if result.candidates:
                listing = "\n".join(
                    f"- {candidate.relative_to(skill_dir).as_posix()}" for candidate in result.candidates
                )
                return ToolResult.success(
                    f"找到多个名为 `{filename}` 的文件，请指定更精确的 filename：\n{listing}"
                )
            if result.path is None:
                return ToolResult.failure(f"未找到文件：{filename}（Skill：{name}）")

            relative = result.path.relative_to(skill_dir).as_posix()
            return ToolResult.success(f"# Skill: {name} / {relative}\n\n{result.content}")
        except SkillError as exc:
            return ToolResult.failure(str(exc))

    return registry


def register_create_skill_tool(registry: ToolRegistry, skills: SkillRegistry) -> ToolRegistry:
    """注册 ``createSkill`` 工具。"""
    if "createSkill" in registry:
        return registry

    @registry.tool(
        name="createSkill",
        description=(
            "创建一个新的 Agent Skill，并在当前项目的 .agents/skills/<name>/SKILL.md 写入内容。"
            "当用户要求创建 Skill 时使用。Skill 已存在时不会覆盖。"
            "如需补充 references/、scripts/ 等目录或辅助文件，请在创建后继续调用文件工具。"
        ),
    )
    def create_skill(name: str, skillContext: str) -> ToolResult:
        """创建新的 Skill。

        Args:
            name: Skill 名称，只能由小写字母、数字和连字符组成（例如 my-skill）
            skillContext: 要写入 SKILL.md 的完整内容；推荐包含 YAML Frontmatter（name、description）
                与正文，缺少 Frontmatter 或 description 时工具会自动补全
        """
        try:
            skill = skills.create_skill(name, skillContext)
        except SkillError as exc:
            return ToolResult.failure(str(exc))

        register_load_skill_tool(registry, skills)
        return ToolResult.success(
            f"已创建 Skill `{skill.name}`：{skill.path}\n"
            "如需添加 references/、scripts/ 等目录或辅助文件，请继续调用 create_dir、create_file、write_file。"
        )

    return registry


def register_skill_tools(
    registry: ToolRegistry,
    skills: SkillRegistry,
    *,
    include_load: bool = True,
    include_create: bool = True,
) -> ToolRegistry:
    """注册 Skill 相关工具。"""
    if include_load:
        register_load_skill_tool(registry, skills)
    if include_create:
        register_create_skill_tool(registry, skills)
    return registry


__all__ = [
    "register_create_skill_tool",
    "register_load_skill_tool",
    "register_skill_tools",
]

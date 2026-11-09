"""Agent Skills 支持：发现并注册 ``.agents/skills`` 下的技能。

初始化阶段只解析每个 ``SKILL.md`` 的 YAML Frontmatter（``name`` 与
``description``），完整正文在首次请求时通过 :meth:`SkillRegistry.load_instructions`
按需读取，避免把全部技能内容提前塞进上下文。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .errors import SkillError, SkillNotFoundError

logger = logging.getLogger(__name__)

SKILL_FILENAME = "SKILL.md"
SKILLS_DIRECTORY = Path(".agents") / "skills"
_FRONTMATTER_DELIMITER = "---"
_SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MAX_NAME_LENGTH = 64
_MAX_DESCRIPTION_LENGTH = 1024


@dataclass(frozen=True, slots=True)
class Skill:
    """一个已发现的 Skill（仅包含元数据）。"""

    name: str
    description: str
    path: Path

    @property
    def directory(self) -> Path:
        """Skill 所在目录。"""
        return self.path.parent


@dataclass(frozen=True, slots=True)
class SkillFileResult:
    """Skill 附加文件的查找结果。

    ``path`` 表示唯一匹配到的文件；``candidates`` 非空表示同名文件不唯一；
    两者都为空表示没有找到。``content`` 仅在唯一匹配时填充。
    """

    path: Path | None = None
    content: str = ""
    candidates: tuple[Path, ...] = ()


def _read_frontmatter(path: Path) -> dict[str, Any]:
    """只读取 ``SKILL.md`` 开头的 Frontmatter，不把正文载入内存。"""
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            first_line = stream.readline()
            if first_line.strip() != _FRONTMATTER_DELIMITER:
                raise SkillError(f"Skill 文件缺少 YAML Frontmatter：{path}")

            frontmatter_lines: list[str] = []
            for line in stream:
                if line.strip() == _FRONTMATTER_DELIMITER:
                    break
                frontmatter_lines.append(line)
            else:
                raise SkillError(f"Skill Frontmatter 未闭合：{path}")
    except OSError as exc:
        raise SkillError(f"无法读取 Skill 文件：{path}（{exc}）") from exc

    try:
        data = yaml.safe_load("".join(frontmatter_lines))
    except yaml.YAMLError as exc:
        raise SkillError(f"Skill Frontmatter YAML 解析失败：{path}（{exc}）") from exc

    if not isinstance(data, dict):
        raise SkillError(f"Skill Frontmatter 必须是 YAML 映射：{path}")
    return data


def _validate_skill_name(name: str) -> str:
    """校验 Skill 名称是否符合 Agent Skills 规范。"""
    normalized = name.strip()
    if not normalized:
        raise SkillError("Skill 名称不能为空")
    if len(normalized) > _MAX_NAME_LENGTH or not _SKILL_NAME_PATTERN.fullmatch(normalized):
        raise SkillError(
            f"Skill 名称不合法：{name!r}。名称只能由小写字母、数字和连字符组成，"
            "且不能以连字符开头或结尾（例如 my-skill）。"
        )
    return normalized


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """把 ``skillContext`` 拆成 Frontmatter 字典与正文。

    传入内容可以带 Frontmatter，也可以只包含正文；缺少 Frontmatter 时返回空字典。
    """
    stripped = text.lstrip("\ufeff").strip()
    lines = stripped.splitlines()
    if not lines or lines[0].strip() != _FRONTMATTER_DELIMITER:
        return {}, stripped

    closing_index: int | None = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == _FRONTMATTER_DELIMITER:
            closing_index = index
            break
    if closing_index is None:
        raise SkillError("skillContext 的 YAML Frontmatter 未闭合，请补全结束的 `---`")

    raw_frontmatter = "\n".join(lines[1:closing_index])
    if not raw_frontmatter.strip():
        data: Any = {}
    else:
        try:
            data = yaml.safe_load(raw_frontmatter)
        except yaml.YAMLError as exc:
            raise SkillError(f"skillContext 的 YAML Frontmatter 解析失败：{exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise SkillError("skillContext 的 YAML Frontmatter 必须是映射（key: value）")

    body = "\n".join(lines[closing_index + 1 :]).strip()
    return data, body


def _derive_description(body: str, name: str) -> str:
    """正文没有提供 description 时，用第一个有效段落生成一个简短描述。"""
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "```", ">", "- ", "* ", "|")):
            continue
        return line[:_MAX_DESCRIPTION_LENGTH]
    return f"Skill `{name}`"


def _build_skill_document(name: str, skill_context: str) -> str:
    """生成符合 Agent Skills 规范的 ``SKILL.md`` 内容。"""
    if not skill_context.strip():
        raise SkillError("skillContext 不能为空，请提供 SKILL.md 的正文内容")

    frontmatter, body = _split_frontmatter(skill_context)
    if not body:
        raise SkillError("skillContext 缺少正文内容，请在 Frontmatter 之后补充 SKILL.md 正文")

    description = frontmatter.get("description")
    if not isinstance(description, str) or not description.strip():
        description = _derive_description(body, name)
    description = description.strip()

    document: dict[str, Any] = {"name": name, "description": description}
    for key, value in frontmatter.items():
        if key not in document:
            document[key] = value

    try:
        rendered = yaml.safe_dump(
            document,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        ).strip()
    except yaml.YAMLError as exc:  # pragma: no cover - safe_dump 很少失败
        raise SkillError(f"生成 YAML Frontmatter 失败：{exc}") from exc

    return f"{_FRONTMATTER_DELIMITER}\n{rendered}\n{_FRONTMATTER_DELIMITER}\n\n{body}\n"


def _read_body(path: Path) -> str:
    """读取 Frontmatter 之后的 Skill 正文。"""
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            first_line = stream.readline()
            if first_line.strip() != _FRONTMATTER_DELIMITER:
                raise SkillError(f"Skill 文件缺少 YAML Frontmatter：{path}")

            for line in stream:
                if line.strip() == _FRONTMATTER_DELIMITER:
                    return stream.read().strip()
            raise SkillError(f"Skill Frontmatter 未闭合：{path}")
    except OSError as exc:
        raise SkillError(f"无法读取 Skill 文件：{path}（{exc}）") from exc


def load_skill_metadata(path: Path) -> Skill:
    """解析一个 ``SKILL.md`` 的元数据。

    ``name`` 与 ``description`` 是必需字段；字段缺失或为空时抛出
    :class:`SkillError`。不符合规范的命名只记录警告，不影响加载。
    """
    path = Path(path)
    data = _read_frontmatter(path)

    raw_name = data.get("name")
    raw_description = data.get("description")
    if not isinstance(raw_name, str) or not raw_name.strip():
        raise SkillError(f"Skill 缺少必需的 name 字段：{path}")
    if not isinstance(raw_description, str) or not raw_description.strip():
        raise SkillError(f"Skill 缺少必需的 description 字段：{path}")

    name = raw_name.strip()
    description = raw_description.strip()
    if len(name) > _MAX_NAME_LENGTH or not _SKILL_NAME_PATTERN.fullmatch(name):
        logger.warning("Skill 名称不符合 Agent Skills 规范：%s（%s）", name, path)
    if path.parent.name != name:
        logger.warning("Skill 名称与目录名不一致：%s != %s", name, path.parent.name)
    if len(description) > _MAX_DESCRIPTION_LENGTH:
        logger.warning("Skill 描述超过 %d 个字符：%s", _MAX_DESCRIPTION_LENGTH, name)

    return Skill(name=name, description=description, path=path)


class SkillRegistry:
    """Skill 注册表：负责发现、登记与按需加载正文。

    使用示例::

        skills = SkillRegistry.discover()
        print(skills.names())
        instructions = skills.load_instructions("my-skill")
    """

    def __init__(self, skills: Sequence[Skill] = (), root: Path | None = None) -> None:
        self._skills: dict[str, Skill] = {}
        self._instructions: dict[str, str] = {}
        self._root = Path(root).expanduser().resolve() if root is not None else None
        for skill in skills:
            self.register(skill)

    # ------------------------------------------------------------------ 属性

    @property
    def root(self) -> Path:
        """项目根目录：Skill 会被创建到 ``<root>/.agents/skills`` 下。"""
        return self._root if self._root is not None else Path.cwd().resolve()

    @property
    def skills_directory(self) -> Path:
        """当前项目的 Skill 根目录。"""
        return self.root / SKILLS_DIRECTORY

    # ------------------------------------------------------------------ 发现

    @classmethod
    def discover(cls, root: Path | None = None) -> SkillRegistry:
        """以 ``root``（缺省为当前工作目录）为项目根目录扫描 Skill。"""
        project_root = Path(root).expanduser().resolve() if root is not None else Path.cwd()
        registry = cls(root=project_root)
        skills_dir = project_root / SKILLS_DIRECTORY
        if not skills_dir.is_dir():
            logger.debug("未找到 Skill 目录：%s", skills_dir)
            return registry

        for entry in sorted(skills_dir.iterdir(), key=lambda item: item.name.casefold()):
            if not entry.is_dir():
                continue
            skill_path = entry / SKILL_FILENAME
            if not skill_path.is_file():
                logger.warning("跳过 Skill 目录 %s：缺少 %s", entry, SKILL_FILENAME)
                continue
            try:
                skill = load_skill_metadata(skill_path)
            except SkillError as exc:
                logger.warning("跳过无效 Skill %s：%s", entry, exc)
                continue
            if skill.name in registry:
                logger.warning("跳过重复 Skill：%s（%s）", skill.name, skill_path)
                continue
            registry.register(skill)

        logger.info("已发现 %d 个 Skill：%s", len(registry), ", ".join(registry.names()) or "无")
        return registry

    # ------------------------------------------------------------------ 注册

    def register(self, skill: Skill) -> Skill:
        """登记一个 Skill（同名覆盖），并清空对应的正文缓存。"""
        if not skill.name:
            raise SkillError("Skill 名称不能为空")
        self._skills[skill.name] = skill
        self._instructions.pop(skill.name, None)
        return skill

    # ------------------------------------------------------------------ 创建

    def create_skill(self, name: str, skill_context: str) -> Skill:
        """在 ``.agents/skills/<name>`` 下创建新的 ``SKILL.md``。

        目标目录或 ``SKILL.md`` 已存在时抛出 :class:`SkillError`，不会覆盖原内容。
        创建成功后会把新 Skill 登记到当前注册表，随后即可通过 ``loadSkill`` 使用。
        """
        skill_name = _validate_skill_name(name)
        skill_dir = self.skills_directory / skill_name
        skill_path = skill_dir / SKILL_FILENAME
        if skill_dir.exists() or skill_path.exists() or skill_name in self._skills:
            raise SkillError(
                f"Skill 已存在：{skill_name}（{skill_path}）。为避免覆盖原有内容，未做任何修改。"
            )

        document = _build_skill_document(skill_name, skill_context)
        try:
            skill_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise SkillError(
                f"Skill 已存在：{skill_name}（{skill_path}）。为避免覆盖原有内容，未做任何修改。"
            ) from exc
        except OSError as exc:
            raise SkillError(f"创建 Skill 目录失败：{skill_dir}（{exc}）") from exc

        try:
            skill_path.write_text(document, encoding="utf-8")
        except OSError as exc:
            try:
                skill_dir.rmdir()
            except OSError:
                logger.warning("创建 Skill 失败后无法清理目录：%s", skill_dir)
            raise SkillError(f"写入 Skill 文件失败：{skill_path}（{exc}）") from exc

        skill = load_skill_metadata(skill_path)
        self.register(skill)
        logger.info("已创建 Skill：%s（%s）", skill.name, skill.path)
        return skill

    # ------------------------------------------------------------------ 查询

    def get(self, name: str) -> Skill:
        """按名称获取 Skill；不存在时抛出 :class:`SkillNotFoundError`。"""
        try:
            return self._skills[name]
        except KeyError as exc:
            raise SkillNotFoundError(f"未知 Skill：{name}") from exc

    def names(self) -> list[str]:
        return list(self._skills)

    def specs(self) -> list[Skill]:
        return list(self._skills.values())

    def prompt_block(self) -> str:
        """生成注入系统提示词的 Skill 元数据清单。"""
        if not self._skills:
            return ""
        lines = ["", "You have access to the following skills:"]
        lines.extend(f"- `{skill.name}`: {skill.description}" for skill in self._skills.values())
        lines.extend(
            [
                "",
                "Use the loadSkill tool to load the full instructions of a skill when needed. "
                "You can also load additional files referenced by a skill.",
            ]
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------ 加载

    def load_instructions(self, name: str) -> str:
        """按需读取并缓存指定 Skill 的完整正文。"""
        if name not in self._instructions:
            self._instructions[name] = _read_body(self.get(name).path)
        return self._instructions[name]

    def load_file(self, name: str, filename: str) -> SkillFileResult:
        """读取 Skill 目录内的附加文件，不会隐式加载 ``SKILL.md``。"""
        skill = self.get(name)
        raw_filename = filename.strip()
        if not raw_filename:
            raise SkillError("filename 不能为空")

        path, candidates = self._resolve_file(skill, raw_filename)
        if candidates:
            return SkillFileResult(candidates=candidates)
        if path is None:
            return SkillFileResult()

        try:
            content = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise SkillError(f"无法读取 Skill 文件：{path}（{exc}）") from exc
        return SkillFileResult(path=path, content=content)

    # ------------------------------------------------------------------ 路径解析

    def _resolve_file(self, skill: Skill, filename: str) -> tuple[Path | None, tuple[Path, ...]]:
        """先精确匹配，再对纯文件名做递归唯一性搜索。"""
        skill_dir = skill.directory.resolve()
        for candidate in self._exact_candidates(skill, filename):
            resolved = self._within_directory(candidate, skill_dir)
            if resolved is not None and resolved.is_file():
                return resolved, ()

        if self._is_bare_filename(filename):
            matches = self._search_by_filename(skill_dir, filename)
            if len(matches) == 1:
                return matches[0], ()
            if len(matches) > 1:
                return None, matches
        return None, ()

    def _exact_candidates(self, skill: Skill, filename: str) -> list[Path]:
        raw_path = Path(filename).expanduser()
        if raw_path.is_absolute():
            return [raw_path]

        candidates = [skill.directory / raw_path, skill.directory.parent / raw_path]
        project_root = self._project_root(skill)
        if project_root is not None:
            candidates.append(project_root / raw_path)

        unique: list[Path] = []
        for candidate in candidates:
            if candidate not in unique:
                unique.append(candidate)
        return unique

    def _project_root(self, skill: Skill) -> Path | None:
        if self._root is not None:
            return self._root
        skills_dir = skill.directory.parent
        if skills_dir.name == SKILLS_DIRECTORY.name and skills_dir.parent.name == SKILLS_DIRECTORY.parent.name:
            return skills_dir.parent.parent
        return None

    @staticmethod
    def _is_bare_filename(filename: str) -> bool:
        path = Path(filename)
        return not path.is_absolute() and path.name == filename

    @classmethod
    def _search_by_filename(cls, skill_dir: Path, filename: str) -> tuple[Path, ...]:
        matches: dict[Path, Path] = {}
        for candidate in skill_dir.rglob("*"):
            if candidate.name != filename:
                continue
            resolved = cls._within_directory(candidate, skill_dir)
            if resolved is not None and resolved.is_file():
                matches[resolved] = resolved
        return tuple(sorted(matches, key=lambda item: item.relative_to(skill_dir).as_posix().casefold()))

    @staticmethod
    def _within_directory(candidate: Path, directory: Path) -> Path | None:
        """返回解析后的路径；越出 ``directory`` 或无法解析时返回 ``None``。"""
        try:
            resolved = candidate.resolve()
        except OSError:
            return None
        try:
            resolved.relative_to(directory)
        except ValueError:
            return None
        return resolved

    def __contains__(self, name: object) -> bool:
        return name in self._skills

    def __len__(self) -> int:
        return len(self._skills)

    def __iter__(self) -> Iterator[Skill]:
        return iter(self._skills.values())


def discover_skills(root: Path | None = None) -> SkillRegistry:
    """便捷函数：等价于 :meth:`SkillRegistry.discover`。"""
    return SkillRegistry.discover(root)


__all__ = [
    "SKILLS_DIRECTORY",
    "SKILL_FILENAME",
    "Skill",
    "SkillFileResult",
    "SkillRegistry",
    "discover_skills",
    "load_skill_metadata",
]

"""Agent Skills 发现、注册与按需加载的测试。"""

from __future__ import annotations

from pathlib import Path

import core.skills as skills_module
from core import Agent, AgentConfig, ChatResponse, SkillRegistry, ToolRegistry
from core.llm.client import LLMClient


class FakeClient(LLMClient):
    def chat(self, messages, tools=None):
        return ChatResponse(content="ok")


def _write_skill(
    root: Path,
    directory: str,
    name: str | None = "demo-skill",
    description: str | None = "演示技能",
    body: str = "# 正文\n\n详细步骤",
) -> Path:
    skill_dir = root / ".agents" / "skills" / directory
    skill_dir.mkdir(parents=True, exist_ok=True)
    lines = ["---"]
    if name is not None:
        lines.append(f"name: {name}")
    if description is not None:
        lines.append(f"description: {description}")
    lines.extend(["---", "", body])
    path = skill_dir / "SKILL.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def test_发现Skill时只解析元数据(tmp_path: Path, monkeypatch) -> None:
    _write_skill(tmp_path, "demo-skill")

    def fail_if_body_read(_path: Path) -> str:
        raise AssertionError("初始化阶段不应读取 Skill 正文")

    monkeypatch.setattr(skills_module, "_read_body", fail_if_body_read)

    registry = SkillRegistry.discover(tmp_path)

    assert registry.names() == ["demo-skill"]
    skill = registry.get("demo-skill")
    assert skill.name == "demo-skill"
    assert skill.description == "演示技能"
    assert skill.path == tmp_path / ".agents" / "skills" / "demo-skill" / "SKILL.md"


def test_按需加载正文并缓存(tmp_path: Path) -> None:
    _write_skill(tmp_path, "demo-skill", body="# 正文\n\n详细步骤")
    registry = SkillRegistry.discover(tmp_path)

    assert registry.load_instructions("demo-skill") == "# 正文\n\n详细步骤"
    assert registry.load_instructions("demo-skill") == "# 正文\n\n详细步骤"


def test_缺少必需字段或SKILL_md时跳过(tmp_path: Path) -> None:
    _write_skill(tmp_path, "no-description", description=None)
    _write_skill(tmp_path, "no-name", name=None)
    (tmp_path / ".agents" / "skills" / "no-file").mkdir(parents=True)
    _write_skill(tmp_path, "valid-skill", name="valid-skill", description="有效技能")

    registry = SkillRegistry.discover(tmp_path)

    assert registry.names() == ["valid-skill"]


def test_重复名称只保留一个(tmp_path: Path) -> None:
    _write_skill(tmp_path, "a-skill", name="same-skill", description="A")
    _write_skill(tmp_path, "b-skill", name="same-skill", description="B")

    registry = SkillRegistry.discover(tmp_path)

    assert registry.names() == ["same-skill"]
    assert len(registry) == 1


def test_Agent初始化时注入元数据并注册加载工具(tmp_path: Path, monkeypatch) -> None:
    _write_skill(tmp_path, "demo-skill", description="处理 PDF 文档", body="# 正文\n\n详细步骤")
    monkeypatch.chdir(tmp_path)

    agent = Agent(
        client=FakeClient(),
        tools=ToolRegistry(),
        config=AgentConfig(system_prompt="你是助手"),
    )

    system_message = agent.messages[0]
    assert system_message.role == "system"
    assert "You have access to the following skills:" in system_message.content
    assert "- `demo-skill`: 处理 PDF 文档" in system_message.content
    assert "Use the loadSkill tool" in system_message.content
    assert "详细步骤" not in system_message.content
    assert "loadSkill" in agent.tools

    result = agent.tools.execute("loadSkill", {"name": "demo-skill"})
    assert result.ok
    assert "详细步骤" in result.content


def test_加载不存在的Skill返回失败(tmp_path: Path) -> None:
    _write_skill(tmp_path, "demo-skill")
    registry = SkillRegistry.discover(tmp_path)
    agent = Agent(client=FakeClient(), tools=ToolRegistry(), skills=registry)

    result = agent.tools.execute("loadSkill", {"name": "missing-skill"})

    assert not result.ok
    assert "未知 Skill" in (result.error or "")


def test_没有Skill时不修改提示词也不注册工具(tmp_path: Path) -> None:
    registry = SkillRegistry.discover(tmp_path)
    agent = Agent(
        client=FakeClient(),
        tools=ToolRegistry(),
        config=AgentConfig(system_prompt="你是助手"),
        skills=registry,
    )

    assert agent.messages[0].content == "你是助手"
    assert "loadSkill" not in agent.tools


# ----------------------------------------------------------------------
# loadSkill 的 filename 分支（需求 3 / 4）
# ----------------------------------------------------------------------


def _make_skill_with_files(root: Path) -> Path:
    """构造一个带附加文件的 Skill，返回其目录。"""
    skill_dir = root / ".agents" / "skills" / "demo-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: 演示\n---\n\n# 正文\n\n详细步骤",
        encoding="utf-8",
    )
    (skill_dir / "notes.md").write_text("顶层笔记内容", encoding="utf-8")
    nested = skill_dir / "assets" / "docs"
    nested.mkdir(parents=True)
    (nested / "ref.md").write_text("嵌套引用内容", encoding="utf-8")
    (skill_dir / "assets" / "dup.md").write_text("dup-a", encoding="utf-8")
    (skill_dir / "assets" / "sub" / "dup.md").parent.mkdir(parents=True)
    (skill_dir / "assets" / "sub" / "dup.md").write_text("dup-b", encoding="utf-8")
    # Skill 目录外，专门用于验证沙箱限制
    (root / "outside.txt").write_text("外部文件内容", encoding="utf-8")
    return skill_dir


def test_filename_相对路径读取附加文件(tmp_path: Path) -> None:
    _make_skill_with_files(tmp_path)
    registry = SkillRegistry.discover(tmp_path)

    result = registry.load_file("demo-skill", "assets/docs/ref.md")

    assert result.path is not None
    assert result.content == "嵌套引用内容"


def test_filename_裸文件名唯一匹配时递归搜索(tmp_path: Path) -> None:
    _make_skill_with_files(tmp_path)
    registry = SkillRegistry.discover(tmp_path)

    result = registry.load_file("demo-skill", "notes.md")

    assert result.path is not None
    assert result.content == "顶层笔记内容"


def test_filename_多个同名文件返回候选而非读取(tmp_path: Path) -> None:
    _make_skill_with_files(tmp_path)
    registry = SkillRegistry.discover(tmp_path)

    result = registry.load_file("demo-skill", "dup.md")

    assert result.path is None
    assert not result.content
    assert len(result.candidates) == 2
    rels = sorted(c.relative_to(tmp_path / ".agents" / "skills" / "demo-skill").as_posix() for c in result.candidates)
    assert rels == ["assets/dup.md", "assets/sub/dup.md"]


def test_filename_不存在返回空结果(tmp_path: Path) -> None:
    _make_skill_with_files(tmp_path)
    registry = SkillRegistry.discover(tmp_path)

    result = registry.load_file("demo-skill", "missing.md")

    assert result.path is None
    assert result.content == ""
    assert result.candidates == ()


def test_filename_越界路径被拒绝(tmp_path: Path) -> None:
    _make_skill_with_files(tmp_path)
    registry = SkillRegistry.discover(tmp_path)

    for escape in ("../outside.txt", "../../outside.txt", "assets/../../outside.txt"):
        result = registry.load_file("demo-skill", escape)
        assert result.path is None, f"路径越界未被拦截：{escape}"
        assert result.candidates == ()


def test_filename_项目相对路径指向Skill目录外被拒绝(tmp_path: Path) -> None:
    _make_skill_with_files(tmp_path)
    registry = SkillRegistry.discover(tmp_path)

    result = registry.load_file("demo-skill", "outside.txt")

    assert result.path is None
    assert result.candidates == ()


def test_filename_绝对路径在Skill目录外被拒绝(tmp_path: Path) -> None:
    _make_skill_with_files(tmp_path)
    registry = SkillRegistry.discover(tmp_path)

    result = registry.load_file("demo-skill", str(tmp_path / "outside.txt"))

    assert result.path is None
    assert result.candidates == ()


def test_filename_绝对路径在Skill目录内可读(tmp_path: Path) -> None:
    skill_dir = _make_skill_with_files(tmp_path)
    registry = SkillRegistry.discover(tmp_path)

    result = registry.load_file("demo-skill", str(skill_dir / "assets" / "docs" / "ref.md"))

    assert result.path is not None
    assert result.content == "嵌套引用内容"


def test_filename_加载附加文件时不重复读取SKILL_md正文(tmp_path: Path) -> None:
    _make_skill_with_files(tmp_path)
    registry = SkillRegistry.discover(tmp_path)

    result = registry.load_file("demo-skill", "notes.md")

    assert result.content == "顶层笔记内容"
    assert "详细步骤" not in result.content  # 未附带 SKILL.md 正文


def test_loadSkill带filename的工具返回内容(tmp_path: Path) -> None:
    _make_skill_with_files(tmp_path)
    registry = SkillRegistry.discover(tmp_path)
    agent = Agent(client=FakeClient(), tools=ToolRegistry(), skills=registry)

    result = agent.tools.execute("loadSkill", {"name": "demo-skill", "filename": "notes.md"})

    assert result.ok
    assert "顶层笔记内容" in result.content
    assert "详细步骤" not in result.content  # 正文仍未进入上下文


def test_loadSkill多候选时返回候选列表(tmp_path: Path) -> None:
    _make_skill_with_files(tmp_path)
    registry = SkillRegistry.discover(tmp_path)
    agent = Agent(client=FakeClient(), tools=ToolRegistry(), skills=registry)

    result = agent.tools.execute("loadSkill", {"name": "demo-skill", "filename": "dup.md"})

    assert result.ok
    assert "assets/dup.md" in result.content
    assert "assets/sub/dup.md" in result.content


# ----------------------------------------------------------------------
# createSkill
# ----------------------------------------------------------------------


def test_createSkill_写入符合规范的SKILL_md(tmp_path: Path) -> None:
    registry = SkillRegistry.discover(tmp_path)
    agent = Agent(client=FakeClient(), tools=ToolRegistry(), skills=registry)

    result = agent.tools.execute(
        "createSkill",
        {
            "name": "my-skill",
            "skillContext": (
                "---\nname: my-skill\ndescription: 处理示例任务\n---\n\n"
                "# 使用流程\n\n1. 第一步\n"
            ),
        },
    )

    assert result.ok
    path = tmp_path / ".agents" / "skills" / "my-skill" / "SKILL.md"
    assert path.is_file()
    skill = registry.get("my-skill")
    assert skill.name == "my-skill"
    assert skill.description == "处理示例任务"
    assert registry.load_instructions("my-skill") == "# 使用流程\n\n1. 第一步"
    assert "loadSkill" in agent.tools


def test_createSkill_缺少Frontmatter时自动补全(tmp_path: Path) -> None:
    registry = SkillRegistry.discover(tmp_path)
    agent = Agent(client=FakeClient(), tools=ToolRegistry(), skills=registry)

    result = agent.tools.execute(
        "createSkill",
        {"name": "body-only", "skillContext": "# 正文\n\n这是自动生成的描述"},
    )

    assert result.ok
    skill = registry.get("body-only")
    assert skill.name == "body-only"
    assert skill.description == "这是自动生成的描述"


def test_createSkill_已存在时不覆盖原内容(tmp_path: Path) -> None:
    _write_skill(tmp_path, "demo-skill")
    path = tmp_path / ".agents" / "skills" / "demo-skill" / "SKILL.md"
    original = path.read_text(encoding="utf-8")
    registry = SkillRegistry.discover(tmp_path)
    agent = Agent(client=FakeClient(), tools=ToolRegistry(), skills=registry)

    result = agent.tools.execute(
        "createSkill",
        {"name": "demo-skill", "skillContext": "---\nname: demo-skill\ndescription: 新\n---\n\n新内容"},
    )

    assert not result.ok
    assert "已存在" in (result.error or "")
    assert path.read_text(encoding="utf-8") == original


def test_createSkill_拒绝不合法的名称(tmp_path: Path) -> None:
    registry = SkillRegistry.discover(tmp_path)
    agent = Agent(client=FakeClient(), tools=ToolRegistry(), skills=registry)

    for name in ("Bad Name", "bad_name", "-bad", "bad-", "中文技能", "../escape"):
        result = agent.tools.execute(
            "createSkill",
            {"name": name, "skillContext": "# 正文\n\n描述"},
        )
        assert not result.ok, f"非法名称未被拒绝：{name}"
    assert not (tmp_path / ".agents" / "skills").exists()

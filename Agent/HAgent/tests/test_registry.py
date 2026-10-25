"""工具注册表与 schema 生成的测试。"""

from __future__ import annotations

import pytest

from core import ToolRegistry, ToolSpec
from core.errors import ToolNotFoundError
from core.tools.registry import build_parameters_schema


def test_装饰器自动生成schema() -> None:
    registry = ToolRegistry()

    @registry.tool()
    def greet(name: str, times: int = 1) -> str:
        """打招呼。

        Args:
            name: 名字
            times: 次数
        """
        return name * times

    spec = registry.get("greet")
    assert spec.description == "打招呼。"
    assert spec.parameters["properties"]["name"] == {"type": "string", "description": "名字"}
    assert spec.parameters["properties"]["times"] == {"type": "integer", "description": "次数"}
    assert spec.parameters["required"] == ["name"]


def test_schema可以转换为openai格式() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(name="noop", description="空操作", parameters={"type": "object", "properties": {}}, handler=lambda: "")
    )
    schemas = registry.schemas()
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "noop"


def test_执行成功与失败() -> None:
    registry = ToolRegistry()

    @registry.tool()
    def add(a: int, b: int) -> int:
        """相加。"""
        return a + b

    ok = registry.execute("add", {"a": 1, "b": 2})
    assert ok.ok and ok.content == "3"

    missing = registry.execute("add", {"a": 1})
    assert not missing.ok and "调用参数错误" in (missing.error or "")

    unknown = registry.execute("not_exists", {})
    assert not unknown.ok and "未知工具" in (unknown.error or "")


def test_未知工具抛出异常() -> None:
    registry = ToolRegistry()
    with pytest.raises(ToolNotFoundError):
        registry.get("nope")


def test_内置工具齐全() -> None:
    from core import FilesystemConfig, register_builtin_tools

    registry = register_builtin_tools(ToolRegistry(), FilesystemConfig())
    names = set(registry.names())
    assert {"getdate", "isLeapYear", "get_cwd", "list_dir", "file_info"} <= names
    assert {"read_file", "create_file", "write_file", "create_dir"} <= names
    assert {"delete_dir", "delete_file", "move_path"} <= names


def test_可选类型注解生成合理schema() -> None:
    def sample(a: int | None = None, b: list[str] | None = None, c: int | str = 1) -> None:
        """示例。"""

    schema = build_parameters_schema(sample)
    assert schema["properties"]["a"] == {"type": "integer"}
    assert schema["properties"]["b"]["type"] == "array"
    assert "anyOf" in schema["properties"]["c"]

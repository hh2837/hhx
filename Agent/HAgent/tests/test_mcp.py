"""MCP 配置加载、工具注册与调用结果处理的测试（完全离线）。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import MCPConfigError, ToolRegistry
from core.mcp import (
    MCPClientManager,
    MCPServerConfig,
    MCPToolInfo,
    build_tool_bindings,
    format_mcp_tool_result,
    load_mcp_config,
    register_mcp_tools,
)


def _write_mcp_config(root: Path, payload: dict) -> Path:
    path = root / ".mcp.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_读取mcp配置_支持sse与streamable_http(tmp_path: Path) -> None:
    _write_mcp_config(
        tmp_path,
        {
            "mcpServers": {
                "sse-server": {"type": "sse", "url": "https://example.com/sse"},
                "http-server": {"type": "streamableHttp", "url": "https://example.com/mcp"},
                "inferred": {"url": "https://example.com/mcp"},
                "with-headers": {
                    "type": "http",
                    "url": "https://example.com/mcp",
                    "headers": {"Authorization": "Bearer token"},
                    "timeout": 5,
                },
            }
        },
    )

    configs = load_mcp_config(tmp_path)

    assert configs["sse-server"].transport == "sse"
    assert configs["http-server"].transport == "streamable-http"
    assert configs["inferred"].transport == "streamable-http"
    assert configs["with-headers"].headers == {"Authorization": "Bearer token"}
    assert configs["with-headers"].timeout == 5


def test_配置文件不存在时返回空(tmp_path: Path) -> None:
    assert load_mcp_config(tmp_path) == {}


def test_非法json抛出配置错误(tmp_path: Path) -> None:
    (tmp_path / ".mcp.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(MCPConfigError):
        load_mcp_config(tmp_path)


def test_跳过缺少url的server但不影响其他server(tmp_path: Path) -> None:
    _write_mcp_config(
        tmp_path,
        {
            "mcpServers": {
                "bad": {"type": "sse"},
                "good": {"type": "sse", "url": "https://example.com/sse"},
            }
        },
    )

    configs = load_mcp_config(tmp_path)

    assert list(configs) == ["good"]


def _tool(name: str, description: str = "desc") -> MCPToolInfo:
    return MCPToolInfo(
        name=name,
        description=description,
        parameters={"type": "object", "properties": {"q": {"type": "string"}}},
    )


def test_无冲突时直接使用原名() -> None:
    registry = ToolRegistry()
    bindings = build_tool_bindings(registry, {"server-a": [_tool("search")]})

    assert [binding.exposed_name for binding in bindings] == ["search"]
    assert bindings[0].tool_name == "search"
    assert bindings[0].server == "server-a"


def test_不同server同名工具自动加前缀() -> None:
    registry = ToolRegistry()
    bindings = build_tool_bindings(
        registry,
        {
            "server-a": [_tool("search")],
            "server-b": [_tool("search")],
        },
    )
    names = {binding.exposed_name for binding in bindings}

    assert names == {"server-a_search", "server-b_search"}


def test_与本地工具冲突时自动加前缀() -> None:
    registry = ToolRegistry()

    @registry.tool(name="RunCli")
    def _runcli(command: str) -> str:
        return command

    bindings = build_tool_bindings(registry, {"server-a": [_tool("RunCli")]})

    assert bindings[0].exposed_name == "server-a_RunCli"


def test_工具名中的非法字符会被清理() -> None:
    registry = ToolRegistry()
    bindings = build_tool_bindings(registry, {"server-a": [_tool("bazi.calculate/one")]})

    assert bindings[0].exposed_name == "bazi_calculate_one"


def test_文本与结构化结果都会返回() -> None:
    result = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="文本结果")],
        structuredContent={"year": 2026},
        isError=False,
    )

    output = format_mcp_tool_result(result, "server", "tool")

    assert output.ok
    assert "文本结果" in output.content
    assert '"year": 2026' in output.content


def test_mcp工具错误转换为失败结果() -> None:
    result = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="参数不合法")],
        structuredContent=None,
        isError=True,
    )

    output = format_mcp_tool_result(result, "server", "tool")

    assert not output.ok
    assert "参数不合法" in (output.error or "")


class _FakeManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self._tools = {"server-a": [_tool("bazi")]}
        self.servers = {"server-a": MCPServerConfig(name="server-a", url="http://example.com")}

    @property
    def tools(self):
        return self._tools

    def call_tool(self, server: str, tool_name: str, arguments: dict):
        self.calls.append((server, tool_name, arguments))
        from core import ToolResult

        return ToolResult.success("ok")


def test_register_mcp_tools_注册并转发调用() -> None:
    registry = ToolRegistry()
    manager = _FakeManager()

    returned = register_mcp_tools(registry, manager=manager)

    assert returned is manager
    assert "bazi" in registry
    result = registry.execute("bazi", {"q": "hello"})
    assert result.ok
    assert result.content == "ok"
    assert manager.calls == [("server-a", "bazi", {"q": "hello"})]


def test_server连接失败不影响其他工具() -> None:
    manager = MCPClientManager(
        {
            "broken": MCPServerConfig(name="broken", url="http://127.0.0.1:1/mcp", timeout=1),
        }
    )

    async def fail(_stack, _config):
        raise RuntimeError("boom")

    manager._connect_server = fail  # type: ignore[method-assign]
    try:
        tools = manager.discover()
    finally:
        manager.close()

    assert tools == {}
    assert "boom" in manager.errors["broken"]

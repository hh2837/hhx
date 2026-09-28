"""HTTP 层端到端测试：SDK 2.x 无状态 Streamable HTTP 连接流程。

验证点（对应文档「测试」第 7 条）：
- 不发送旧协议 ``initialize``（自动模式走 ``server/discover``，钉定模式零协商流量）；
- 不要求、也不返回 ``Mcp-Session-Id``；
- 使用 2026-07-28 实际规定的发现/调用方式；
- ``/health`` 可用；
- 工具可通过 HTTP MCP 端点被发现和调用。

说明：本文件不使用 respx（respx 会拦截测试自身发往 MCP 服务的真实 HTTP
请求），后端一律由 ``FakeGoBackend``（独立 uvicorn 线程的真实 HTTP 服务器）
模拟，构成“真实 MCP 服务 ↔ 真实 HTTP 后端”的端到端链路。
"""

from __future__ import annotations

import socket

import httpx
import pytest

from pet_hospital_mcp.server import ServerBundle

from .conftest import FakeGoBackend, ok_body, start_uvicorn, stop_uvicorn

META_ENVELOPE = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "pytest", "version": "0.0.1"},
}

RAW_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "Mcp-Protocol-Version": "2026-07-28",
}


@pytest.fixture
def http_base(http_bundle: ServerBundle) -> str:
    """启动真实 MCP HTTP 服务，返回 base URL。"""
    port = _free_port_http()
    server, thread = start_uvicorn(http_bundle.app, port)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        stop_uvicorn(server, thread)


def _free_port_http() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ─────────────────────────── /health ───────────────────────────

async def test_health_over_http(http_base: str):
    async with httpx.AsyncClient() as ac:
        response = await ac.get(f"{http_base}/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# ─────────────────── 原始 2026-07-28 协议请求 ───────────────────

async def test_discover_without_session(http_base: str):
    """裸 server/discover：不携带任何会话标识，直接成功。"""
    async with httpx.AsyncClient() as ac:
        response = await ac.post(
            f"{http_base}/mcp",
            headers={**RAW_HEADERS, "Mcp-Method": "server/discover"},
            json={"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": META_ENVELOPE}},
        )
    assert response.status_code == 200
    assert "mcp-session-id" not in {k.lower() for k in response.headers}  # 不返回会话头
    payload = response.json()
    assert payload["result"]["supportedVersions"] == ["2026-07-28"]
    assert payload["result"]["capabilities"]["tools"] is not None


async def test_call_without_session(http_base: str, fake_go_backend: FakeGoBackend):
    """裸 tools/call：无会话、无 initialize，仍可完成调用。"""
    fake_go_backend.set_json(ok_body())

    async with httpx.AsyncClient() as ac:
        response = await ac.post(
            f"{http_base}/mcp",
            headers={**RAW_HEADERS, "Mcp-Method": "tools/call", "Mcp-Name": "list_pets"},
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "list_pets", "arguments": {"params": {"pageSize": 5}}, "_meta": META_ENVELOPE},
            },
        )
    assert response.status_code == 200
    assert "mcp-session-id" not in {k.lower() for k in response.headers}
    payload = response.json()
    assert payload["result"]["isError"] is False
    assert payload["result"]["content"][0]["type"] == "text"
    # 后端确实收到了按协议转发的参数
    assert fake_go_backend.calls[0]["params"]["pageSize"] == "5"


# ─────────────────── SDK Client 自动模式（走 discover） ───────────────────

async def test_sdk_client_auto_mode_uses_discover(http_base: str):
    """自动模式：单次 server/discover 探测，不发送旧 initialize。"""
    from mcp import Client

    async with Client(f"{http_base}/mcp") as client:
        assert client.protocol_version == "2026-07-28"
        assert client.session.discover_result is not None  # 走的是 discover 而非 initialize
        tools = await client.list_tools()
        assert [t.name for t in tools.tools] == ["list_pets"]


async def test_sdk_client_call_tool_over_http(http_base: str, fake_go_backend: FakeGoBackend):
    from mcp import Client

    fake_go_backend.set_json(ok_body())

    async with Client(f"{http_base}/mcp") as client:
        result = await client.call_tool("list_pets", {"params": {"species": "猫", "pageSize": 10}})
        assert result.is_error is False
        assert result.structured_content["total"] == 1
        assert result.structured_content["items"][0]["species"] == "猫"
        sent = dict(fake_go_backend.calls[0]["params"])
        assert sent["species"] == "猫"
        assert sent["pageSize"] == "10"


async def test_sdk_client_error_result_over_http(http_base: str, fake_go_backend: FakeGoBackend):
    from mcp import Client

    fake_go_backend.set_json({"error": {"message": "unavailable"}}, status=503)

    async with Client(f"{http_base}/mcp") as client:
        result = await client.call_tool("list_pets", {"params": {}})
        assert result.is_error is True
        text = result.content[0].text
        assert '"code": "BACKEND_API_ERROR"' in text


# ─────────────────── SDK Client 钉定模式（零协商流量） ───────────────────

async def test_pinned_mode_stateless_connection(http_base: str, fake_go_backend: FakeGoBackend):
    """钉定 2026-07-28：不发 probe 也不发握手，直接可用 → 服务确实无状态。"""
    from mcp import Client

    fake_go_backend.set_json(ok_body())

    async with Client(f"{http_base}/mcp", mode="2026-07-28") as client:
        assert client.protocol_version == "2026-07-28"
        tools = await client.list_tools()
        assert tools.tools[0].name == "list_pets"
        result = await client.call_tool("list_pets", {"params": {}})
        assert result.is_error is False
        assert result.structured_content["total"] == 1

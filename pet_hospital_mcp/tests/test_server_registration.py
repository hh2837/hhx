"""MCP 工具注册与 /health 路由测试。"""

from __future__ import annotations

import httpx


async def test_only_list_pets_registered(client):
    async with client:
        tools = await client.list_tools()
    names = [t.name for t in tools.tools]
    assert names == ["list_pets"], "阶段一只应注册 list_pets 一个工具"


async def test_tool_name_is_snake_case(client):
    async with client:
        tools = await client.list_tools()
    assert tools.tools[0].name == "list_pets"


async def test_tool_has_descriptive_contract(client):
    async with client:
        tools = await client.list_tools()
    tool = tools.tools[0]
    assert tool.description
    for keyword in (
        "GET /api/v1/pets",
        "pageSize",
        "sortBy",
        "species",
        "status",
        "totalCost",
        "VALIDATION_ERROR",
    ):
        assert keyword in tool.description, f"description 缺少关键信息: {keyword}"


async def test_input_schema_shape(client):
    async with client:
        tools = await client.list_tools()
    tool = tools.tools[0]
    schema = tool.input_schema
    assert schema["type"] == "object"
    # 参数为单对象入参（params）；字段级约束由工具 description 与
    # ListPetsParams 模型共同承载（Any 入参保证统一校验路径）
    assert "params" in schema["properties"]
    assert schema["required"] == ["params"]


async def test_health_route_registered(bundle):
    paths = {getattr(r, "path", None) for r in bundle.app.routes}
    assert "/mcp" in paths
    assert "/health" in paths


async def test_health_endpoint_response(bundle):
    transport = httpx.ASGITransport(app=bundle.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "pet-hospital-mcp"
    assert payload["protocol"] == "2026-07-28"

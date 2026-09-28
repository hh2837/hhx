"""list_pets 工具测试：参数转发、输入校验、后端异常映射、输出兼容性。"""

from __future__ import annotations

import math
from typing import Any

import httpx
import pytest

from .conftest import make_pet, ok_body, tool_error_text

ALL_FILTER_PARAMS: dict[str, Any] = {
    "q": "猫瘟",
    "name": "Mimi",
    "ownerName": "Alice",
    "ownerPhone": "13800000000",
    "species": "猫",
    "doctor": "王医生",
    "disease": "猫瘟",
    "status": "待就诊",
    "min": 10.5,
    "max": 100.0,
    "sortBy": "totalCost",
    "order": "desc",
    "page": 2,
    "pageSize": 30,
}


async def assert_validation_error(client, params: Any, *, expect_loc: str | None = None):
    result = await client.call_tool("list_pets", {"params": params})
    assert result.is_error is True, f"应当拒绝输入: {params!r}"
    body = tool_error_text(result)
    assert body["error"]["code"] == "VALIDATION_ERROR", body
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    assert isinstance(body["error"]["details"], dict)
    if expect_loc is not None:
        locs = [tuple(e["loc"]) for e in body["error"]["details"].get("errors", [])]
        assert any(expect_loc in loc for loc in locs), locs


# ─────────────────────────── 正常调用 ───────────────────────────

async def test_success_forwards_all_params_and_returns_data(client, backend):
    route = backend.get("/api/v1/pets")
    route.return_value = httpx.Response(200, json=ok_body())

    async with client:
        result = await client.call_tool("list_pets", {"params": ALL_FILTER_PARAMS})
    assert result.is_error is False

    request = route.calls.last.request
    assert request.url.path == "/api/v1/pets"
    assert request.method == "GET"
    sent = dict(request.url.params)
    for key, value in ALL_FILTER_PARAMS.items():
        assert sent[key] == str(value), f"参数 {key} 未按原样转发"

    assert result.structured_content["total"] == 1
    assert result.structured_content["items"][0]["name"] == "Mimi"


async def test_success_with_minimal_params_uses_defaults(client, backend):
    route = backend.get("/api/v1/pets")
    route.return_value = httpx.Response(200, json=ok_body())

    async with client:
        result = await client.call_tool("list_pets", {"params": {}})
    assert result.is_error is False
    sent = dict(route.calls.last.request.url.params)
    assert sent == {"page": "1", "pageSize": "20"}  # 默认分页


async def test_records_and_charges_null_or_array_both_accepted(client, backend):
    backend.get("/api/v1/pets").return_value = httpx.Response(
        200,
        json=ok_body(
            items=[
                make_pet(id="PET-000001", records=None, charges=None),
                make_pet(
                    id="PET-000002",
                    name="Doudou",
                    species="犬",
                    records=[
                        {"id": "MR-11", "visitDate": "2026-09-01", "diagnosis": "体检", "doctor": "李医生"}
                    ],
                    charges=[{"id": "CHG-21", "item": "挂号", "category": "检查", "amount": 20.0}],
                ),
            ],
            total=2,
            totalPages=1,
            totalCost=32.5,
        ),
    )

    async with client:
        result = await client.call_tool("list_pets", {"params": {"pageSize": 50}})
    assert result.is_error is False
    items = result.structured_content["items"]
    assert items[0]["records"] is None
    assert items[0]["charges"] is None
    assert items[1]["records"][0]["diagnosis"] == "体检"
    assert items[1]["charges"][0]["amount"] == 20.0
    assert items[1]["id"] == "PET-000002"  # id 为字符串编号


# ─────────────────────── 输入校验失败 ───────────────────────

async def test_reject_bad_species(client, backend):
    async with client:
        await assert_validation_error(client, {"species": "dragon"}, expect_loc="species")


async def test_reject_bad_status(client, backend):
    async with client:
        await assert_validation_error(client, {"status": "evaporated"}, expect_loc="status")


async def test_reject_bad_sortby(client, backend):
    async with client:
        await assert_validation_error(client, {"sortBy": "weight"}, expect_loc="sortBy")


async def test_reject_bad_order(client, backend):
    async with client:
        await assert_validation_error(client, {"order": "up"}, expect_loc="order")


async def test_reject_page_below_one(client, backend):
    async with client:
        await assert_validation_error(client, {"page": 0}, expect_loc="page")
        await assert_validation_error(client, {"page": -3}, expect_loc="page")


async def test_reject_pagesize_out_of_range(client, backend):
    async with client:
        await assert_validation_error(client, {"pageSize": 0}, expect_loc="pageSize")
        await assert_validation_error(client, {"pageSize": 501}, expect_loc="pageSize")


async def test_reject_negative_min_and_max(client, backend):
    async with client:
        await assert_validation_error(client, {"min": -1}, expect_loc="min")
        await assert_validation_error(client, {"max": -0.01}, expect_loc="max")


async def test_reject_min_greater_than_max(client, backend):
    async with client:
        await assert_validation_error(client, {"min": 200.0, "max": 100.0})


async def test_reject_unknown_field(client, backend):
    async with client:
        await assert_validation_error(client, {"chipNo": "secret"}, expect_loc="chipNo")


async def test_reject_nan_input(client, backend):
    # 说明：标准 MCP 客户端会在序列化时把 NaN 归一化为 null（协议层行为），
    # 因此 NaN 无法以数字形态到达工具；模型层严格拒绝由
    # tests/test_input_model.py 覆盖。这里验证归一化后按“未提供”处理、
    # 且不会把 NaN 传给后端。
    route = backend.get("/api/v1/pets")
    route.return_value = httpx.Response(200, json=ok_body())

    async with client:
        result = await client.call_tool("list_pets", {"params": {"min": float("nan")}})
    assert result.is_error is False
    sent = dict(route.calls.last.request.url.params)
    assert "min" not in sent  # NaN 未作为数字转发给后端


async def test_reject_wrong_types(client, backend):
    async with client:
        await assert_validation_error(client, {"page": "abc"}, expect_loc="page")
        await assert_validation_error(client, {"page": "5"}, expect_loc="page")  # 字符串数字同样拒绝
        await assert_validation_error(client, {"pageSize": 10.5}, expect_loc="pageSize")
        await assert_validation_error(client, {"species": 123}, expect_loc="species")
        await assert_validation_error(client, {"q": 42}, expect_loc="q")


async def test_reject_non_object_params(client, backend):
    async with client:
        result = await client.call_tool("list_pets", {"params": "not-an-object"})
    assert result.is_error is True
    assert tool_error_text(result)["error"]["code"] == "VALIDATION_ERROR"


# ─────────────────────── 后端异常映射 ───────────────────────

async def test_backend_5xx_maps_to_api_error(client, backend):
    backend.get("/api/v1/pets").return_value = httpx.Response(
        500,
        json={"error": {"message": "internal boom"}},
    )
    async with client:
        result = await client.call_tool("list_pets", {"params": {}})
    assert result.is_error is True
    body = tool_error_text(result)
    assert body["error"]["code"] == "BACKEND_API_ERROR"
    assert body["error"]["details"]["status"] == 500


async def test_backend_4xx_maps_to_api_error(client, backend):
    backend.get("/api/v1/pets").return_value = httpx.Response(404, text="nope")
    async with client:
        result = await client.call_tool("list_pets", {"params": {}})
    assert result.is_error is True
    assert tool_error_text(result)["error"]["code"] == "BACKEND_API_ERROR"


async def test_backend_timeout_maps_to_timeout(client, backend):
    backend.get("/api/v1/pets").side_effect = httpx.ReadTimeout("slow backend")
    async with client:
        result = await client.call_tool("list_pets", {"params": {}})
    assert result.is_error is True
    body = tool_error_text(result)
    assert body["error"]["code"] == "BACKEND_TIMEOUT"
    assert "attempt" in body["error"]["details"]


async def test_backend_connect_error_maps_to_unavailable(client, backend):
    backend.get("/api/v1/pets").side_effect = httpx.ConnectError("connection refused")
    async with client:
        result = await client.call_tool("list_pets", {"params": {}})
    assert result.is_error is True
    assert tool_error_text(result)["error"]["code"] == "BACKEND_UNAVAILABLE"


async def test_backend_invalid_json_maps_to_invalid_response(client, backend):
    backend.get("/api/v1/pets").return_value = httpx.Response(200, text="<html>")
    async with client:
        result = await client.call_tool("list_pets", {"params": {}})
    assert result.is_error is True
    assert tool_error_text(result)["error"]["code"] == "BACKEND_INVALID_RESPONSE"


async def test_backend_missing_data_maps_to_invalid_response(client, backend):
    backend.get("/api/v1/pets").return_value = httpx.Response(200, json={"code": 0})
    async with client:
        result = await client.call_tool("list_pets", {"params": {}})
    assert result.is_error is True
    assert tool_error_text(result)["error"]["code"] == "BACKEND_INVALID_RESPONSE"


async def test_backend_malformed_data_maps_to_invalid_response(client, backend):
    backend.get("/api/v1/pets").return_value = httpx.Response(
        200,
        json={"code": 0, "data": {"items": "not-a-list"}},
    )
    async with client:
        result = await client.call_tool("list_pets", {"params": {}})
    assert result.is_error is True
    assert tool_error_text(result)["error"]["code"] == "BACKEND_INVALID_RESPONSE"


async def test_backend_missing_required_data_fields_maps_to_invalid_response(client, backend):
    backend.get("/api/v1/pets").return_value = httpx.Response(
        200,
        json={"code": 0, "data": {"items": [], "total": 0}},  # 缺 page/pageSize/totalPages/totalCost
    )
    async with client:
        result = await client.call_tool("list_pets", {"params": {}})
    assert result.is_error is True
    assert tool_error_text(result)["error"]["code"] == "BACKEND_INVALID_RESPONSE"


async def test_backend_records_as_scalar_maps_to_invalid_response(client, backend):
    backend.get("/api/v1/pets").return_value = httpx.Response(
        200,
        json=ok_body(items=[make_pet(records="oops")]),
    )
    async with client:
        result = await client.call_tool("list_pets", {"params": {}})
    assert result.is_error is True
    assert tool_error_text(result)["error"]["code"] == "BACKEND_INVALID_RESPONSE"


async def test_unknown_backend_fields_are_preserved(client, backend):
    """后端新增字段不应导致校验失败，且应透传到结构化输出。"""
    backend.get("/api/v1/pets").return_value = httpx.Response(
        200,
        json=ok_body(items=[make_pet(nickname="Kitty", futureField={"x": 1})]),
    )
    async with client:
        result = await client.call_tool("list_pets", {"params": {}})
    assert result.is_error is False
    assert result.structured_content["items"][0]["nickname"] == "Kitty"
    assert result.structured_content["items"][0]["futureField"] == {"x": 1}

"""RestClient 单元测试：路径/参数转发、超时、重试、错误映射。"""

from __future__ import annotations

import httpx
import pytest

from pet_hospital_mcp.rest_client import (
    BackendApiError,
    BackendInvalidResponseError,
    BackendTimeoutError,
    BackendUnavailableError,
    RestClient,
)


def make_client(handler, **kwargs) -> RestClient:
    transport = httpx.MockTransport(handler)
    return RestClient(
        "http://backend.test",
        timeout_seconds=1.0,
        max_retries=kwargs.pop("max_retries", 0),
        retry_backoff_seconds=0.01,
        transport=transport,
        **kwargs,
    )


async def test_success_parses_json_and_forwards_params():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={"code": 0, "data": {"items": [], "total": 0}},
        )

    client = make_client(handler)
    body = await client.get("/api/v1/pets", params={"page": 2, "species": "cat"})
    assert body["data"]["total"] == 0
    assert seen["method"] == "GET"
    assert seen["path"] == "/api/v1/pets"
    assert seen["params"] == {"page": "2", "species": "cat"}


async def test_4xx_raises_backend_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "not found"}})

    client = make_client(handler)
    with pytest.raises(BackendApiError) as exc:
        await client.get("/api/v1/pets")
    assert exc.value.code.value == "BACKEND_API_ERROR"
    assert exc.value.details["status"] == 404
    assert exc.value.details["backend_message"] == "not found"


async def test_5xx_raises_backend_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = make_client(handler)
    with pytest.raises(BackendApiError) as exc:
        await client.get("/api/v1/pets")
    assert exc.value.code.value == "BACKEND_API_ERROR"
    assert exc.value.details["status"] == 500


async def test_timeout_raises_backend_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    client = make_client(handler)
    with pytest.raises(BackendTimeoutError) as exc:
        await client.get("/api/v1/pets")
    assert exc.value.code.value == "BACKEND_TIMEOUT"


async def test_connect_error_raises_backend_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = make_client(handler)
    with pytest.raises(BackendUnavailableError) as exc:
        await client.get("/api/v1/pets")
    assert exc.value.code.value == "BACKEND_UNAVAILABLE"


async def test_invalid_json_raises_backend_invalid_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    client = make_client(handler)
    with pytest.raises(BackendInvalidResponseError) as exc:
        await client.get("/api/v1/pets")
    assert exc.value.code.value == "BACKEND_INVALID_RESPONSE"


async def test_non_object_json_raises_backend_invalid_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["not", "an", "object"])

    client = make_client(handler)
    with pytest.raises(BackendInvalidResponseError) as exc:
        await client.get("/api/v1/pets")
    assert exc.value.code.value == "BACKEND_INVALID_RESPONSE"


async def test_retry_recovers_after_transient_failure():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("first attempt refused")
        return httpx.Response(200, json={"code": 0, "data": {}})

    client = make_client(handler, max_retries=2)
    body = await client.get("/api/v1/pets")
    assert body["code"] == 0
    assert calls["n"] == 2


async def test_retry_exhausted_raises_last_error():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("always refused")

    client = make_client(handler, max_retries=2)
    with pytest.raises(BackendUnavailableError):
        await client.get("/api/v1/pets")
    assert calls["n"] == 3  # 1 次初始 + 2 次重试


async def test_4xx_not_retried():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, text="bad")

    client = make_client(handler, max_retries=3)
    with pytest.raises(BackendApiError):
        await client.get("/api/v1/pets")
    assert calls["n"] == 1  # 确定性失败不重试

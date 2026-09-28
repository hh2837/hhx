"""测试共享夹具。

约定：
- 测试绝不访问真实 Go 服务：进程内工具测试用 respx 模拟后端；
  HTTP 端到端测试用 ``FakeGoBackend``（真实 HTTP 服务器）模拟后端；
- 进程内 MCP 客户端使用同步 fixture 返回“未进入”的 Client，
  由测试在自身任务内 ``async with client:`` 进入，避免 anyio 取消作用域
  跨任务退出问题（pytest-asyncio 异步生成器 fixture 的限制）。
"""

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Any, AsyncIterator

import httpx
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from pet_hospital_mcp.config import Settings
from pet_hospital_mcp.server import ServerBundle, create_server

TEST_BASE_URL = "http://pet-hospital-backend.test"


def make_pet(**overrides: Any) -> dict[str, Any]:
    """模拟 Go API 的宠物对象（按真实后端结构，id 为字符串、中文枚举）。"""
    pet: dict[str, Any] = {
        "id": "PET-000001",
        "name": "Mimi",
        "species": "猫",
        "breed": "波斯猫",
        "gender": "母",
        "ageMonths": 30,
        "color": "白色",
        "chipNo": "CHIP-001",
        "ownerName": "Alice",
        "ownerPhone": "13800000000",
        "ownerAddr": "成都",
        "doctor": "王医生",
        "disease": "猫瘟",
        "status": "待就诊",
        "allergy": "无",
        "records": None,
        "charges": None,
        "totalCost": 12.5,
        "visitCount": 0,
        "createdAt": "2026-09-01T10:00:00Z",
        "updatedAt": "2026-09-02T10:00:00Z",
    }
    pet.update(overrides)
    return pet


def ok_body(**data_overrides: Any) -> dict[str, Any]:
    """模拟 Go API 成功响应信封。"""
    data: dict[str, Any] = {
        "items": [make_pet()],
        "total": 1,
        "page": 1,
        "pageSize": 20,
        "totalPages": 1,
        "totalCost": 12.5,
    }
    data.update(data_overrides)
    return {"code": 0, "message": "ok", "data": data}


def tool_error_text(result) -> dict[str, Any]:
    """从工具失败结果中解析统一错误结构。"""
    text = result.content[0].text
    return json.loads(text[text.index("{"):])


# ─────────────────────────── 基础配置夹具 ───────────────────────────

@pytest.fixture
def settings() -> Settings:
    return Settings(
        mcp_host="127.0.0.1",
        mcp_port=0,
        pet_hospital_base_url=TEST_BASE_URL,
        backend_timeout_seconds=1.0,
        backend_max_retries=2,
        backend_retry_backoff_seconds=0.02,
        log_level="WARNING",
    )


@pytest.fixture
def bundle(settings: Settings) -> ServerBundle:
    return create_server(settings)


@pytest.fixture
def client(bundle: ServerBundle):
    """进程内直连客户端（未进入；测试内 ``async with client:`` 使用）。"""
    from mcp import Client

    return Client(bundle.mcp, raise_exceptions=True)


@pytest.fixture
def backend():
    """进程内工具测试的后端模拟（respx 全局拦截 httpx 流量）。"""
    import respx

    with respx.mock(base_url=TEST_BASE_URL, assert_all_called=False) as mock:
        yield mock


# ─────────────────────────── 真实模拟 Go 后端 ───────────────────────────

class FakeGoBackend:
    """运行在独立 uvicorn 线程中的 Go REST API 替身。"""

    def __init__(self, base_url: str, state: dict[str, Any]) -> None:
        self.base_url = base_url
        self._state = state
        #: 收到的请求快照：[{"path": str, "params": dict}]
        self.calls: list[dict[str, Any]] = []

    def set_json(self, payload: dict[str, Any], status: int = 200) -> None:
        self._state["handler"] = self._handler(status=status, json_body=payload)

    def set_text(self, text: str, status: int = 200) -> None:
        self._state["handler"] = self._handler(status=status, text=text)

    def set_side_effect(self, exc: Exception) -> None:
        def _raise(request) -> Response:
            self._record(request)
            raise exc

        self._state["handler"] = _raise

    def _record(self, request) -> None:
        self.calls.append(
            {
                "path": request.url.path,
                "params": {k: v for k, v in request.query_params.items()},
            }
        )

    def _handler(self, *, status: int, json_body: dict[str, Any] | None = None, text: str | None = None):
        def _handle(request) -> Response:
            self._record(request)
            if json_body is not None:
                return Response(
                    json.dumps(json_body),
                    status_code=status,
                    media_type="application/json",
                )
            return Response(text or "", status_code=status)

        return _handle


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_uvicorn(app, port: int) -> tuple[uvicorn.Server, threading.Thread]:
    """在后台线程启动 uvicorn，返回 (server, thread)。"""
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            return server, thread
        time.sleep(0.02)
    raise RuntimeError("uvicorn 未能启动")


def stop_uvicorn(server: uvicorn.Server, thread: threading.Thread) -> None:
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture
def fake_go_backend() -> AsyncIterator[FakeGoBackend]:
    """启动一个可编程的 Go REST API 替身（真实 HTTP 服务器）。"""
    state: dict[str, Any] = {"handler": None}
    app = Starlette()

    async def pets(request: Request) -> Response:
        handler = state["handler"]
        if handler is None:
            return JSONResponse(ok_body())
        return handler(request)  # handler 返回 Response 或抛异常

    app.add_route("/api/v1/pets", pets, methods=["GET"])

    port = _free_port()
    server, thread = start_uvicorn(app, port)
    try:
        yield FakeGoBackend(f"http://127.0.0.1:{port}", state)
    finally:
        stop_uvicorn(server, thread)


@pytest.fixture
def http_bundle(fake_go_backend: FakeGoBackend) -> AsyncIterator[ServerBundle]:
    """指向真实模拟后端的 MCP 服务实例（用于 HTTP 端到端测试）。"""
    settings = Settings(
        mcp_host="127.0.0.1",
        mcp_port=0,
        pet_hospital_base_url=fake_go_backend.base_url,
        backend_timeout_seconds=1.0,
        backend_max_retries=0,  # 端到端测试避免重试噪音
        backend_retry_backoff_seconds=0.02,
        log_level="WARNING",
    )
    yield create_server(settings)

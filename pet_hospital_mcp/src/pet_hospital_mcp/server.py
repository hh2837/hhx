"""MCP 服务装配。

- 创建 ``MCPServer``（SDK 2.x，协议 2026-07-28，无状态 Streamable HTTP）；
- 注册 ``/health`` 健康检查路由；
- 注册阶段一唯一工具 ``list_pets``；
- 返回可被任意 ASGI 服务器（uvicorn 等）承载的 Starlette 应用。

命令行直接运行请使用 ``python -m pet_hospital_mcp``；也可以使用
``uvicorn pet_hospital_mcp.server:app``。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mcp.server import MCPServer
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import Settings
from .logging_config import setup_logging
from .rest_client import RestClient
from .tools.list_pets import register as register_list_pets

#: 对外报告的协议版本（2026-07-28 规范）
PROTOCOL_VERSION = "2026-07-28"

SERVER_NAME = "pet-hospital-mcp"
SERVER_VERSION = "0.1.0"


@dataclass
class ServerBundle:
    """装配结果：同时暴露 MCPServer 对象与 ASGI app。

    测试中可用 ``bundle.mcp`` 做进程内直连（``Client(mcp)``），
    用 ``bundle.app`` 做真实 HTTP 链路验证。
    """

    mcp: MCPServer
    app: Starlette
    rest_client: RestClient


def create_server(settings: Settings | None = None) -> ServerBundle:
    """构建完整的 MCP 服务（幂等可重复调用，每次返回独立实例）。"""
    settings = settings or Settings()
    setup_logging(settings.log_level)

    mcp = MCPServer(
        SERVER_NAME,
        title="Pet Hospital MCP Server",
        description=(
            "Stateless Streamable HTTP MCP server that exposes the existing Go "
            "pet hospital REST API to AI agents (protocol 2026-07-28, SDK 2.x)."
        ),
        instructions=(
            "This server proxies the upstream Go pet hospital REST API over MCP. "
            "Stage 1 exposes a single tool: list_pets."
        ),
        version=SERVER_VERSION,
    )

    rest_client = RestClient(
        settings.pet_hospital_base_url,
        timeout_seconds=settings.backend_timeout_seconds,
        max_retries=settings.backend_max_retries,
        retry_backoff_seconds=settings.backend_retry_backoff_seconds,
    )

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> JSONResponse:
        """健康检查：无 MCP 语义，纯 HTTP。"""
        return JSONResponse(
            {
                "status": "ok",
                "service": SERVER_NAME,
                "version": SERVER_VERSION,
                "protocol": PROTOCOL_VERSION,
            }
        )

    register_list_pets(mcp, rest_client)

    app = mcp.streamable_http_app()
    return ServerBundle(mcp=mcp, app=app, rest_client=rest_client)


#: uvicorn pet_hospital_mcp.server:app 入口
app: Starlette = create_server().app


def create_app(settings: Settings | None = None) -> Starlette:
    """兼容入口：只返回 ASGI 应用。"""
    return create_server(settings).app


__all__: list[str] = ["ServerBundle", "app", "create_app", "create_server"]

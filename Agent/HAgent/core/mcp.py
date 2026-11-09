"""MCP（Model Context Protocol）客户端支持。

HAgent 在启动时读取当前项目目录下的 ``.mcp.json``，通过 MCP Python SDK 连接外部
MCP Server（支持 Streamable HTTP 与 SSE），调用 ``list_tools()`` 发现工具，再把这些
工具动态注册到本地 :class:`~core.tools.registry.ToolRegistry` 中。这样 LLM 就能像调用
本地 Function Calling 工具一样调用 MCP 工具。

MCP Python SDK 是全异步接口，而 HAgent 的 Agent 主循环是同步的。本模块用一个后台
事件循环线程持有 MCP 会话：连接、发现工具和工具调用都投递到同一个事件循环任务中
执行，从而保证 ``ClientSession`` 的异步上下文始终在同一个任务内进入和退出。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import logging
import re
import threading
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import MCPConfigError, MCPConnectionError
from .tools.base import ToolResult, ToolSpec
from .tools.registry import ToolRegistry

try:  # pragma: no cover - 是否安装 mcp 取决于运行环境
    from mcp import ClientSession
    from mcp.client.sse import sse_client
    from mcp.client.streamable_http import streamable_http_client

    MCP_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - 降级路径
    ClientSession = None  # type: ignore[assignment,misc]
    sse_client = None  # type: ignore[assignment]
    streamable_http_client = None  # type: ignore[assignment]
    MCP_SDK_AVAILABLE = False

logger = logging.getLogger(__name__)

MCP_CONFIG_FILENAME = ".mcp.json"
_DEFAULT_TIMEOUT = 30.0
_MAX_TOOL_NAME_LENGTH = 64
_TOOL_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_-]+")
_RESERVED_TOOL_NAMES = {"loadSkill", "createSkill"}
_STREAMABLE_HTTP_TYPES = {"streamable-http", "streamablehttp", "streamable_http", "http"}
_SSE_TYPES = {"sse", "server-sent-events", "serversentevents"}


# ----------------------------------------------------------------------
# 配置
# ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MCPServerConfig:
    """一个 MCP Server 的连接配置。"""

    name: str
    url: str
    transport: str = "streamable-http"
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = _DEFAULT_TIMEOUT


@dataclass(frozen=True, slots=True)
class MCPToolInfo:
    """从 MCP Server 发现的工具元数据。"""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class MCPToolBinding:
    """LLM 可见工具名与 MCP Server / 原始工具名之间的映射。"""

    exposed_name: str
    server: str
    tool_name: str
    description: str
    parameters: dict[str, Any]


def _normalize_transport(raw_type: Any) -> str:
    value = str(raw_type or "").strip().lower()
    if not value:
        return "streamable-http"
    if value in _SSE_TYPES:
        return "sse"
    if value in _STREAMABLE_HTTP_TYPES:
        return "streamable-http"
    raise MCPConfigError(f"不支持的 MCP 传输类型：{raw_type!r}（仅支持 sse / streamable-http）")


def _string_map(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items() if value is not None}


def _positive_float(raw: Any, default: float, label: str) -> float:
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise MCPConfigError(f"{label} 必须是数字：{raw!r}") from exc
    if value <= 0:
        raise MCPConfigError(f"{label} 必须大于 0：{raw!r}")
    return value


def load_mcp_config(
    root: Path | None = None,
    config_path: Path | None = None,
    config_file: str = MCP_CONFIG_FILENAME,
    default_timeout: float = _DEFAULT_TIMEOUT,
) -> dict[str, MCPServerConfig]:
    """读取 MCP 配置文件并返回 ``服务器名 -> 配置`` 映射。

    配置文件不存在时返回空字典；文件格式错误时抛出 :class:`MCPConfigError`。
    单个 Server 配置不合法时只跳过该项，不影响其他 Server。
    """
    path = (
        Path(config_path)
        if config_path is not None
        else Path(root or Path.cwd()) / config_file
    )
    if not path.is_file():
        logger.debug("未找到 MCP 配置文件：%s", path)
        return {}

    try:
        raw_text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise MCPConfigError(f"无法读取 MCP 配置文件：{path}（{exc}）") from exc

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise MCPConfigError(f"MCP 配置文件不是合法 JSON：{path}（{exc}）") from exc

    if not isinstance(data, dict):
        raise MCPConfigError(f"MCP 配置文件顶层必须是对象：{path}")
    servers = data.get("mcpServers")
    if servers is None:
        return {}
    if not isinstance(servers, dict):
        raise MCPConfigError(f"MCP 配置中的 mcpServers 必须是对象：{path}")

    configs: dict[str, MCPServerConfig] = {}
    for raw_name, raw_config in servers.items():
        name = str(raw_name).strip()
        if not name:
            logger.warning("跳过未命名的 MCP Server 配置：%s", path)
            continue
        if not isinstance(raw_config, dict):
            logger.warning("跳过无效的 MCP Server 配置 `%s`：必须是对象", name)
            continue
        url = str(raw_config.get("url") or "").strip()
        if not url:
            logger.warning("跳过 MCP Server `%s`：缺少 url", name)
            continue
        try:
            transport = _normalize_transport(raw_config.get("type"))
            timeout = _positive_float(
                raw_config.get("timeout"),
                default_timeout,
                f"MCP Server `{name}` 的 timeout",
            )
        except MCPConfigError as exc:
            logger.warning("跳过 MCP Server `%s`：%s", name, exc)
            continue
        configs[name] = MCPServerConfig(
            name=name,
            url=url,
            transport=transport,
            headers=_string_map(raw_config.get("headers")),
            timeout=timeout,
        )

    logger.info("已加载 %d 个 MCP Server 配置：%s", len(configs), ", ".join(configs) or "无")
    return configs


# ----------------------------------------------------------------------
# 同步/异步桥接
# ----------------------------------------------------------------------


@dataclass(slots=True)
class _Command:
    future: concurrent.futures.Future[Any]
    operation: Callable[[AsyncExitStack], Awaitable[Any]]


class _MCPWorker:
    """在后台线程中运行一个长期存活的 asyncio 事件循环。"""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._queue: asyncio.Queue[_Command | None] | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="hagent-mcp", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5):
            raise MCPConnectionError("MCP 后台事件循环启动超时")

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        queue: asyncio.Queue[_Command | None] = asyncio.Queue()
        self._queue = queue
        self._loop.call_soon(self._ready.set)
        try:
            self._loop.run_until_complete(self._consume(queue))
        finally:
            self._loop.close()

    async def _consume(self, queue: asyncio.Queue[_Command | None]) -> None:
        async with AsyncExitStack() as stack:
            while True:
                command = await queue.get()
                if command is None:
                    break
                if command.future.done():
                    continue
                try:
                    value = await command.operation(stack)
                except BaseException as exc:  # noqa: BLE001 - 需要把取消等异常传回调用方
                    if not command.future.done():
                        command.future.set_exception(exc)
                else:
                    if not command.future.done():
                        command.future.set_result(value)

    def submit(self, operation: Callable[[AsyncExitStack], Awaitable[Any]], timeout: float) -> Any:
        queue = self._queue
        if queue is None or not self._loop.is_running():
            raise MCPConnectionError("MCP 后台事件循环不可用")
        future: concurrent.futures.Future[Any] = concurrent.futures.Future()
        self._loop.call_soon_threadsafe(queue.put_nowait, _Command(future, operation))
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise MCPConnectionError(f"MCP 操作超时（{timeout:.0f} 秒）") from exc

    def close(self) -> None:
        queue = self._queue
        if queue is not None and self._loop.is_running():
            try:
                self._loop.call_soon_threadsafe(queue.put_nowait, None)
            except RuntimeError:
                return
            self._thread.join(timeout=5)


# ----------------------------------------------------------------------
# 客户端
# ----------------------------------------------------------------------


def _format_exception(exc: BaseException) -> str:
    message = str(exc).strip()
    if message:
        return f"{type(exc).__name__}: {message}"
    return type(exc).__name__


def _value(obj: Any, *names: str, default: Any = None) -> Any:
    """同时兼容 SDK 模型对象与测试中常见的 dict。"""
    if isinstance(obj, Mapping):
        for name in names:
            if name in obj:
                return obj[name]
    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return default


def _content_to_text(item: Any) -> str:
    item_type = str(_value(item, "type", default="") or "")
    if item_type == "image" or item_type == "audio":
        mime = _value(item, "mimeType", "mime_type", default="unknown")
        data = _value(item, "data", default="") or ""
        return f"[{item_type}: {mime}, base64 数据长度 {len(str(data))}]"

    text = _value(item, "text")
    if isinstance(text, str):
        return text

    if item_type == "resource":
        resource = _value(item, "resource")
        resource_text = _value(resource, "text")
        if isinstance(resource_text, str):
            return resource_text
        uri = _value(resource, "uri", "url")
        return f"[资源: {uri}]" if uri else "[资源内容]"

    if hasattr(item, "model_dump"):
        try:
            return json.dumps(item.model_dump(mode="json"), ensure_ascii=False)
        except Exception:
            logger.debug("MCP 内容块序列化失败", exc_info=True)
    return str(item)


def _json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except Exception:
            logger.debug("MCP 结构化数据序列化失败", exc_info=True)
    return value


def format_mcp_tool_result(result: Any, server: str, tool_name: str) -> ToolResult:
    """把 MCP ``CallToolResult`` 转换为 HAgent 的统一工具结果。"""
    parts: list[str] = []
    for item in _value(result, "content", default=[]) or []:
        rendered = _content_to_text(item)
        if rendered:
            parts.append(rendered)

    structured = _value(result, "structuredContent", "structured_content")
    if structured is not None:
        try:
            rendered_structured = json.dumps(
                _json_value(structured),
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        except (TypeError, ValueError):
            rendered_structured = str(structured)
        parts.append(f"结构化数据：\n{rendered_structured}")

    is_error = bool(_value(result, "isError", "is_error", default=False))
    text = "\n".join(part for part in parts if part).strip()
    if is_error:
        return ToolResult.failure(text or f"MCP 工具 `{server}/{tool_name}` 返回错误")
    if not text:
        text = f"(MCP 工具 `{server}/{tool_name}` 未返回内容)"
    return ToolResult.success(text)


class MCPClientManager:
    """管理多个 MCP Server 的连接、工具发现与调用。"""

    def __init__(self, servers: Mapping[str, MCPServerConfig]) -> None:
        self._servers = dict(servers)
        self._sessions: dict[str, Any] = {}
        self._tools: dict[str, list[MCPToolInfo]] = {}
        self._errors: dict[str, str] = {}
        self._worker: _MCPWorker | None = None
        if self._servers:
            if not MCP_SDK_AVAILABLE:
                for name in self._servers:
                    self._errors[name] = "未安装 mcp 依赖，请执行 pip install mcp"
            else:
                self._worker = _MCPWorker()

    # ------------------------------------------------------------------ 属性

    @property
    def servers(self) -> dict[str, MCPServerConfig]:
        return dict(self._servers)

    @property
    def tools(self) -> dict[str, list[MCPToolInfo]]:
        return {name: list(tools) for name, tools in self._tools.items()}

    @property
    def errors(self) -> dict[str, str]:
        return dict(self._errors)

    @property
    def connected_servers(self) -> list[str]:
        return list(self._sessions)

    # ------------------------------------------------------------------ 发现

    def discover(self) -> dict[str, list[MCPToolInfo]]:
        """连接所有 Server 并调用 ``list_tools()``，单个 Server 失败不影响其他 Server。"""
        if self._worker is None:
            return self.tools

        for name, config in self._servers.items():
            timeout = config.timeout + 10
            try:
                session, tools = self._worker.submit(
                    lambda stack, cfg=config: self._connect_server(stack, cfg),
                    timeout=timeout,
                )
            except Exception as exc:  # noqa: BLE001 - 连接失败需要降级为日志
                message = _format_exception(exc)
                self._errors[name] = message
                logger.warning("MCP Server `%s` 连接失败：%s", name, message)
                continue
            self._sessions[name] = session
            self._tools[name] = tools
            self._errors.pop(name, None)
            logger.info(
                "已连接 MCP Server `%s`，发现 %d 个工具：%s",
                name,
                len(tools),
                ", ".join(tool.name for tool in tools) or "无",
            )
        return self.tools

    async def _connect_server(
        self,
        stack: AsyncExitStack,
        config: MCPServerConfig,
    ) -> tuple[Any, list[MCPToolInfo]]:
        if not MCP_SDK_AVAILABLE:
            raise MCPConnectionError("未安装 mcp 依赖，请执行 pip install mcp")

        server_stack = await stack.enter_async_context(AsyncExitStack())
        try:
            read_stream, write_stream = await self._open_transport(server_stack, config)
            session = await server_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await session.initialize()
            result = await session.list_tools()
            tools = [self._to_tool_info(tool) for tool in _value(result, "tools", default=[]) or []]
            return session, tools
        except BaseException:
            await server_stack.aclose()
            raise

    async def _open_transport(
        self,
        stack: AsyncExitStack,
        config: MCPServerConfig,
    ) -> tuple[Any, Any]:
        if config.transport == "sse":
            transport = sse_client(
                config.url,
                headers=config.headers or None,
                timeout=min(config.timeout, 30.0),
                sse_read_timeout=max(config.timeout, 300.0),
            )
        else:
            transport = streamable_http_client(config.url)

        streams = await stack.enter_async_context(transport)
        if not isinstance(streams, Sequence) or len(streams) < 2:
            raise MCPConnectionError(f"MCP 传输层返回了无法识别的数据流：{type(streams).__name__}")
        return streams[0], streams[1]

    @staticmethod
    def _to_tool_info(tool: Any) -> MCPToolInfo:
        name = str(_value(tool, "name", default="") or "").strip()
        if not name:
            raise MCPConnectionError("MCP Server 返回了缺少 name 的工具")
        description = str(_value(tool, "description", default="") or "").strip()
        parameters = _value(tool, "input_schema", "inputSchema")
        if hasattr(parameters, "model_dump"):
            parameters = parameters.model_dump(mode="json")
        if not isinstance(parameters, dict) or not parameters:
            parameters = {"type": "object", "properties": {}}
        return MCPToolInfo(name=name, description=description, parameters=parameters)

    # ------------------------------------------------------------------ 调用

    def call_tool(self, server: str, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        """调用指定 Server 上的原始工具，并格式化返回内容。"""
        session = self._sessions.get(server)
        if session is None:
            detail = self._errors.get(server) or "尚未连接"
            return ToolResult.failure(f"MCP Server `{server}` 不可用：{detail}")

        config = self._servers.get(server)
        timeout = config.timeout if config is not None else _DEFAULT_TIMEOUT
        if self._worker is None:
            return ToolResult.failure(f"MCP Server `{server}` 不可用：MCP 客户端未启动")

        try:
            result = self._worker.submit(
                lambda _stack: session.call_tool(tool_name, arguments or {}),
                timeout=timeout,
            )
        except Exception as exc:  # noqa: BLE001 - 工具异常需要转成失败结果
            message = _format_exception(exc)
            logger.warning("调用 MCP 工具 `%s/%s` 失败：%s", server, tool_name, message)
            return ToolResult.failure(f"调用 MCP 工具失败（{server}/{tool_name}）：{message}")
        return format_mcp_tool_result(result, server, tool_name)

    def close(self) -> None:
        """关闭后台连接（主要用于测试或显式退出）。"""
        if self._worker is not None:
            self._worker.close()

    def __len__(self) -> int:
        return sum(len(tools) for tools in self._tools.values())


# ----------------------------------------------------------------------
# 工具注册
# ----------------------------------------------------------------------


def _sanitize_tool_name(raw: str, fallback: str, max_length: int = _MAX_TOOL_NAME_LENGTH) -> str:
    cleaned = _TOOL_NAME_PATTERN.sub("_", raw.strip()).strip("_")
    if not cleaned:
        cleaned = fallback
    if len(cleaned) > max_length:
        digest = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:8]
        cleaned = f"{cleaned[: max_length - 9]}_{digest}"
    return cleaned


def _unique_name(candidate: str, used: set[str], max_length: int = _MAX_TOOL_NAME_LENGTH) -> str:
    if candidate not in used:
        return candidate
    index = 2
    while True:
        suffix = f"_{index}"
        base = candidate[: max_length - len(suffix)]
        name = f"{base}{suffix}"
        if name not in used:
            return name
        index += 1


def build_tool_bindings(
    registry: ToolRegistry,
    tools_by_server: Mapping[str, Sequence[MCPToolInfo]],
    max_tool_name_length: int = _MAX_TOOL_NAME_LENGTH,
) -> list[MCPToolBinding]:
    """为 MCP 工具生成最终暴露给 LLM 的名称，并处理冲突。

    默认直接使用 MCP 工具原名；当不同 Server 出现同名工具，或与本地工具冲突时，
    自动加上 ``<server>_<tool>`` 前缀。
    """
    entries: list[tuple[str, MCPToolInfo, str]] = []
    for server, tools in tools_by_server.items():
        for tool in tools:
            base = _sanitize_tool_name(tool.name, "mcp_tool", max_tool_name_length)
            entries.append((server, tool, base))

    counts = Counter(base for _, _, base in entries)
    used = set(registry.names()) | _RESERVED_TOOL_NAMES
    bindings: list[MCPToolBinding] = []

    for server, tool, base in entries:
        if counts[base] == 1 and base not in used:
            exposed = base
        else:
            prefix = _sanitize_tool_name(server, "mcp", max_tool_name_length)
            exposed = _sanitize_tool_name(
                f"{prefix}_{base}",
                f"mcp_{base}",
                max_tool_name_length,
            )
        exposed = _unique_name(exposed, used, max_tool_name_length)
        used.add(exposed)
        description = tool.description or f"MCP tool `{tool.name}` from server `{server}`"
        bindings.append(
            MCPToolBinding(
                exposed_name=exposed,
                server=server,
                tool_name=tool.name,
                description=f"[MCP:{server}] {description}",
                parameters=tool.parameters,
            )
        )
    return bindings


def _make_handler(
    manager: MCPClientManager,
    binding: MCPToolBinding,
) -> Callable[..., ToolResult]:
    def handler(**arguments: Any) -> ToolResult:
        return manager.call_tool(binding.server, binding.tool_name, arguments)

    handler.__name__ = binding.exposed_name
    return handler


def register_mcp_tools(
    registry: ToolRegistry,
    root: Path | None = None,
    config_path: Path | None = None,
    manager: MCPClientManager | None = None,
    config_file: str = MCP_CONFIG_FILENAME,
    default_timeout: float = _DEFAULT_TIMEOUT,
    max_tool_name_length: int = _MAX_TOOL_NAME_LENGTH,
) -> MCPClientManager | None:
    """读取 MCP 配置、连接 Server，并把发现的工具注册到 ``registry``。

    连接失败的 Server 只会记录告警并跳过，不影响本地工具与其他 Server。
    返回 :class:`MCPClientManager`（没有配置时返回 ``None``），便于上层查询错误。
    """
    if manager is None:
        try:
            configs = load_mcp_config(
                root=root,
                config_path=config_path,
                config_file=config_file,
                default_timeout=default_timeout,
            )
        except MCPConfigError as exc:
            logger.warning("加载 MCP 配置失败：%s", exc)
            return None
        if not configs:
            return None
        try:
            manager = MCPClientManager(configs)
            manager.discover()
        except Exception as exc:  # noqa: BLE001 - MCP 初始化失败不应影响本地工具
            logger.warning("初始化 MCP 客户端失败：%s", _format_exception(exc))
            return None
    else:
        if not manager.tools and getattr(manager, "servers", None):
            manager.discover()

    bindings = build_tool_bindings(registry, manager.tools, max_tool_name_length)
    for binding in bindings:
        registry.register(
            ToolSpec(
                name=binding.exposed_name,
                description=binding.description,
                parameters=binding.parameters,
                handler=_make_handler(manager, binding),
            )
        )
    if bindings:
        logger.info("已注册 %d 个 MCP 工具：%s", len(bindings), ", ".join(b.exposed_name for b in bindings))
    return manager


__all__ = [
    "MCP_CONFIG_FILENAME",
    "MCPClientManager",
    "MCPServerConfig",
    "MCPToolBinding",
    "MCPToolInfo",
    "build_tool_bindings",
    "format_mcp_tool_result",
    "load_mcp_config",
    "register_mcp_tools",
]

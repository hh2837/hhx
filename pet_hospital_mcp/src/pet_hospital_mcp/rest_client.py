"""Go 宠物医院 REST API 的 HTTP 客户端封装。

职责：
- 通过 HTTP 调用上游 Go REST API（唯一业务后端，MCP 服务只允许走 HTTP）。
- 统一超时与有限重试（仅针对瞬时错误：连接失败/超时；4xx/5xx 不重试）。
- 把上游各类异常翻译为带错误码的 ``BackendError`` 子类，供工具层映射为
  统一错误结构。

本模块不包含任何业务参数拼装逻辑（由 tools/ 负责），后续阶段新增工具可直接复用。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Mapping

import httpx

from .errors import ErrorCode
from .logging_config import get_logger

logger = get_logger(__name__)

#: 尝试解析上游错误响应体时，后端原始 message 的最大长度
_BACKEND_MESSAGE_MAX_LEN = 500


class BackendError(Exception):
    """后端调用失败基类，携带统一错误码与可读信息。"""

    code: ErrorCode = ErrorCode.INTERNAL_ERROR
    message: str = "Backend error"
    details: dict[str, Any]

    def __init__(self, message: str | None = None, details: dict[str, Any] | None = None) -> None:
        self.message = message or self.message
        self.details = details or {}
        super().__init__(self.message)

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "details": self.details,
        }


class BackendTimeoutError(BackendError):
    """后端调用超时。"""

    code = ErrorCode.BACKEND_TIMEOUT
    message = "Backend request timed out"


class BackendUnavailableError(BackendError):
    """后端不可达（连接失败等）。"""

    code = ErrorCode.BACKEND_UNAVAILABLE
    message = "Backend service is unavailable"


class BackendApiError(BackendError):
    """后端返回了 4xx/5xx。"""

    code = ErrorCode.BACKEND_API_ERROR
    message = "Backend returned an error response"


class BackendInvalidResponseError(BackendError):
    """后端返回了非法 JSON 或不符合预期数据模型。"""

    code = ErrorCode.BACKEND_INVALID_RESPONSE
    message = "Backend returned an invalid response"


def _extract_backend_message(body: str, status_code: int) -> str:
    """从错误响应体中尽力提取可读 message，失败则回退为状态码说明。"""
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return f"HTTP {status_code}"
    if isinstance(parsed, dict):
        err = parsed.get("error")
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            return err["message"]
        if isinstance(parsed.get("message"), str):
            return parsed["message"]
    return f"HTTP {status_code}"


class RestClient:
    """面向 Go REST API 的异步 HTTP 客户端。"""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 10.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        # transport 仅用于测试注入（httpx.MockTransport / respx 亦可全局拦截）
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout_seconds,
            transport=transport,
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def base_url(self) -> str:
        return self._base_url

    async def get(self, path: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """执行 GET 并返回解析后的 JSON 对象。

        成功仅当 2xx 且响应体为合法 JSON 对象；其余情况抛出对应
        ``BackendError`` 子类。
        """
        last_error: BackendError | None = None
        attempts = self._max_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                return await self._get_once(path, params, attempt)
            except BackendTimeoutError as exc:
                last_error = exc
            except BackendUnavailableError as exc:
                last_error = exc
            # 4xx/5xx 与响应解析错误不重试（确定性失败）
            if attempt < attempts:
                await asyncio.sleep(self._retry_backoff_seconds)
        assert last_error is not None
        raise last_error

    async def _get_once(
        self, path: str, params: Mapping[str, Any] | None, attempt: int
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        started = asyncio.get_event_loop().time()
        try:
            response = await self._client.get(path, params=params)
        except httpx.TimeoutException as exc:
            duration_ms = (asyncio.get_event_loop().time() - started) * 1000
            logger.warning(
                "backend_timeout",
                extra={
                    "url": url,
                    "params": dict(params) if params else None,
                    "attempt": attempt,
                    "duration_ms": round(duration_ms, 1),
                },
            )
            raise BackendTimeoutError(
                details={
                    "url": url,
                    "attempt": attempt,
                    "timeout_seconds": self._timeout_seconds,
                }
            ) from exc
        except httpx.ConnectError as exc:
            duration_ms = (asyncio.get_event_loop().time() - started) * 1000
            logger.warning(
                "backend_unavailable",
                extra={
                    "url": url,
                    "attempt": attempt,
                    "duration_ms": round(duration_ms, 1),
                },
            )
            raise BackendUnavailableError(
                details={
                    "url": url,
                    "attempt": attempt,
                    "exception": exc.__class__.__name__,
                }
            ) from exc

        duration_ms = (asyncio.get_event_loop().time() - started) * 1000
        if response.status_code < 200 or response.status_code >= 300:
            backend_message = _extract_backend_message(response.text, response.status_code)
            logger.error(
                "backend_api_error",
                extra={
                    "url": url,
                    "status": response.status_code,
                    "duration_ms": round(duration_ms, 1),
                },
            )
            raise BackendApiError(
                details={
                    "url": url,
                    "status": response.status_code,
                    "backend_message": backend_message[:_BACKEND_MESSAGE_MAX_LEN],
                }
            )

        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error(
                "backend_invalid_json",
                extra={
                    "url": url,
                    "status": response.status_code,
                    "duration_ms": round(duration_ms, 1),
                },
            )
            raise BackendInvalidResponseError(
                details={
                    "url": url,
                    "status": response.status_code,
                    "content_type": response.headers.get("content-type"),
                }
            ) from exc

        if not isinstance(payload, dict):
            raise BackendInvalidResponseError(
                details={
                    "url": url,
                    "status": response.status_code,
                    "reason": "response body is not a JSON object",
                }
            )
        logger.debug(
            "backend_ok",
            extra={"url": url, "status": response.status_code, "duration_ms": round(duration_ms, 1)},
        )
        return payload

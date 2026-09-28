"""统一错误结构。

所有对 MCP 客户端可见的错误（无效输入、上游异常等）都必须使用这里定义的
统一 JSON 结构返回：

.. code-block:: json

    {
      "error": {
        "code": "ERROR_CODE",
        "message": "可读错误信息",
        "details": {}
      }
    }
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ErrorCode(str, Enum):
    """MCP 服务对外暴露的错误码（阶段一固定集合）。"""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    BACKEND_TIMEOUT = "BACKEND_TIMEOUT"
    BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"
    BACKEND_API_ERROR = "BACKEND_API_ERROR"
    BACKEND_INVALID_RESPONSE = "BACKEND_INVALID_RESPONSE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorDetail(BaseModel):
    """错误结构中的 ``error`` 对象。"""

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    """统一错误信封：``{"error": {code, message, details}}``。"""

    error: ErrorDetail


def build_error(
    code: ErrorCode | str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造统一的错误结构（纯 dict，可直接 JSON 序列化）。"""
    envelope = ErrorEnvelope(
        error=ErrorDetail(
            code=code.value if isinstance(code, ErrorCode) else code,
            message=message,
            details=details or {},
        )
    )
    return envelope.model_dump(mode="json")

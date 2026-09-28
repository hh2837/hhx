"""标准库 JSON 结构化日志。

每条工具调用日志至少包含：``timestamp``、``tool_name``、``params``、
``status``、``duration_ms``。

敏感字段（``ownerPhone``、``ownerAddr``、``chipNo`` 及其 snake_case 写法）
会在写入日志前被递归脱敏，绝不把完整敏感数据落盘。
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any

#: 敏感字段名集合（归一化后匹配：小写 + 去下划线）
_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {"ownerphone", "owneraddr", "chipno"}
)

_KEY_NORMALIZE_RE = re.compile(r"[^a-z0-9]")


def _normalize_key(key: str) -> str:
    return _KEY_NORMALIZE_RE.sub("", key.lower())


def redact(value: Any) -> Any:
    """递归脱敏：匹配敏感键名的值替换为 ``"***"``。"""
    if isinstance(value, dict):
        return {
            k: ("***" if _normalize_key(str(k)) in _SENSITIVE_KEYS else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, tuple):
        return [redact(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    """把日志记录渲染为单行 JSON。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # 业务附加字段（tool_name / params / status / duration_ms ...）
        for key in ("tool_name", "params", "status", "duration_ms", "url", "attempt"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = redact(value) if key == "params" else value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO") -> None:
    """配置 ``pet_hospital_mcp`` 命名空间下的 JSON 日志。"""
    logger = logging.getLogger("pet_hospital_mcp")
    if logger.handlers:  # 幂等
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(level.upper())
    logger.propagate = False


def get_logger(name: str) -> logging.Logger:
    """获取包内日志器（统一走 JSON 格式）。"""
    return logging.getLogger(f"pet_hospital_mcp.{name}")

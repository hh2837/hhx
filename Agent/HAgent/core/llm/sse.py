"""Server-Sent Events（SSE）解析工具。

大模型服务普遍以 SSE 协议返回流式结果，这里把原始字节行转换成 JSON 对象，
与具体的 HTTP 客户端实现解耦。
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any

DONE_MARKER = "[DONE]"


def decode_line(line: bytes | str) -> str:
    """把一行原始数据解码成字符串（忽略解码错误）。"""
    if isinstance(line, bytes):
        return line.decode("utf-8", errors="replace")
    return line


def parse_sse_line(line: bytes | str) -> dict[str, Any] | None:
    """解析单行 SSE 数据。

    返回解析后的 JSON 对象；若是心跳注释、空行或 ``[DONE]`` 则返回 ``None``。
    """
    text = decode_line(line).strip()
    if not text or text.startswith(":") or not text.startswith("data:"):
        return None
    data = text[len("data:") :].strip()
    if not data or data == DONE_MARKER:
        return None
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def iter_sse_payloads(lines: Iterable[bytes | str]) -> Iterator[dict[str, Any]]:
    """迭代一组 SSE 行，产出可解析的 JSON 负载。"""
    for line in lines:
        payload = parse_sse_line(line)
        if payload is not None:
            yield payload


__all__ = ["DONE_MARKER", "decode_line", "iter_sse_payloads", "parse_sse_line"]

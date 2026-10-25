"""OpenAI 兼容协议的大模型客户端。

兼容绝大多数提供 ``/v1/chat/completions`` 接口的服务（LM Studio、Ollama、
vLLM、DeepSeek、OpenAI 官方……），支持 SSE 流式输出与 function calling。
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

import requests

from ..config import LLMConfig
from ..errors import LLMConnectionError, LLMResponseError
from ..models import Message
from .client import LLMClient, StreamChunk, ToolCallDelta
from .sse import iter_sse_payloads


class OpenAICompatibleClient(LLMClient):
    """基于 ``requests`` 的 OpenAI 兼容客户端。"""

    def __init__(self, config: LLMConfig, session: requests.Session | None = None) -> None:
        self._config = config
        self._session = session or requests.Session()

    @property
    def config(self) -> LLMConfig:
        return self._config

    def build_payload(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """构造请求体（与传输解耦，便于测试）。"""
        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": [message.to_payload() for message in messages],
            "stream": True,
        }
        if tools:
            payload["tools"] = list(tools)
        if self._config.temperature is not None:
            payload["temperature"] = self._config.temperature
        return payload

    def build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        return headers

    def stream_chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> Iterator[StreamChunk]:
        payload = self.build_payload(messages, tools)
        try:
            response = self._session.post(
                self._config.chat_completions_url,
                headers=self.build_headers(),
                json=payload,
                stream=True,
                timeout=self._config.timeout,
            )
        except requests.RequestException as exc:
            raise LLMConnectionError(f"无法连接大模型服务：{exc}") from exc

        with response:
            if response.status_code >= 400:
                raise LLMResponseError(
                    f"大模型服务返回错误 {response.status_code}：{self._safe_body(response)}"
                )
            for data in iter_sse_payloads(response.iter_lines()):
                chunk = self._to_chunk(data)
                if chunk is not None:
                    yield chunk

    @staticmethod
    def _safe_body(response: requests.Response) -> str:
        try:
            return response.text[:500]
        except Exception:  # noqa: BLE001 - 防御性：任何异常都不应掩盖原始错误
            return "<无法读取响应体>"

    @staticmethod
    def _to_chunk(data: dict[str, Any]) -> StreamChunk | None:
        choices = data.get("choices") or []
        if not choices:
            return None
        choice = choices[0] or {}
        delta = choice.get("delta") or {}

        content = delta.get("content") or ""
        reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""

        deltas: list[ToolCallDelta] = []
        for raw in delta.get("tool_calls") or []:
            function = raw.get("function") or {}
            deltas.append(
                ToolCallDelta(
                    index=int(raw.get("index", 0) or 0),
                    id=raw.get("id") or "",
                    name=function.get("name") or "",
                    arguments=function.get("arguments") or "",
                )
            )

        finish_reason = choice.get("finish_reason")
        if not (content or reasoning or deltas or finish_reason):
            return None
        return StreamChunk(
            content=content,
            reasoning=reasoning,
            tool_call_deltas=deltas,
            finish_reason=finish_reason,
        )

    def close(self) -> None:
        self._session.close()


__all__ = ["OpenAICompatibleClient"]

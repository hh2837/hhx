"""OpenAI 兼容协议的大模型客户端。

兼容绝大多数提供 ``/v1/chat/completions`` 接口的服务（LM Studio、Ollama、
vLLM、DeepSeek、OpenAI 官方……），使用非流式响应并支持 function calling。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import requests

from ..config import LLMConfig
from ..errors import LLMConnectionError, LLMResponseError
from ..models import Message, ToolCall
from .client import ChatResponse, LLMClient, TokenUsage


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
            "stream": False,
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

    def chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        payload = self.build_payload(messages, tools)
        try:
            response = self._session.post(
                self._config.chat_completions_url,
                headers=self.build_headers(),
                json=payload,
                timeout=self._config.timeout,
            )
        except requests.RequestException as exc:
            raise LLMConnectionError(f"无法连接大模型服务：{exc}") from exc

        with response:
            if response.status_code >= 400:
                raise LLMResponseError(
                    f"大模型服务返回错误 {response.status_code}：{self._safe_body(response)}"
                )
            return self._to_response(self._read_json(response))

    @staticmethod
    def _safe_body(response: requests.Response) -> str:
        try:
            return response.text[:500]
        except Exception:  # noqa: BLE001 - 防御性：任何异常都不应掩盖原始错误
            return "<无法读取响应体>"

    @staticmethod
    def _read_json(response: requests.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMResponseError(f"大模型服务返回了无法解析的响应：{exc}") from exc
        if not isinstance(data, dict):
            raise LLMResponseError("大模型服务返回的响应格式不是 JSON 对象。")
        return data

    @staticmethod
    def _to_response(data: dict[str, Any]) -> ChatResponse:
        choices = data.get("choices") or []
        if not choices:
            return ChatResponse()

        choice = choices[0] or {}
        message = choice.get("message") or {}

        content = message.get("content") or ""
        reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
        tool_calls = [
            ToolCall.from_payload(raw)
            for raw in message.get("tool_calls") or []
            if isinstance(raw, dict)
        ]

        raw_usage = data.get("usage")
        usage = TokenUsage.from_payload(raw_usage) if isinstance(raw_usage, dict) else None

        return ChatResponse(
            content=content,
            reasoning=reasoning,
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason"),
            usage=usage,
        )

    def close(self) -> None:
        self._session.close()


__all__ = ["OpenAICompatibleClient"]

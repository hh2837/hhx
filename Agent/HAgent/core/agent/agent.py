"""Agent 编排：把"模型 → 工具 → 模型"的循环收敛在一处。

这一层只产生 :mod:`core.events` 事件，不做任何界面相关的事情。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import Any

from ..config import AgentConfig
from ..errors import MaxToolRoundsExceeded
from ..events import (
    AssistantDelta,
    AssistantMessage,
    AssistantMessageStarted,
    ErrorOccurred,
    Event,
    EventEmitter,
    RunFinished,
    RunStarted,
    ToolCallFinished,
    ToolCallRequested,
    UserMessageEcho,
)
from ..llm.client import LLMClient
from ..models import Message, ToolCall
from ..tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class Agent:
    """一个可复用的智能体。

    典型用法::

        agent = Agent(client=OpenAICompatibleClient(config.llm),
                      tools=register_builtin_tools(ToolRegistry()))
        answer = agent.run("现在几点？", emit=print)
    """

    def __init__(
        self,
        client: LLMClient,
        tools: ToolRegistry,
        config: AgentConfig | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self._client = client
        self._tools = tools
        self._config = config or AgentConfig()
        self._system_prompt = system_prompt if system_prompt is not None else self._config.system_prompt
        self._messages: list[Message] = []
        if self._system_prompt:
            self._messages.append(Message.system(self._system_prompt))

    # ------------------------------------------------------------------ 状态

    @property
    def client(self) -> LLMClient:
        return self._client

    @property
    def tools(self) -> ToolRegistry:
        return self._tools

    @property
    def config(self) -> AgentConfig:
        return self._config

    @property
    def messages(self) -> list[Message]:
        return list(self._messages)

    def reset(self) -> None:
        """清空会话历史（保留系统提示词）。"""
        self._messages = [Message.system(self._system_prompt)] if self._system_prompt else []

    def set_messages(self, messages: Iterable[Message]) -> None:
        """用外部历史覆盖当前历史。"""
        self._messages = list(messages)

    # ------------------------------------------------------------------ 运行

    def run(self, user_input: str, emit: EventEmitter | None = None) -> str:
        """处理一次用户输入，返回最终回答文本。"""
        emitter: EventEmitter = emit or (lambda event: None)
        self._safe_emit(emitter, RunStarted(user_input=user_input))

        self._messages.append(Message.user(user_input))
        self._safe_emit(emitter, UserMessageEcho(text=user_input))
        self._trim_history()

        rounds = 0
        while rounds < self._config.max_tool_rounds:
            rounds += 1
            answer, tool_calls = self._stream_once(emitter)

            if not tool_calls:
                self._messages.append(Message.assistant(answer))
                self._safe_emit(emitter, RunFinished(answer=answer, rounds=rounds))
                return answer

            self._messages.append(Message.assistant(answer, tool_calls))
            for call in tool_calls:
                self._safe_emit(emitter, ToolCallRequested(call=call))
                result = self._tools.execute(call.name, call.arguments)
                output = result.content if result.ok else f"[工具执行失败] {result.error}"
                self._safe_emit(
                    emitter,
                    ToolCallFinished(call=call, ok=result.ok, output=output),
                )
                self._messages.append(Message.tool(output, call.id, call.name))

        message = f"工具调用轮次超过上限（{self._config.max_tool_rounds}），已终止本轮对话。"
        self._safe_emit(emitter, ErrorOccurred(message=message))
        raise MaxToolRoundsExceeded(message)

    # ------------------------------------------------------------------ 内部实现

    def _stream_once(self, emitter: EventEmitter) -> tuple[str, list[ToolCall]]:
        """请求一次模型，收集回答文本与工具调用。"""
        answer_parts: list[str] = []
        accumulator: dict[int, dict[str, Any]] = {}
        started = False

        for chunk in self._client.stream_chat(self._messages, self._tools.schemas()):
            if chunk.content:
                if not started:
                    started = True
                    self._safe_emit(emitter, AssistantMessageStarted())
                answer_parts.append(chunk.content)
                self._safe_emit(emitter, AssistantDelta(text=chunk.content))
            for delta in chunk.tool_call_deltas:
                entry = accumulator.setdefault(delta.index, {"id": "", "name": "", "arguments": ""})
                if delta.id:
                    entry["id"] = delta.id
                if delta.name:
                    entry["name"] += delta.name
                if delta.arguments:
                    entry["arguments"] += delta.arguments

        answer = "".join(answer_parts)
        if started:
            self._safe_emit(emitter, AssistantMessage(text=answer))
        tool_calls = [self._to_tool_call(index, entry) for index, entry in sorted(accumulator.items())]
        return answer, tool_calls

    @staticmethod
    def _to_tool_call(index: int, entry: dict[str, Any]) -> ToolCall:
        raw_arguments = entry.get("arguments") or "{}"
        try:
            arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else dict(raw_arguments)
        except json.JSONDecodeError:
            arguments = {}
        if not isinstance(arguments, dict):
            arguments = {"value": arguments}
        return ToolCall(
            id=entry.get("id") or f"call_{index}",
            name=entry.get("name") or "",
            arguments=arguments,
        )

    def _trim_history(self) -> None:
        """限制历史长度，保留系统提示词与最近的若干条消息。"""
        limit = self._config.max_history_messages
        if limit <= 0 or len(self._messages) <= limit:
            return
        head = self._messages[:1] if self._messages and self._messages[0].role == "system" else []
        tail = self._messages[len(head) :][-limit:]
        self._messages = head + tail

    @staticmethod
    def _safe_emit(emitter: EventEmitter, event: Event) -> None:
        """事件回调异常不应中断 Agent 主循环。"""
        try:
            emitter(event)
        except Exception:
            logger.exception("事件回调执行失败：%s", type(event).__name__)


__all__ = ["Agent"]

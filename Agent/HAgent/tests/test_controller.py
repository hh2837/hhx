"""控制器翻译与非流式客户端解析的测试。"""

from __future__ import annotations

from core import (
    Agent,
    AgentConfig,
    ChatResponse,
    LLMConfig,
    OpenAICompatibleClient,
    ToolCall,
    ToolRegistry,
)
from core.llm.client import LLMClient
from tui.controller import ChatController


class FakeClient(LLMClient):
    """按脚本返回完整响应：每次请求消耗一段脚本。"""

    def __init__(self, scripts: list[ChatResponse]) -> None:
        self.scripts = list(scripts)

    def chat(self, messages, tools=None):
        return self.scripts.pop(0) if self.scripts else ChatResponse()


class RecordingViewport:
    """记录界面收到的所有调用。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def _record(self, name: str, payload: object = "") -> None:
        self.calls.append((name, payload))

    def show_user_message(self, text: str) -> None:
        self._record("user", text)

    def start_assistant_message(self) -> None:
        self._record("assistant-start")

    def finish_assistant_message(self, text: str) -> None:
        self._record("assistant-end", text)

    def show_tool_call(self, call) -> None:
        self._record("tool-call", call.name)

    def show_tool_result(self, call, ok: bool, output: str) -> None:
        self._record("tool-result", (call.name, ok))

    def show_error(self, message: str, detail: str = "") -> None:
        self._record("error", message)

    def set_status(self, status: str) -> None:
        self._record("status", status)

    def clear_transcript(self) -> None:
        self._record("clear")

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


def test_控制器把事件翻译成界面动作() -> None:
    client = FakeClient(
        [
            ChatResponse(
                tool_calls=[ToolCall(id="c1", name="noop", arguments={})]
            ),
            ChatResponse(content="完成"),
        ]
    )
    agent = Agent(
        client=client,
        tools=ToolRegistry(),
        config=AgentConfig(system_prompt="s", max_tool_rounds=3),
    )
    viewport = RecordingViewport()
    controller = ChatController(agent, viewport)

    controller.submit("跑一下")

    names = viewport.names()
    assert "user" in names
    assert "assistant-start" in names
    assert "tool-call" in names
    assert "tool-result" in names
    assert "assistant-end" in names
    assert names[-1] == "status"


def test_控制器忽略空输入() -> None:
    viewport = RecordingViewport()
    agent = Agent(client=FakeClient([]), tools=ToolRegistry())
    controller = ChatController(agent, viewport)
    assert controller.submit("   ") == ""
    assert viewport.calls == []


def test_请求体使用非流式模式() -> None:
    client = OpenAICompatibleClient(LLMConfig(model="test-model"))
    payload = client.build_payload([])
    assert payload["stream"] is False


def test_解析非流式完整响应() -> None:
    response = OpenAICompatibleClient._to_response(
        {
            "choices": [
                {
                    "message": {
                        "content": "好的",
                        "tool_calls": [
                            {
                                "id": "c1",
                                "type": "function",
                                "function": {"name": "noop", "arguments": '{"a": 1}'},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
    )
    assert response.content == "好的"
    assert response.finish_reason == "tool_calls"
    assert response.tool_calls[0].name == "noop"
    assert response.tool_calls[0].arguments == {"a": 1}

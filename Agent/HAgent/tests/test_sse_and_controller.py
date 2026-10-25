"""SSE 解析与控制器翻译的测试。"""

from __future__ import annotations

from core import Agent, AgentConfig, StreamChunk, ToolCallDelta, ToolRegistry
from core.llm.client import LLMClient
from core.llm.sse import iter_sse_payloads, parse_sse_line
from tui.controller import ChatController


class FakeClient(LLMClient):
    """按脚本产出流式分段：每次请求消耗一段脚本。"""

    def __init__(self, scripts: list[list[StreamChunk]]) -> None:
        self.scripts = list(scripts)

    def stream_chat(self, messages, tools=None):
        script = self.scripts.pop(0) if self.scripts else []
        yield from script


def test_解析data行() -> None:
    payload = parse_sse_line(b'data: {"choices": [{"delta": {"content": "hi"}}]}')
    assert payload is not None
    assert payload["choices"][0]["delta"]["content"] == "hi"


def test_忽略心跳与结束标记() -> None:
    assert parse_sse_line(b": ping") is None
    assert parse_sse_line(b"data: [DONE]") is None
    assert parse_sse_line(b"") is None
    assert parse_sse_line(b"event: message") is None


def test_批量迭代忽略非法json() -> None:
    payloads = list(iter_sse_payloads([b"data: {bad}", b'data: {"ok": true}']))
    assert payloads == [{"ok": True}]


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

    def append_assistant_delta(self, text: str) -> None:
        self._record("delta", text)

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
            [
                StreamChunk(
                    tool_call_deltas=[ToolCallDelta(index=0, id="c1", name="noop", arguments="{}")]
                )
            ],
            [StreamChunk(content="完成")],
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

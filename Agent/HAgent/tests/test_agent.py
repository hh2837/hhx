"""Agent 主循环与事件流的测试（使用假的 LLM 客户端，完全离线）。"""

from __future__ import annotations

from core import (
    Agent,
    AgentConfig,
    AssistantDelta,
    AssistantMessage,
    AssistantMessageStarted,
    RunFinished,
    RunStarted,
    StreamChunk,
    ToolCall,
    ToolCallDelta,
    ToolCallFinished,
    ToolCallRequested,
    ToolRegistry,
    UserMessageEcho,
)
from core.llm.client import LLMClient
from core.tools.datetime_tools import register_datetime_tools


class FakeClient(LLMClient):
    """按脚本产出流式分段的假客户端。"""

    def __init__(self, scripts: list[list[StreamChunk]]) -> None:
        self.scripts = list(scripts)
        self.requests: list[list[dict]] = []

    def stream_chat(self, messages, tools=None):
        self.requests.append([message.to_payload() for message in messages])
        script = self.scripts.pop(0) if self.scripts else []
        yield from script


def _agent(scripts: list[list[StreamChunk]]) -> tuple[Agent, FakeClient]:
    client = FakeClient(scripts)
    registry = ToolRegistry()
    register_datetime_tools(registry)
    agent = Agent(
        client=client,
        tools=registry,
        config=AgentConfig(system_prompt="你是助手", max_tool_rounds=4),
    )
    return agent, client


def test_纯文本回答会流式产出事件() -> None:
    agent, _ = _agent([[StreamChunk(content="你好"), StreamChunk(content="，世界")]])
    events = []
    answer = agent.run("打个招呼", emit=events.append)

    assert answer == "你好，世界"
    kinds = [type(event) for event in events]
    assert kinds[0] is RunStarted
    assert UserMessageEcho in kinds
    assert AssistantMessageStarted in kinds
    assert kinds.count(AssistantDelta) == 2
    assert AssistantMessage in kinds
    assert kinds[-1] is RunFinished


def test_工具调用会写回历史() -> None:
    agent, client = _agent(
        [
            [
                StreamChunk(
                    tool_call_deltas=[
                        ToolCallDelta(index=0, id="call_1", name="isLeapYear", arguments='{"year": 2024}')
                    ]
                )
            ],
            [StreamChunk(content="2024年是闰年")],
        ]
    )
    events = []
    answer = agent.run("2024是闰年吗", emit=events.append)

    assert answer == "2024年是闰年"
    assert ToolCallRequested in [type(event) for event in events]
    finished = [event for event in events if isinstance(event, ToolCallFinished)]
    assert finished and finished[0].ok and "闰年" in finished[0].output

    roles = [message.role for message in agent.messages]
    assert roles == ["system", "user", "assistant", "tool", "assistant"]
    assert len(client.requests) == 2
    assert client.requests[1][-1]["role"] == "tool"


def test_工具调用参数分片会正确拼接() -> None:
    agent, _ = _agent(
        [
            [
                StreamChunk(
                    tool_call_deltas=[
                        ToolCallDelta(index=0, id="c1", name="isLeapYear", arguments='{"ye'),
                        ToolCallDelta(index=0, arguments='ar": 2023}'),
                    ]
                )
            ],
            [StreamChunk(content="不是闰年")],
        ]
    )
    answer = agent.run("2023呢")
    assert answer == "不是闰年"
    tool_message = next(message for message in agent.messages if message.role == "tool")
    assert "不是闰年" in tool_message.content


def test_超过工具轮次上限会终止() -> None:
    from core.errors import MaxToolRoundsExceeded

    script = [
        [
            StreamChunk(
                tool_call_deltas=[ToolCallDelta(index=0, id="c", name="isLeapYear", arguments='{"year": 2024}')]
            )
        ]
        for _ in range(5)
    ]
    agent, _ = _agent(script)
    try:
        agent.run("一直调用工具")
    except MaxToolRoundsExceeded:
        pass
    else:  # pragma: no cover - 断言失败分支
        raise AssertionError("应当抛出 MaxToolRoundsExceeded")


def test_事件回调异常不会中断主流程() -> None:
    agent, _ = _agent([[StreamChunk(content="ok")]])

    def broken(_event) -> None:
        raise RuntimeError("界面炸了")

    assert agent.run("测试", emit=broken) == "ok"


def test_历史长度会被裁剪() -> None:
    client = FakeClient([[StreamChunk(content="a")], [StreamChunk(content="b")]])
    registry = ToolRegistry()
    agent = Agent(
        client=client,
        tools=registry,
        config=AgentConfig(system_prompt="s", max_history_messages=3),
    )
    agent.run("一")
    agent.run("二")
    # 发给模型的请求中，除系统提示词外最多保留 max_history_messages 条
    assert len(client.requests[1]) <= 4


def test_重置会话会清空历史() -> None:
    agent, _ = _agent([[StreamChunk(content="ok")]])
    agent.run("你好")
    agent.reset()
    assert len(agent.messages) == 1
    assert agent.messages[0].role == "system"


def test_工具调用对象可序列化() -> None:
    call = ToolCall(id="x", name="n", arguments={"a": 1})
    payload = call.to_payload()
    assert payload["function"]["name"] == "n"
    assert "arguments" in payload["function"]

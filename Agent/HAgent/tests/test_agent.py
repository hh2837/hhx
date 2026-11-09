"""Agent 主循环与事件流的测试（使用假的 LLM 客户端，完全离线）。"""

from __future__ import annotations

from core import (
    Agent,
    AgentConfig,
    AssistantMessage,
    AssistantMessageStarted,
    ChatResponse,
    RunFinished,
    RunStarted,
    ToolCall,
    ToolCallFinished,
    ToolCallRequested,
    ToolRegistry,
    UserMessageEcho,
)
from core.llm.client import LLMClient
from core.tools.datetime_tools import register_datetime_tools


class FakeClient(LLMClient):
    """按脚本返回完整响应的假客户端。"""

    def __init__(self, responses: list[ChatResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[list[dict]] = []

    def chat(self, messages, tools=None):
        self.requests.append([message.to_payload() for message in messages])
        return self.responses.pop(0) if self.responses else ChatResponse()


def _agent(responses: list[ChatResponse]) -> tuple[Agent, FakeClient]:
    client = FakeClient(responses)
    registry = ToolRegistry()
    register_datetime_tools(registry)
    agent = Agent(
        client=client,
        tools=registry,
        config=AgentConfig(system_prompt="你是助手", max_tool_rounds=4),
    )
    return agent, client


def test_纯文本回答一次性产出完整事件() -> None:
    agent, _ = _agent([ChatResponse(content="你好，世界")])
    events = []
    answer = agent.run("打个招呼", emit=events.append)

    assert answer == "你好，世界"
    kinds = [type(event) for event in events]
    assert kinds[0] is RunStarted
    assert UserMessageEcho in kinds
    assert AssistantMessageStarted in kinds
    assert AssistantMessage in kinds
    assert kinds[-1] is RunFinished
    assert [event.text for event in events if isinstance(event, AssistantMessage)] == ["你好，世界"]


def test_工具调用会写回历史() -> None:
    agent, client = _agent(
        [
            ChatResponse(
                tool_calls=[
                    ToolCall(id="call_1", name="isLeapYear", arguments={"year": 2024})
                ]
            ),
            ChatResponse(content="2024年是闰年"),
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


def test_工具调用参数直接使用完整字典() -> None:
    agent, _ = _agent(
        [
            ChatResponse(
                tool_calls=[
                    ToolCall(id="c1", name="isLeapYear", arguments={"year": 2023})
                ]
            ),
            ChatResponse(content="不是闰年"),
        ]
    )
    answer = agent.run("2023呢")
    assert answer == "不是闰年"
    tool_message = next(message for message in agent.messages if message.role == "tool")
    assert "不是闰年" in tool_message.content


def test_超过工具轮次上限会终止() -> None:
    from core.errors import MaxToolRoundsExceeded

    script = [
        ChatResponse(
            tool_calls=[ToolCall(id="c", name="isLeapYear", arguments={"year": 2024})]
        )
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
    agent, _ = _agent([ChatResponse(content="ok")])

    def broken(_event) -> None:
        raise RuntimeError("界面炸了")

    assert agent.run("测试", emit=broken) == "ok"


def test_历史长度会被裁剪() -> None:
    client = FakeClient([ChatResponse(content="a"), ChatResponse(content="b")])
    registry = ToolRegistry()
    agent = Agent(
        client=client,
        tools=registry,
        config=AgentConfig(system_prompt="s", max_history_messages=3),
    )
    agent.run("一")
    agent.run("二")
    assert len(client.requests[1]) <= 4


def test_重置会话会清空历史() -> None:
    agent, _ = _agent([ChatResponse(content="ok")])
    agent.run("你好")
    agent.reset()
    assert len(agent.messages) == 1
    assert agent.messages[0].role == "system"


def test_工具调用对象可序列化() -> None:
    call = ToolCall(id="x", name="n", arguments={"a": 1})
    payload = call.to_payload()
    assert payload["function"]["name"] == "n"
    assert "arguments" in payload["function"]


# ---------------------------------------------------------------------------
# AGENTS.md 一次注入、全程复用
# ---------------------------------------------------------------------------


def _agents_agent(workspace, **kwargs) -> Agent:
    return Agent(
        client=FakeClient([ChatResponse(content="ok")]),
        tools=ToolRegistry(),
        config=AgentConfig(system_prompt="你是助手"),
        workspace=workspace,
        **kwargs,
    )


def test_首次加载会注入_AGENTS_文件(tmp_path) -> None:
    (tmp_path / "AGENTS.md").write_text("本项目使用英语交流。", encoding="utf-8")
    agent = _agents_agent(tmp_path)

    names = [message.name for message in agent.messages]
    assert "AGENTS.md" in names
    assert agent.agents_md_injected
    injected = next(message for message in agent.messages if message.name == "AGENTS.md")
    assert "本项目使用英语交流。" in injected.content


def test_已注入后不会重复注入(tmp_path) -> None:
    (tmp_path / "AGENTS.md").write_text("约定内容", encoding="utf-8")
    agent = _agents_agent(tmp_path)
    count_before = len(agent.messages)

    assert agent.inject_agents_md() is False  # 已存在，不重复
    assert len(agent.messages) == count_before
    assert sum(1 for m in agent.messages if m.name == "AGENTS.md") == 1


def test_无_AGENTS_文件时不注入(tmp_path) -> None:
    agent = _agents_agent(tmp_path)
    assert not agent.agents_md_injected
    assert all(message.name != "AGENTS.md" for message in agent.messages)


def test_新会话_reset_会重新注入(tmp_path) -> None:
    (tmp_path / "AGENTS.md").write_text("约定", encoding="utf-8")
    agent = _agents_agent(tmp_path)
    agent.run("你好")
    agent.reset()
    assert agent.agents_md_injected
    assert any(m.name == "AGENTS.md" for m in agent.messages)


def test_恢复历史时缺失约定会补注入(tmp_path) -> None:
    (tmp_path / "AGENTS.md").write_text("约定", encoding="utf-8")
    agent = _agents_agent(tmp_path)
    # 手工构造一个不含约定消息的历史（模拟旧会话）
    from core import Message

    agent.set_messages([Message.system("系统"), Message.user("旧内容")])
    assert agent.agents_md_injected
    assert any(m.name == "AGENTS.md" for m in agent.messages)


def test_注入事件会通过_emit_发出(tmp_path) -> None:
    from core import AgentsInjected

    agent = _agents_agent(tmp_path)  # 此时还没有 AGENTS.md，未注入
    assert not agent.agents_md_injected

    (tmp_path / "AGENTS.md").write_text("约定", encoding="utf-8")
    events: list = []
    ok = agent.inject_agents_md(emit=events.append)
    assert ok is True
    assert any(isinstance(event, AgentsInjected) for event in events)
    assert agent.agents_md_injected

"""上下文归档、压缩与 recallContext 工具的离线测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from core import (
    Agent,
    AgentConfig,
    ChatResponse,
    CompactionFinished,
    CompactionStarted,
    ContextCompactionRequired,
    ContextError,
    ContextStore,
    ContextWarning,
    Message,
    OpenAICompatibleClient,
    TokenUsage,
    ToolCall,
    ToolRegistry,
    estimate_tokens,
    format_token_count,
    register_recall_context_tool,
)
from core.llm.client import LLMClient


class FakeClient(LLMClient):
    """按脚本返回响应，并记录每次请求。"""

    def __init__(self, scripts: list[ChatResponse]) -> None:
        self.scripts = list(scripts)
        self.requests: list[list[Message]] = []
        self.tools: list[object] = []

    def chat(self, messages, tools=None):
        self.requests.append(list(messages))
        self.tools.append(tools)
        return self.scripts.pop(0) if self.scripts else ChatResponse()


def _agent(
    context_dir: Path,
    scripts: list[ChatResponse],
    *,
    context_window: int | None = None,
    threshold: float = 0.7,
) -> tuple[Agent, FakeClient]:
    client = FakeClient(scripts)
    agent = Agent(
        client=client,
        tools=ToolRegistry(),
        config=AgentConfig(system_prompt="你是助手", compact_threshold=threshold),
        context_dir=context_dir,
        context_window=context_window,
    )
    return agent, client


def test_token_估算与格式化() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("你好世界") >= 4
    assert estimate_tokens("hello world") > 0
    assert format_token_count(128_000) == "128k"
    assert format_token_count(12_300) == "12.3k"
    assert format_token_count(512) == "512"


def test_归档按顺序保存完整消息并支持检索(tmp_path: Path) -> None:
    store = ContextStore(tmp_path)
    messages = [
        Message.system("系统提示"),
        Message.user("请记住秘密关键词 阿尔法"),
        Message.assistant(
            "",
            [ToolCall(id="c1", name="lookup", arguments={"query": "贝塔秘密"})],
        ),
        Message.tool("工具返回 伽马秘密", "c1", "lookup"),
    ]

    record = store.archive(messages)

    assert record.path.exists()
    assert record.path.name == f"{record.archive_id}.jsonl"
    lines = record.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4
    assert '"index": 0' in lines[0]
    assert '"role": "tool"' in lines[3]

    alpha = store.search("阿尔法")
    assert alpha and alpha[0].archive_id == record.archive_id
    assert alpha[0].index == 1
    assert "阿尔法" in alpha[0].snippet

    beta = store.search("贝塔秘密")
    assert beta and "lookup" in beta[0].snippet

    gamma = store.search("伽马秘密")
    assert gamma and gamma[0].role == "tool"

    assert store.search("完全不存在的内容") == []
    with pytest.raises(ValueError):
        store.search("x", archive_id="../evil")


def test_recallContext_工具返回归档编号与位置(tmp_path: Path) -> None:
    store = ContextStore(tmp_path)
    record = store.archive([Message.user("需要检索的关键词 德尔塔")])
    registry = ToolRegistry()
    register_recall_context_tool(registry, store)

    result = registry.execute("recallContext", {"text": "德尔塔"})

    assert result.ok
    assert record.archive_id in result.content
    assert "第 0 条" in result.content
    assert "德尔塔" in result.content

    failure = registry.execute("recallContext", {"text": "x", "id": "../evil"})
    assert not failure.ok


def test_压缩先归档再替换上下文并追加归档说明(tmp_path: Path) -> None:
    agent, client = _agent(
        tmp_path,
        [
            ChatResponse(content="# 工作摘要\n用户正在完成任务 A。"),
            ChatResponse(content="继续完成"),
        ],
    )
    agent.set_messages(
        [
            Message.system("你是助手"),
            Message.user("请完成任务 A"),
            Message.assistant("任务 A 已完成"),
        ]
    )

    events = []
    result = agent.compact(events.append)

    assert isinstance(events[0], CompactionStarted)
    assert isinstance(events[-1], CompactionFinished)
    assert result.path.exists()
    assert result.path.parent == tmp_path
    assert len(result.path.read_text(encoding="utf-8").splitlines()) == 3
    assert client.tools == [None]

    assert len(agent.messages) == 2
    assert agent.messages[0].role == "system"
    assert "工作摘要" in agent.messages[1].content
    assert "此前会话压缩摘要" in agent.messages[1].content
    assert result.archive_id in agent.messages[1].content
    assert "recallContext" in agent.messages[1].content
    assert "请完成任务 A" in result.original_text
    assert "任务 A 已完成" in result.original_text
    assert agent.context_stats().needs_compaction is False
    assert agent.context_stats().used_tokens < 1_000

    assert agent.run("继续") == "继续完成"


def test_压缩失败保留原上下文但归档仍然存在(tmp_path: Path) -> None:
    agent, _ = _agent(tmp_path, [ChatResponse(content="")])
    agent.set_messages(
        [
            Message.system("你是助手"),
            Message.user("历史消息"),
        ]
    )
    before = [message.to_payload() for message in agent.messages]

    with pytest.raises(ContextError):
        agent.compact()

    assert [message.to_payload() for message in agent.messages] == before
    assert list(tmp_path.glob("*.jsonl"))


def test_达到阈值发出警告并阻止新的普通提示词(tmp_path: Path) -> None:
    agent, _ = _agent(
        tmp_path,
        [
            ChatResponse(
                content="完成",
                usage=TokenUsage(prompt_tokens=7_500, completion_tokens=500, total_tokens=8_000),
            )
        ],
        context_window=10_000,
        threshold=0.7,
    )

    events = []
    agent.run("触发一次响应", events.append)

    warnings = [event for event in events if isinstance(event, ContextWarning)]
    assert warnings
    assert "/compact" in warnings[0].message
    assert agent.compaction_required

    with pytest.raises(ContextCompactionRequired):
        agent.run("这条不应被接受")


def test_解析_API_返回的_token_usage() -> None:
    response = OpenAICompatibleClient._to_response(
        {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        }
    )
    assert response.usage is not None
    assert response.usage.prompt_tokens == 100
    assert response.usage.total_tokens == 150

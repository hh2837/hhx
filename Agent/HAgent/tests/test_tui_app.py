"""TUI 应用的集成测试（使用 Textual 的测试驱动与假的 LLM 客户端）。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Input, Markdown

from core import (
    Agent,
    AgentConfig,
    AppConfig,
    LLMConfig,
    StreamChunk,
    ToolRegistry,
    UIConfig,
)
from core.llm.client import LLMClient
from tui.app import XAgentApp
from tui.widgets import ChatView


class FakeClient(LLMClient):
    def __init__(self, scripts: list[list[StreamChunk]]) -> None:
        self.scripts = list(scripts)

    def stream_chat(self, messages, tools=None):
        script = self.scripts.pop(0) if self.scripts else []
        yield from script


def _build_app(scripts: list[list[StreamChunk]]) -> XAgentApp:
    config = AppConfig(
        llm=LLMConfig(model="test-model"),
        agent=AgentConfig(system_prompt="你是助手"),
        ui=UIConfig(theme="textual-dark", show_sidebar=True),
        workspace=Path.cwd(),
    )
    agent = Agent(
        client=FakeClient(scripts),
        tools=ToolRegistry(),
        config=config.agent,
    )
    return XAgentApp(config, agent=agent)


def _collect_texts(chat: ChatView) -> list[str]:
    texts: list[str] = []
    for child in chat.children:
        if isinstance(child, Markdown):
            texts.append(child.source)
        else:
            content = getattr(child, "content", "")
            texts.append(content if isinstance(content, str) else str(content))
    return texts


def test_应用能够启动并渲染欢迎信息() -> None:
    app = _build_app([])

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            chat = app.query_one(ChatView)
            assert any("欢迎使用 xAgent" in text for text in _collect_texts(chat))

    asyncio.run(scenario())


def test_提交问题会渲染用户消息与助手回答() -> None:
    app = _build_app([[StreamChunk(content="你好呀")]])

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one(Input).value = "嗨"
            await pilot.press("enter")

            for _ in range(100):
                await asyncio.sleep(0.05)
                if not app.is_busy:
                    break
            await pilot.pause()

            texts = _collect_texts(app.query_one(ChatView))
            assert any("嗨" in text for text in texts)
            assert any("你好呀" in text for text in texts)

    asyncio.run(scenario())


def test_新会话会清空界面() -> None:
    app = _build_app([[StreamChunk(content="你好呀")]])

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_new_session()
            await pilot.pause()
            texts = _collect_texts(app.query_one(ChatView))
            assert any("新会话" in text for text in texts)

    asyncio.run(scenario())

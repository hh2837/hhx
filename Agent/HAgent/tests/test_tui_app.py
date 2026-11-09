"""TUI 应用的集成测试（使用 Textual 的测试驱动与假的 LLM 客户端）。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Input, Markdown, Static

from core import (
    Agent,
    AgentConfig,
    AppConfig,
    ChatResponse,
    LLMConfig,
    Message,
    Session,
    SessionStore,
    ToolRegistry,
    UIConfig,
)
from core.llm.client import LLMClient
from tui.app import HAgentApp
from tui.widgets import (
    ChatView,
    CommandPalette,
    CompactionScreen,
    ConfigNoticeScreen,
    SessionResumeScreen,
    Sidebar,
)
from tui.widgets.status_bar import format_context


class FakeClient(LLMClient):
    def __init__(self, scripts: list[ChatResponse]) -> None:
        self.scripts = list(scripts)

    def chat(self, messages, tools=None):
        return self.scripts.pop(0) if self.scripts else ChatResponse()


def _build_app(
    scripts: list[ChatResponse],
    context_dir: Path | None = None,
    session_store: SessionStore | None = None,
    *,
    load_mcp: bool = False,
    config_notice: bool = False,
) -> HAgentApp:
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
        context_dir=context_dir,
    )
    return HAgentApp(
        config,
        agent=agent,
        load_mcp=load_mcp,
        config_notice=config_notice,
        session_store=session_store,
    )


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
            assert any("欢迎使用 HAgent" in text for text in _collect_texts(chat))

    asyncio.run(scenario())


def test_提交问题会渲染用户消息与助手回答() -> None:
    app = _build_app([ChatResponse(content="你好呀")])

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
    app = _build_app([ChatResponse(content="你好呀")])

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_new_session()
            await pilot.pause()
            texts = _collect_texts(app.query_one(ChatView))
            assert any("新会话" in text for text in texts)

    asyncio.run(scenario())


def test_状态栏上下文格式包含默认窗口标记() -> None:
    text = format_context(12_300, 128_000, 12_300 / 128_000, True)
    assert text == "12.3k / 128k（9.6%，默认）"


def test_compact_命令会压缩上下文(tmp_path: Path) -> None:
    app = _build_app(
        [
            ChatResponse(content="第一轮回答"),
            ChatResponse(content="# 摘要\n用户进行了第一轮对话。"),
        ],
        context_dir=tmp_path,
    )

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one(Input).value = "开始"
            await pilot.press("enter")
            for _ in range(100):
                await asyncio.sleep(0.05)
                if not app.is_busy:
                    break
            await pilot.pause()

            app.query_one(Input).value = "/compact"
            await pilot.press("enter")
            for _ in range(100):
                await asyncio.sleep(0.05)
                if not app.is_busy:
                    break
            await pilot.pause()

            texts = _collect_texts(app.query_one(ChatView))
            assert any("上下文压缩完成" in text for text in texts)
            assert list(tmp_path.glob("*.jsonl"))

            assert isinstance(app.screen, CompactionScreen)
            screen = app.screen
            assert "开始" in screen.original_text
            assert "第一轮回答" in screen.original_text
            assert "# 摘要" in screen.summary_text
            assert screen.query_one("#compaction-original-scroll")
            assert screen.query_one("#compaction-summary-scroll")

            await pilot.click("#close-compaction")
            await pilot.pause()
            assert not isinstance(app.screen, CompactionScreen)

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# 斜杠命令补全与分发
# ---------------------------------------------------------------------------


def test_输入斜杠会弹出补全面板() -> None:
    app = _build_app([])

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            prompt = app.query_one(Input)
            prompt.focus()
            prompt.value = "/ne"
            await pilot.pause()

            palette = app.query_one(CommandPalette)
            assert palette.visible
            assert palette.selected_command is not None
            assert palette.selected_command.name == "/new"

    asyncio.run(scenario())


def test_补全面板回车会执行命令() -> None:
    app = _build_app([])

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            prompt = app.query_one(Input)
            prompt.focus()
            prompt.value = "/help"
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            texts = _collect_texts(app.query_one(ChatView))
            assert any("可用命令" in text for text in texts)
            assert not app.query_one(CommandPalette).visible

    asyncio.run(scenario())


def test_未知命令会提示_help() -> None:
    app = _build_app([])

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            prompt = app.query_one(Input)
            prompt.value = "/不存在"
            await pilot.press("enter")
            await pilot.pause()
            texts = _collect_texts(app.query_one(ChatView))
            assert any("未知命令" in text for text in texts)

    asyncio.run(scenario())


def test_slash_status_显示状态() -> None:
    app = _build_app([])

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one(Input).value = "/status"
            await pilot.press("enter")
            await pilot.pause()
            texts = _collect_texts(app.query_one(ChatView))
            assert any("模型：test-model" in text for text in texts)
            assert any("消息数" in text for text in texts)

    asyncio.run(scenario())


def test_new_会先自动保存当前会话(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    app = _build_app(
        [ChatResponse(content="你好！"), ChatResponse(content="第二回答")],
        session_store=store,
    )

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one(Input).value = "第一条消息"
            await pilot.press("enter")
            for _ in range(100):
                await asyncio.sleep(0.05)
                if not app.is_busy:
                    break
            await pilot.pause()

            app.action_new_session()
            await pilot.pause()

            sessions = store.list_sessions()
            assert len(sessions) == 1
            assert any(m.content == "第一条消息" for m in sessions[0].messages)
            texts = _collect_texts(app.query_one(ChatView))
            assert any("已自动保存" in text for text in texts)

    asyncio.run(scenario())


def test_MCP_加载占位文案() -> None:
    app = _build_app([])

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            # 尚未加载完成 -> 显示加载中
            assert "正在加载 MCP" in app._render_mcp_text()
            # 加载完成但无可用 manager -> 显示未配置
            app._mcp_loaded = True
            assert "未配置" in app._render_mcp_text()

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# 配置缺失提示面板
# ---------------------------------------------------------------------------


def test_配置缺失时弹出提示面板() -> None:
    app = _build_app([], config_notice=True)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, ConfigNoticeScreen)
            await pilot.click("#config-notice-quit")
            await pilot.pause()

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# 会话恢复
# ---------------------------------------------------------------------------


def test_resume_列出并恢复会话(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    store.save(
        Session(
            title="我的会话",
            messages=[Message.system("你是助手"), Message.user("旧内容")],
        )
    )
    app = _build_app([], session_store=store)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_resume_session()
            await pilot.pause()
            assert isinstance(app.screen, SessionResumeScreen)
            await pilot.press("enter")
            await pilot.pause()
            texts = _collect_texts(app.query_one(ChatView))
            assert any("已恢复会话" in text for text in texts)
            assert "旧内容" in [m.content for m in app.agent.messages]

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# MCP 侧边栏
# ---------------------------------------------------------------------------


def test_MCP_侧边栏展示服务器与工具() -> None:
    from core import MCPClientManager, MCPServerConfig, MCPToolInfo

    app = _build_app([])

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            manager = MCPClientManager({})  # 无服务器，不启动线程
            manager._servers = {
                "pet-hospital": MCPServerConfig(name="pet-hospital", url="http://127.0.0.1:8000/mcp")
            }
            manager._tools = {
                "pet-hospital": [MCPToolInfo(name="list_pets", description="列出宠物", parameters={})]
            }
            app._mcp_manager = manager
            app._refresh_sidebar()
            await pilot.pause()
            mcp_info = app.query_one("#mcp-info", Static).content
            assert "pet-hospital" in str(mcp_info)
            assert "list_pets" in str(mcp_info)

    asyncio.run(scenario())

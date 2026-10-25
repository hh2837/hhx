"""xAgent 的 Textual 终端界面。

界面层只做三件事：
1. 采集用户输入；
2. 把核心层事件渲染成组件状态；
3. 管理与核心层无关的界面交互（清屏、保存会话……）。

所有业务逻辑都在 :mod:`core` 中完成，这里不出现任何模型调用或工具执行的代码。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header, Input

from core import Agent, AppConfig, Session, SessionStore, ToolCall, build_agent

from .controller import ChatController
from .theme import APP_CSS
from .widgets import ChatView, PromptInput, Sidebar, StatusBar

logger = logging.getLogger(__name__)

SESSION_DIRNAME = Path(".xagent") / "sessions"


class XAgentApp(App[None]):
    """xAgent 终端界面。"""

    CSS = APP_CSS
    TITLE = "xAgent"
    SUB_TITLE = "Terminal Agent"

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+q", "quit", "退出"),
        Binding("ctrl+n", "new_session", "新会话"),
        Binding("ctrl+s", "save_session", "保存会话"),
        Binding("ctrl+l", "clear_transcript", "清屏"),
    ]

    def __init__(
        self,
        config: AppConfig,
        agent: Agent | None = None,
        session_store: SessionStore | None = None,
    ) -> None:
        super().__init__()
        self._config = config
        self._agent = agent or build_agent(config)
        self._session_store = session_store or SessionStore(config.workspace / SESSION_DIRNAME)
        self._controller = ChatController(self._agent, self)
        self._busy = False

    # ------------------------------------------------------------------ 状态

    @property
    def is_busy(self) -> bool:
        """当前是否有对话正在执行。"""
        return self._busy

    @property
    def agent(self) -> Agent:
        return self._agent

    # ------------------------------------------------------------------ 布局

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            yield ChatView(id="chat")
            if self._config.ui.show_sidebar:
                yield Sidebar(id="sidebar")
        with Horizontal(id="prompt-area"):
            yield PromptInput()
        yield StatusBar(
            model=self._config.llm.model or "(未配置)",
            workspace=str(self._config.workspace),
            id="status",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._apply_theme()
        self.query_one(PromptInput).focus()
        self._refresh_sidebar()
        self.query_one(ChatView).add_info(
            "欢迎使用 xAgent！输入问题后回车发送；Ctrl+Q 退出，Ctrl+N 新会话，Ctrl+S 保存会话。"
        )

    # ------------------------------------------------------------------ 交互

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """用户提交输入：在后台线程中驱动一次对话。"""
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if self._busy:
            self.query_one(ChatView).add_info("上一轮还在进行中，请稍候…")
            return
        self._busy = True
        self.query_one(PromptInput).disabled = True
        self.run_worker(lambda: self._run_turn(text), group="chat", thread=True, exit_on_error=False)

    def action_new_session(self) -> None:
        """开始一个新会话。"""
        self._controller.reset()
        self._refresh_sidebar()
        self.query_one(ChatView).add_info("已开启新会话。")

    def action_save_session(self) -> None:
        """把当前会话保存到磁盘。"""
        session = Session(title="TUI 会话", messages=self._agent.messages)
        path = self._session_store.save(session)
        self.query_one(ChatView).add_info(f"会话已保存：{path}")

    def action_clear_transcript(self) -> None:
        """只清空界面，不影响历史。"""
        self.query_one(ChatView).clear()
        self.query_one(ChatView).add_info("界面已清空（历史仍保留）。")

    # ------------------------------------------------------------------ 运行

    def _run_turn(self, text: str) -> None:
        """在工作线程中执行一次完整对话。"""
        try:
            self._controller.submit(text)
        except Exception as exc:  # noqa: BLE001 - 任何异常都要反馈到界面
            self.show_error(f"{type(exc).__name__}: {exc}")
        finally:
            self._dispatch(self._finish_turn)

    def _finish_turn(self) -> None:
        self._busy = False
        self.query_one(PromptInput).disabled = False
        self.query_one(PromptInput).focus()
        self._refresh_sidebar()

    # ------------------------------------------------------------------ 视图端口

    # 以下方法实现 core 无关的 ChatViewPort 协议：核心层事件 → 界面动作。

    def show_user_message(self, text: str) -> None:
        self._dispatch(lambda: self.query_one(ChatView).add_user_message(text))

    def start_assistant_message(self) -> None:
        self._dispatch(lambda: self.query_one(ChatView).start_assistant_message())

    def append_assistant_delta(self, text: str) -> None:
        self._dispatch(lambda: self.query_one(ChatView).append_assistant_delta(text))

    def finish_assistant_message(self, text: str) -> None:
        self._dispatch(lambda: self.query_one(ChatView).finish_assistant_message(text))

    def show_tool_call(self, call: ToolCall) -> None:
        self._dispatch(lambda: self.query_one(ChatView).add_tool_call(call))
        self._dispatch(lambda: self._log_tool(f"→ {call.name}({call.arguments})"))

    def show_tool_result(self, call: ToolCall, ok: bool, output: str) -> None:
        self._dispatch(lambda: self.query_one(ChatView).add_tool_result(call, ok, output))
        state = "成功" if ok else "失败"
        preview = output.strip().splitlines()[0] if output.strip() else ""
        self._dispatch(lambda: self._log_tool(f"← {call.name} {state}：{preview}"))

    def show_error(self, message: str, detail: str = "") -> None:
        text = message if not detail else f"{message}\n{detail}"
        self._dispatch(lambda: self.query_one(ChatView).add_error(text))

    def set_status(self, status: str) -> None:
        self._dispatch(lambda: self.query_one(StatusBar).set_status(status))

    def clear_transcript(self) -> None:
        self._dispatch(lambda: self.query_one(ChatView).clear())

    # ------------------------------------------------------------------ 内部

    def _dispatch(self, func: Callable[[], None]) -> None:
        """把界面更新调度到 UI 线程执行（Agent 在工作线程中运行）。"""
        if getattr(self, "_thread_id", 0) == threading.get_ident():
            func()
            return
        try:
            self.call_from_thread(func)
        except Exception:
            logger.debug("界面调度失败（应用可能正在退出）", exc_info=True)

    def _apply_theme(self) -> None:
        theme = self._config.ui.theme
        if not theme:
            return
        try:
            self.theme = theme
        except Exception:
            logger.warning("主题 %s 不可用，使用默认主题", theme, exc_info=True)

    def _refresh_sidebar(self) -> None:
        if not self._config.ui.show_sidebar:
            return
        try:
            sidebar = self.query_one(Sidebar)
        except Exception:  # noqa: BLE001 - 侧边栏可能被禁用
            return
        tools = ", ".join(self._agent.tools.names())
        info = (
            f"模型：{self._config.llm.model or '(未配置)'}\n"
            f"工作目录：{self._config.workspace}\n"
            f"消息数：{len(self._agent.messages)}\n"
            f"工具：{tools}"
        )
        sidebar.update_session_info(info)

    def _log_tool(self, text: str) -> None:
        if not self._config.ui.show_sidebar:
            return
        try:
            self.query_one(Sidebar).log(text)
        except Exception:
            logger.debug("工具日志写入失败", exc_info=True)


def create_app(config: AppConfig | None = None) -> XAgentApp:
    """创建 TUI 应用实例。"""
    from core import ConfigLoader

    config = config or ConfigLoader().load()
    return XAgentApp(config)


__all__ = ["XAgentApp", "create_app"]

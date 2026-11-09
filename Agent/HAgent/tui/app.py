"""HAgent 的 Textual 终端界面。

界面层只做三件事：
1. 采集用户输入（含斜杠命令补全与分发）；
2. 把核心层事件渲染成组件状态；
3. 管理与核心层无关的界面交互（清屏、保存/恢复会话、异步加载 MCP……）。

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
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input

from core import (
    Agent,
    AppConfig,
    CompactionResult,
    Session,
    SessionStore,
    ToolCall,
    build_agent,
    build_mcp_tools,
    format_token_count,
)

from .commands import command_help_text, match_commands, resolve_command
from .controller import ChatController
from .theme import APP_CSS
from .widgets import (
    ChatView,
    CommandPalette,
    CompactionScreen,
    ConfigNoticeScreen,
    PromptInput,
    SessionResumeScreen,
    Sidebar,
    StatusBar,
)

logger = logging.getLogger(__name__)

SESSION_DIRNAME = Path(".hagent") / "sessions"


def _derive_session_title(messages) -> str:
    """从会话消息中抽取一个人类可读的标题。"""
    for message in messages:
        if message.role == "user":
            text = message.content.strip().replace("\n", " ")
            return text[:32] or "新会话"
    return "新会话"


class HAgentApp(App[None]):
    """HAgent 终端界面。"""

    CSS = APP_CSS
    TITLE = "HAgent"
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
        *,
        load_mcp: bool = True,
        config_notice: bool = False,
    ) -> None:
        super().__init__()
        self._config = config
        # 先不阻塞地构建 Agent（不含 MCP），MCP 由后台线程异步加载。
        self._agent = agent or build_agent(config, load_mcp=False)
        self._session_store = session_store or SessionStore(self._resolve_session_dir(config))
        self._controller = ChatController(self._agent, self)
        self._busy = False
        self._load_mcp = load_mcp
        self._config_notice = config_notice
        self._mcp_manager = None
        self._mcp_loaded = False

    @staticmethod
    def _resolve_session_dir(config: AppConfig) -> Path:
        raw = Path(config.ui.session_dir) if config.ui.session_dir else SESSION_DIRNAME
        if raw.is_absolute():
            return raw
        return config.workspace / raw

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
            yield ChatView(tool_output_limit=self._config.ui.tool_output_limit, id="chat")
            if self._config.ui.show_sidebar:
                yield Sidebar(id="sidebar")
        with Vertical(id="prompt-area"):
            yield CommandPalette(limit=self._config.ui.command_palette_limit)
            yield PromptInput()
        yield StatusBar(
            model=self._config.llm.model or "(未配置)",
            workspace=str(self._config.workspace),
            id="status",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._apply_theme()
        self._apply_ui_config()
        self.query_one(PromptInput).focus()
        self._refresh_sidebar()
        self._refresh_context_status()
        self.query_one(ChatView).add_info(
            "欢迎使用 HAgent！输入问题后回车发送；输入 / 查看命令补全；"
            "Ctrl+Q 退出，Ctrl+N 新会话，Ctrl+S 保存会话。"
        )
        if self._agent.agents_md_injected:
            self.query_one(ChatView).add_info("已注入项目约定 AGENTS.md，后续轮次自动复用。")

        if self._config_notice:
            self.push_screen(
                ConfigNoticeScreen(
                    config_path=str(self._config.config_path or self._config.workspace / "config.ini")
                )
            )
            return

        if self._load_mcp:
            self.query_one(Sidebar).update_mcp("（正在加载 MCP…）")
            self.run_worker(self._load_mcp_async, group="mcp", thread=True, exit_on_error=False)

    # ------------------------------------------------------------------ 交互

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """用户提交输入：优先解析斜杠命令，否则在后台线程中驱动一次对话。"""
        text = event.value.strip()
        event.input.value = ""
        self.query_one(CommandPalette).hide()
        self.query_one(PromptInput).set_completion_active(False)
        if not text:
            return

        command = resolve_command(text)
        if command is not None:
            if self._busy and command.name == "/compact":
                self.query_one(ChatView).add_info("上一轮还在进行中，请稍候…")
                return
            if self._dispatch_command(command.name):
                return

        if self._busy:
            self.query_one(ChatView).add_info("上一轮还在进行中，请稍候…")
            return
        if text.startswith("/"):
            self.query_one(ChatView).add_info("未知命令。输入 /help 查看全部命令。")
            return

        if self._agent.compaction_required:
            stats = self._agent.context_stats()
            self._refresh_context_status()
            self.query_one(ChatView).add_warning(
                f"上下文已使用 {format_token_count(stats.used_tokens)} / "
                f"{format_token_count(stats.window_tokens)}（{stats.ratio * 100:.1f}%），"
                "请先执行 /compact 压缩上下文后再继续。"
            )
            return

        self._busy = True
        self.query_one(PromptInput).disabled = True
        self.run_worker(lambda: self._run_turn(text), group="chat", thread=True, exit_on_error=False)

    def on_input_changed(self, event: Input.Changed) -> None:
        """输入内容变化时刷新命令补全面板。"""
        self._update_completion(event.value)

    def on_prompt_input_completion_key(self, event: PromptInput.CompletionKey) -> None:
        """补全面板打开时的导航按键：↑↓ 选择、Tab 补全、回车执行、Esc 关闭。"""
        palette = self.query_one(CommandPalette)
        if not palette.visible:
            return
        prompt = self.query_one(PromptInput)
        key = event.key
        if key == "up":
            palette.select_previous()
        elif key == "down":
            palette.select_next()
        elif key == "tab":
            command = palette.selected_command
            if command is not None:
                prompt.value = command.name
                prompt.cursor_position = len(prompt.value)
                prompt.focus()
        elif key == "enter":
            command = palette.selected_command
            palette.hide()
            prompt.set_completion_active(False)
            prompt.value = ""
            if command is not None:
                self._dispatch_command(command.name)
            prompt.focus()
        elif key == "escape":
            palette.hide()
            prompt.set_completion_active(False)
            prompt.focus()

    # ------------------------------------------------------------------ 命令

    def _update_completion(self, value: str) -> None:
        palette = self.query_one(CommandPalette)
        prompt = self.query_one(PromptInput)
        matches = match_commands(value, limit=self._config.ui.command_palette_limit)
        if matches:
            palette.show_commands(matches)
            prompt.set_completion_active(True)
        else:
            palette.hide()
            prompt.set_completion_active(False)

    def _dispatch_command(self, name: str) -> bool:
        """按命令名分发到对应动作；未知命令返回 ``False``。"""
        if name == "/new":
            self.action_new_session()
        elif name == "/resume":
            self.action_resume_session()
        elif name == "/save":
            self.action_save_session()
        elif name == "/compact":
            self._start_compaction()
        elif name == "/status":
            self.action_show_status()
        elif name == "/clear":
            self.action_clear_transcript()
        elif name == "/help":
            self.action_show_help()
        elif name == "/quit":
            self.exit()
        else:
            return False
        return True

    def action_new_session(self) -> None:
        """开始一个新会话；新建前先自动保存当前会话历史。"""
        saved = self._save_current_session()
        self._controller.reset()
        self._refresh_sidebar()
        self._refresh_context_status()
        if saved is not None:
            self.query_one(ChatView).add_info(f"当前会话已自动保存：{saved}")
        if self._agent.agents_md_injected:
            self.query_one(ChatView).add_info("已开启新会话。项目约定 AGENTS.md 已重新注入。")
        else:
            self.query_one(ChatView).add_info("已开启新会话。")

    def action_save_session(self) -> None:
        """把当前会话保存到磁盘。"""
        path = self._save_current_session()
        if path is None:
            self.query_one(ChatView).add_info("当前没有可保存的对话内容。")
        else:
            self.query_one(ChatView).add_info(f"会话已保存：{path}")

    def _save_current_session(self) -> Path | None:
        """把当前会话保存到磁盘；没有用户消息时返回 ``None``。"""
        messages = self._agent.messages
        if not any(message.role == "user" for message in messages):
            return None
        title = _derive_session_title(messages)
        return self._session_store.save(Session(title=title, messages=messages))

    def action_resume_session(self) -> None:
        """打开历史会话选择面板。"""
        sessions = self._session_store.list_sessions()
        self.push_screen(SessionResumeScreen(sessions), self._on_resume_result)

    def action_show_status(self) -> None:
        """查看模型、上下文与会话状态。"""
        stats = self._agent.context_stats()
        tools = ", ".join(self._agent.tools.names()) or "（无）"
        default_note = "（默认）" if stats.window_is_default else ""
        text = (
            f"模型：{self._config.llm.model or '(未配置)'}\n"
            f"工作目录：{self._config.workspace}\n"
            f"消息数：{len(self._agent.messages)}\n"
            f"上下文：{format_token_count(stats.used_tokens)} / "
            f"{format_token_count(stats.window_tokens)}（{stats.ratio * 100:.1f}%{default_note}）\n"
            f"工具（{len(self._agent.tools)}）：{tools}\n"
            f"会话目录：{self._session_store.directory}"
        )
        self.query_one(ChatView).add_info(text)

    def action_show_help(self) -> None:
        """展示全部命令说明。"""
        self.query_one(ChatView).add_info(command_help_text())

    def action_clear_transcript(self) -> None:
        """只清空界面，不影响历史。"""
        self.query_one(ChatView).clear()
        self.query_one(ChatView).add_info("界面已清空（历史仍保留）。")

    # ------------------------------------------------------------------ 会话恢复

    def _on_resume_result(self, session: Session | None) -> None:
        if session is None:
            return
        try:
            self._agent.set_messages(session.messages)
        except Exception as exc:  # noqa: BLE001 - 任何异常都要反馈到界面
            self.show_error(f"恢复会话失败：{type(exc).__name__}: {exc}")
            return
        self._busy = False
        self.query_one(PromptInput).disabled = False
        self.query_one(ChatView).clear()
        self.query_one(ChatView).add_info(
            f"已恢复会话「{session.title}」（{len(session.messages)} 条消息）。"
        )
        self._refresh_sidebar()
        self._refresh_context_status()
        self.query_one(PromptInput).focus()

    # ------------------------------------------------------------------ MCP（异步加载）

    def _load_mcp_async(self) -> None:
        """在后台线程连接 MCP Server 并把工具注册到 Agent，随后刷新侧边栏。"""
        try:
            manager = build_mcp_tools(self._config, self._agent.tools)
        except Exception as exc:  # noqa: BLE001 - MCP 失败不影响主流程
            logger.warning("MCP 异步加载失败：%s", exc)
            manager = None
        self._mcp_manager = manager
        self._mcp_loaded = True
        self._dispatch(self._refresh_mcp_sidebar)
        self._dispatch(self._refresh_sidebar)

    def _render_mcp_text(self) -> str:
        manager = self._mcp_manager
        if manager is not None:
            if not manager.servers:
                return "（.mcp.json 中未配置任何服务器）"
            lines: list[str] = []
            for server, tools in manager.tools.items():
                names = ", ".join(tool.name for tool in tools) or "（无工具）"
                lines.append(f"● {server}（{len(tools)}）: {names}")
            for server, error in manager.errors.items():
                lines.append(f"⚠ {server}: {error}")
            return "\n".join(lines)
        if not self._mcp_loaded:
            return "（正在加载 MCP…）"
        return "（未配置 .mcp.json，或加载失败）"

    # ------------------------------------------------------------------ 运行

    def _run_turn(self, text: str) -> None:
        """在工作线程中执行一次完整对话。"""
        try:
            self._controller.submit(text)
        except Exception as exc:  # noqa: BLE001 - 任何异常都要反馈到界面
            self.show_error(f"{type(exc).__name__}: {exc}")
        finally:
            self._dispatch(self._finish_turn)

    def _start_compaction(self) -> None:
        """启动一次上下文压缩（压缩期间禁用其他交互）。"""
        self._busy = True
        self.query_one(PromptInput).disabled = True
        self.query_one(ChatView).add_info("开始压缩上下文，正在归档原始记录并生成摘要…")
        self.run_worker(
            self._run_compaction,
            group="compact",
            thread=True,
            exit_on_error=False,
        )

    def _run_compaction(self) -> None:
        """在工作线程中执行上下文压缩。"""
        try:
            self._controller.compact()
        except Exception as exc:  # noqa: BLE001 - 任何异常都要反馈到界面
            self.show_error(f"上下文压缩失败：{type(exc).__name__}: {exc}")
        finally:
            self._dispatch(self._finish_turn)

    def _finish_turn(self) -> None:
        self._busy = False
        self.query_one(PromptInput).disabled = False
        if not isinstance(self.screen, CompactionScreen):
            self.query_one(PromptInput).focus()
        self._refresh_sidebar()
        self._refresh_context_status()

    # ------------------------------------------------------------------ 视图端口

    # 以下方法实现 core 无关的 ChatViewPort 协议：核心层事件 → 界面动作。

    def show_user_message(self, text: str) -> None:
        self._dispatch(lambda: self.query_one(ChatView).add_user_message(text))

    def start_assistant_message(self) -> None:
        self._dispatch(lambda: self.query_one(ChatView).start_assistant_message())

    def finish_assistant_message(self, text: str) -> None:
        self._dispatch(lambda: self.query_one(ChatView).finish_assistant_message(text))
        self._dispatch(self._refresh_context_status)

    def show_tool_call(self, call: ToolCall) -> None:
        self._dispatch(lambda: self.query_one(ChatView).add_tool_call(call))
        self._dispatch(lambda: self._log_tool(f"→ {call.name}({call.arguments})"))

    def show_tool_result(self, call: ToolCall, ok: bool, output: str) -> None:
        self._dispatch(lambda: self.query_one(ChatView).add_tool_result(call, ok, output))
        state = "成功" if ok else "失败"
        preview = output.strip().splitlines()[0] if output.strip() else ""
        self._dispatch(lambda: self._log_tool(f"← {call.name} {state}：{preview}"))
        self._dispatch(self._refresh_context_status)

    def show_error(self, message: str, detail: str = "") -> None:
        text = message if not detail else f"{message}\n{detail}"
        self._dispatch(lambda: self.query_one(ChatView).add_error(text))

    def show_warning(self, message: str) -> None:
        self._dispatch(lambda: self.query_one(ChatView).add_warning(message))
        self._dispatch(self._refresh_context_status)

    def show_info(self, message: str) -> None:
        self._dispatch(lambda: self.query_one(ChatView).add_info(message))

    def show_compaction_result(self, result: CompactionResult) -> None:
        self._dispatch(
            lambda: self.push_screen(
                CompactionScreen(
                    original_text=result.original_text,
                    summary_text=result.summary,
                    archive_id=result.archive_id,
                    archive_path=str(result.path),
                    message_count=result.message_count,
                )
            )
        )

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

    def _apply_ui_config(self) -> None:
        """把 config.ini 中的界面参数真正应用到控件。"""
        if self._config.ui.show_sidebar:
            try:
                self.query_one(Sidebar).styles.width = self._config.ui.sidebar_width
            except Exception:  # noqa: BLE001 - 侧边栏可能尚未就绪
                logger.debug("应用侧边栏宽度失败", exc_info=True)

    def _refresh_context_status(self) -> None:
        """把核心层的上下文统计刷新到状态栏。"""
        try:
            status_bar = self.query_one(StatusBar)
        except Exception:  # noqa: BLE001 - 应用尚未挂载完成
            return
        stats = self._agent.context_stats()
        status_bar.set_context(
            used_tokens=stats.used_tokens,
            window_tokens=stats.window_tokens,
            ratio=stats.ratio,
            window_is_default=stats.window_is_default,
            needs_compaction=stats.needs_compaction,
        )

    def _refresh_sidebar(self) -> None:
        if not self._config.ui.show_sidebar:
            return
        try:
            sidebar = self.query_one(Sidebar)
        except Exception:  # noqa: BLE001 - 侧边栏可能被禁用
            return
        tools = ", ".join(self._agent.tools.names())
        stats = self._agent.context_stats()
        default_note = "（默认）" if stats.window_is_default else ""
        info = (
            f"模型：{self._config.llm.model or '(未配置)'}\n"
            f"工作目录：{self._config.workspace}\n"
            f"消息数：{len(self._agent.messages)}\n"
            f"上下文：{format_token_count(stats.used_tokens)} / "
            f"{format_token_count(stats.window_tokens)}"
            f"（{stats.ratio * 100:.1f}%{default_note}）\n"
            f"工具：{tools}"
        )
        sidebar.update_session_info(info)
        sidebar.update_mcp(self._render_mcp_text())

    def _refresh_mcp_sidebar(self) -> None:
        if not self._config.ui.show_sidebar:
            return
        try:
            self.query_one(Sidebar).update_mcp(self._render_mcp_text())
        except Exception:  # noqa: BLE001 - 侧边栏可能被禁用
            logger.debug("刷新 MCP 侧边栏失败", exc_info=True)

    def _log_tool(self, text: str) -> None:
        if not self._config.ui.show_sidebar:
            return
        try:
            self.query_one(Sidebar).log(text)
        except Exception:
            logger.debug("工具日志写入失败", exc_info=True)


def create_app(config: AppConfig | None = None, *, load_mcp: bool = True) -> HAgentApp:
    """创建 TUI 应用实例。"""
    from core import ConfigLoader

    config = config or ConfigLoader().load()
    return HAgentApp(config, load_mcp=load_mcp)


__all__ = ["HAgentApp", "create_app"]

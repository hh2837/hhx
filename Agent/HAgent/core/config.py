"""配置层：把外部配置（ini / 环境变量 / .env）转换成强类型配置对象。

配置优先级（数值越大优先级越高）::

    内置默认值  <  config.ini  <  环境变量  <  .env 文件

设计约束：本模块不依赖任何 UI 框架，前端可以自由选择如何加载配置。
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .errors import ConfigError, ToolExecutionError

DEFAULT_CONFIG_FILENAME = "config.ini"
DEFAULT_ENV_FILENAME = ".env"
DEFAULT_AGENTS_FILENAME = "AGENTS.md"

ENV_CONFIG_PATH = "HAGENT_CONFIG"
ENV_WORKSPACE = "HAGENT_WORKSPACE"
ENV_THEME = "HAGENT_THEME"

DEFAULT_SYSTEM_PROMPT = (
    "你是一个命令行助手，拥有本地文件系统与时间相关的工具能力。"
    "回答要简洁、准确，必要时主动调用工具获取真实信息，不要臆造。"
)

DEFAULT_CONFIG_TEMPLATE = """\
; HAgent 默认配置（自动生成）
; 请按需修改本文件，修改后重启程序生效。
; 环境变量优先级高于本文件，敏感信息建议通过 HAGENT_LLM_API_KEY 注入。

[LLM]
; OpenAI 兼容接口地址（LM Studio / Ollama / vLLM / DeepSeek …）
base_url = http://localhost:1234/v1
api_key =
; 示例模型名，请替换为真实可用的模型
model = mock-model
timeout = 120
temperature = 0.7
; 模型上下文窗口大小（Token）。留空或 0 表示未知，界面按 128k 显示并标注「默认」
context_window =

[Agent]
system_prompt = 你是一个命令行助手，拥有本地文件系统与时间相关的工具能力。回答要简洁、准确，必要时主动调用工具获取真实信息，不要臆造。
max_tool_rounds = 8
max_history_messages = 200
; 上下文使用比例达到该值时提示执行 /compact
compact_threshold = 0.7
; 压缩摘要的目标 Token 数
compact_target_tokens = 5000
; 无法从模型服务获得窗口大小时使用的默认上下文窗口
default_context_window = 128000
; 原始上下文归档目录（相对工作目录）
archive_dirname = .agents/context
; recallContext 单次最多返回的片段数
max_search_results = 8
; recallContext 每个片段的字符数
snippet_chars = 400
; 项目约定文件名；存在时会在新会话首次加载时注入一次
agents_file = AGENTS.md
; AGENTS.md 最大读取字节数，超出部分会截断
agents_max_bytes = 200000

[Filesystem]
; 留空表示以工作目录（workspace）为沙箱根目录；填绝对路径则限制在该目录内
root =
encoding = utf-8
max_read_bytes = 512000

[UI]
theme = textual-dark
show_sidebar = true
sidebar_width = 42
; 会话文件目录（相对工作目录；也可填写绝对路径）
session_dir = .hagent/sessions
; 工具输出在对话区最多展示的字符数
tool_output_limit = 800
; 斜杠命令补全面板最多展示的条目数
command_palette_limit = 8

[MCP]
; MCP Server 配置文件（相对工作目录）
config_file = .mcp.json
; 未在 .mcp.json 中单独指定时的连接超时（秒）
default_timeout = 30
; 暴露给模型的 MCP 工具名最大长度
max_tool_name_length = 64

[search]
baidu_api_key =
"""


@dataclass(frozen=True, slots=True)
class LLMConfig:
    """大模型服务配置。"""

    base_url: str = "http://localhost:1234/v1"
    api_key: str = ""
    model: str = ""
    timeout: float = 120.0
    temperature: float = 0.7
    context_window: int = 0
    """模型上下文窗口大小（Token）。0 表示未知，运行时按 128k 处理并标注「默认」。"""

    @property
    def chat_completions_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"


@dataclass(frozen=True, slots=True)
class AgentConfig:
    """Agent 编排配置。"""

    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    max_tool_rounds: int = 8
    max_history_messages: int = 200
    compact_threshold: float = 0.7
    """上下文使用比例达到该值时提示并阻止新的普通输入。"""
    compact_target_tokens: int = 5_000
    """压缩摘要的目标 Token 数。"""
    default_context_window: int = 128_000
    """无法获得模型窗口大小时使用的默认窗口（Token）。"""
    archive_dirname: str = ".agents/context"
    """原始上下文归档目录（相对于工作区）。"""
    max_search_results: int = 8
    """recallContext 单次最多返回的片段数。"""
    snippet_chars: int = 400
    """recallContext 每个片段展示的字符数。"""
    agents_file: str = DEFAULT_AGENTS_FILENAME
    """项目约定文件名；存在时在新会话首次加载时注入一次。"""
    agents_max_bytes: int = 200_000
    """读取 AGENTS 文件的最大字节数。"""


@dataclass(frozen=True, slots=True)
class FilesystemConfig:
    """文件系统工具配置。

    ``root`` 为沙箱根目录；为 ``None`` 表示不限制路径（谨慎使用）。
    """

    root: Path | None = None
    encoding: str = "utf-8"
    max_read_bytes: int = 512_000

    def resolve(self, path: str | os.PathLike[str]) -> Path:
        """把相对路径解析为绝对路径，并校验是否落在沙箱内。"""
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            base = self.root if self.root is not None else Path.cwd()
            candidate = base / candidate
        candidate = Path(os.path.normpath(candidate))
        if self.root is None:
            return candidate
        root = Path(os.path.normpath(self.root))
        if candidate != root and root not in candidate.parents:
            raise ToolExecutionError(f"路径超出允许的根目录 {root}：{candidate}")
        return candidate


@dataclass(frozen=True, slots=True)
class UIConfig:
    """界面配置（核心层只保留与业务相关的少数几项）"""

    theme: str = "textual-dark"
    show_sidebar: bool = True
    sidebar_width: int = 42
    session_dir: str = ".hagent/sessions"
    """会话文件目录（相对于工作区，或绝对路径）。"""
    tool_output_limit: int = 800
    """工具输出在对话区最多展示的字符数。"""
    command_palette_limit: int = 8
    """斜杠命令补全面板最多展示的条目数。"""


@dataclass(frozen=True, slots=True)
class MCPConfig:
    """MCP 客户端配置。"""

    config_file: str = ".mcp.json"
    default_timeout: float = 30.0
    max_tool_name_length: int = 64


@dataclass(frozen=True, slots=True)
class SearchConfig:
    """搜索配置"""

    baidu_api_key: str = ""


@dataclass(frozen=True, slots=True)
class AppConfig:
    """应用总配置"""

    llm: LLMConfig = LLMConfig()
    agent: AgentConfig = AgentConfig()
    filesystem: FilesystemConfig = FilesystemConfig()
    ui: UIConfig = UIConfig()
    mcp: MCPConfig = MCPConfig()
    search: SearchConfig = SearchConfig()
    workspace: Path = field(default_factory=Path.cwd)
    config_path: Path | None = None

    @property
    def sandbox_root(self) -> Path:
        """文件工具实际使用的沙箱根目录。

        优先使用配置中显式指定的根目录，否则以工作目录为准。
        """
        return self.filesystem.root or self.workspace

    def with_workspace(self, workspace: Path) -> AppConfig:
        """派生一个以指定目录作为工作区的新配置。"""
        return replace(self, workspace=Path(workspace).resolve())


# dataclass(slots=True) 的类属性是 slot 描述符而非默认值，这里统一取实例作为默认值来源。
_DEFAULTS_LLM = LLMConfig()
_DEFAULTS_AGENT = AgentConfig()
_DEFAULTS_FILESYSTEM = FilesystemConfig()
_DEFAULTS_UI = UIConfig()
_DEFAULTS_MCP = MCPConfig()
_DEFAULTS_SEARCH = SearchConfig()


@dataclass(frozen=True, slots=True)
class ConfigLoader:
    """配置加载器。

    使用示例::

        config = ConfigLoader().load()

    默认情况下，配置文件不存在时会自动创建一份完整的示例配置。
    """

    config_path: Path | None = None
    env_file: Path | None = None
    auto_create: bool = True

    @staticmethod
    def project_root() -> Path:
        """HAgent 项目根目录（core 包的上一级）。"""
        return Path(__file__).resolve().parent.parent

    @classmethod
    def default_config_path(cls) -> Path:
        """默认配置文件位于当前运行目录下（在哪运行就在哪生成/读取 config.ini）。"""
        return Path.cwd() / DEFAULT_CONFIG_FILENAME

    def resolve_config_path(self) -> Path | None:
        if self.config_path is not None:
            return Path(self.config_path)
        env_path = os.environ.get(ENV_CONFIG_PATH)
        if env_path:
            return Path(env_path)
        default = self.default_config_path()
        return default if default.exists() else None

    def target_config_path(self) -> Path:
        """返回即将读取 / 创建的配置文件路径。"""
        if self.config_path is not None:
            return Path(self.config_path)
        env_path = os.environ.get(ENV_CONFIG_PATH)
        if env_path:
            return Path(env_path)
        return self.default_config_path()

    def ensure_config_file(self) -> Path | None:
        """配置文件不存在时创建默认模板，返回创建出的路径。"""
        path = self.target_config_path()
        if path.exists():
            return None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(DEFAULT_CONFIG_TEMPLATE, encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"无法创建默认配置文件：{path}（{exc}）") from exc
        return path

    def load(self) -> AppConfig:
        """加载配置并返回 :class:`AppConfig`。"""
        if self.auto_create:
            self.ensure_config_file()
        env_values = self._load_env_file()
        parser = configparser.ConfigParser(interpolation=None)
        config_path = self.resolve_config_path()
        if config_path is not None and Path(config_path).exists():
            try:
                parser.read(Path(config_path), encoding="utf-8")
            except configparser.Error as exc:  # pragma: no cover - 依赖具体异常
                raise ConfigError(f"配置文件解析失败：{config_path}（{exc}）") from exc

        llm = self._build_llm(parser, env_values)
        agent = self._build_agent(parser, env_values)
        filesystem = self._build_filesystem(parser, env_values)
        ui = self._build_ui(parser, env_values)
        mcp = self._build_mcp(parser, env_values)
        search = self._build_search(parser, env_values)

        workspace = Path(
            env_values.get("workspace") or parser.get("Agent", "workspace", fallback="") or Path.cwd()
        ).expanduser()

        config = AppConfig(
            llm=llm,
            agent=agent,
            filesystem=filesystem,
            ui=ui,
            mcp=mcp,
            search=search,
            workspace=workspace.resolve(),
            config_path=Path(config_path) if config_path else self.target_config_path(),
        )
        return config

    # ------------------------------------------------------------------ 内部实现

    def _load_env_file(self) -> dict[str, str]:
        """读取 .env 文件（简单的 KEY=VALUE 解析，不引入额外依赖）。"""
        path = self.env_file or (self.project_root() / DEFAULT_ENV_FILENAME)
        if not path or not Path(path).exists():
            return {}
        values: dict[str, str] = {}
        for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip().strip('"').strip("'")
            values[key.strip()] = value
        return values

    @staticmethod
    def _env(env_values: dict[str, str], key: str) -> str | None:
        """环境变量优先于 .env 文件。"""
        if key in os.environ:
            return os.environ[key]
        return env_values.get(key)

    def _build_llm(self, parser: configparser.ConfigParser, env_values: dict[str, str]) -> LLMConfig:
        section = "LLM"
        base_url = self._env(env_values, "HAGENT_LLM_BASE_URL") or parser.get(
            section, "base_url", fallback=_DEFAULTS_LLM.base_url
        )
        api_key = self._env(env_values, "HAGENT_LLM_API_KEY") or parser.get(section, "api_key", fallback="")
        model = self._env(env_values, "HAGENT_LLM_MODEL") or parser.get(section, "model", fallback="")
        timeout = self._float(
            self._env(env_values, "HAGENT_LLM_TIMEOUT"), parser.get(section, "timeout", fallback=None), 120.0
        )
        temperature = self._float(
            self._env(env_values, "HAGENT_LLM_TEMPERATURE"),
            parser.get(section, "temperature", fallback=None),
            0.7,
        )
        raw_context_window = (
            self._env(env_values, "HAGENT_LLM_CONTEXT_WINDOW")
            or parser.get(section, "context_window", fallback="")
            or str(_DEFAULTS_LLM.context_window)
        )
        context_window = int(raw_context_window)
        return LLMConfig(
            base_url=base_url.strip(),
            api_key=api_key.strip(),
            model=model.strip(),
            timeout=timeout,
            temperature=temperature,
            context_window=max(context_window, 0),
        )

    def _build_agent(self, parser: configparser.ConfigParser, env_values: dict[str, str]) -> AgentConfig:
        section = "Agent"
        system_prompt = self._env(env_values, "HAGENT_SYSTEM_PROMPT") or parser.get(
            section, "system_prompt", fallback=_DEFAULTS_AGENT.system_prompt
        )
        max_tool_rounds = int(
            self._env(env_values, "HAGENT_MAX_TOOL_ROUNDS")
            or parser.get(section, "max_tool_rounds", fallback=str(_DEFAULTS_AGENT.max_tool_rounds))
        )
        max_history_messages = int(
            parser.get(section, "max_history_messages", fallback=str(_DEFAULTS_AGENT.max_history_messages))
        )
        compact_threshold = self._float(
            self._env(env_values, "HAGENT_COMPACT_THRESHOLD"),
            parser.get(section, "compact_threshold", fallback=None),
            _DEFAULTS_AGENT.compact_threshold,
        )
        raw_compact_target = (
            self._env(env_values, "HAGENT_COMPACT_TARGET_TOKENS")
            or parser.get(section, "compact_target_tokens", fallback="")
            or str(_DEFAULTS_AGENT.compact_target_tokens)
        )
        compact_target_tokens = int(raw_compact_target)
        default_context_window = int(
            self._env(env_values, "HAGENT_DEFAULT_CONTEXT_WINDOW")
            or parser.get(
                section,
                "default_context_window",
                fallback=str(_DEFAULTS_AGENT.default_context_window),
            )
        )
        archive_dirname = (
            parser.get(section, "archive_dirname", fallback=_DEFAULTS_AGENT.archive_dirname)
            or _DEFAULTS_AGENT.archive_dirname
        )
        max_search_results = int(
            parser.get(
                section,
                "max_search_results",
                fallback=str(_DEFAULTS_AGENT.max_search_results),
            )
        )
        snippet_chars = int(
            parser.get(section, "snippet_chars", fallback=str(_DEFAULTS_AGENT.snippet_chars))
        )
        agents_file = (
            self._env(env_values, "HAGENT_AGENTS_FILE")
            or parser.get(section, "agents_file", fallback=_DEFAULTS_AGENT.agents_file)
            or _DEFAULTS_AGENT.agents_file
        )
        agents_max_bytes = int(
            self._env(env_values, "HAGENT_AGENTS_MAX_BYTES")
            or parser.get(
                section,
                "agents_max_bytes",
                fallback=str(_DEFAULTS_AGENT.agents_max_bytes),
            )
        )
        return AgentConfig(
            system_prompt=system_prompt,
            max_tool_rounds=max_tool_rounds,
            max_history_messages=max_history_messages,
            compact_threshold=compact_threshold,
            compact_target_tokens=compact_target_tokens,
            default_context_window=max(default_context_window, 1),
            archive_dirname=archive_dirname,
            max_search_results=max(max_search_results, 1),
            snippet_chars=max(snippet_chars, 1),
            agents_file=agents_file,
            agents_max_bytes=max(agents_max_bytes, 1),
        )

    def _build_filesystem(
        self, parser: configparser.ConfigParser, env_values: dict[str, str]
    ) -> FilesystemConfig:
        section = "Filesystem"
        root = self._env(env_values, "HAGENT_FS_ROOT") or parser.get(section, "root", fallback="") or None
        encoding = parser.get(section, "encoding", fallback=_DEFAULTS_FILESYSTEM.encoding)
        max_read_bytes = int(
            parser.get(section, "max_read_bytes", fallback=str(_DEFAULTS_FILESYSTEM.max_read_bytes))
        )
        return FilesystemConfig(
            root=Path(root).expanduser() if root else None,
            encoding=encoding,
            max_read_bytes=max_read_bytes,
        )

    def _build_ui(self, parser: configparser.ConfigParser, env_values: dict[str, str]) -> UIConfig:
        section = "UI"
        theme = self._env(env_values, ENV_THEME) or parser.get(section, "theme", fallback=_DEFAULTS_UI.theme)
        show_sidebar = parser.getboolean(section, "show_sidebar", fallback=_DEFAULTS_UI.show_sidebar)
        sidebar_width = int(parser.get(section, "sidebar_width", fallback=str(_DEFAULTS_UI.sidebar_width)))
        session_dir = (
            parser.get(section, "session_dir", fallback=_DEFAULTS_UI.session_dir)
            or _DEFAULTS_UI.session_dir
        )
        tool_output_limit = int(
            parser.get(
                section,
                "tool_output_limit",
                fallback=str(_DEFAULTS_UI.tool_output_limit),
            )
        )
        command_palette_limit = int(
            parser.get(
                section,
                "command_palette_limit",
                fallback=str(_DEFAULTS_UI.command_palette_limit),
            )
        )
        return UIConfig(
            theme=theme,
            show_sidebar=show_sidebar,
            sidebar_width=sidebar_width,
            session_dir=session_dir,
            tool_output_limit=max(tool_output_limit, 0),
            command_palette_limit=max(command_palette_limit, 1),
        )

    def _build_mcp(self, parser: configparser.ConfigParser, env_values: dict[str, str]) -> MCPConfig:
        section = "MCP"
        config_file = (
            self._env(env_values, "HAGENT_MCP_CONFIG")
            or parser.get(section, "config_file", fallback=_DEFAULTS_MCP.config_file)
            or _DEFAULTS_MCP.config_file
        )
        default_timeout = self._float(
            self._env(env_values, "HAGENT_MCP_DEFAULT_TIMEOUT"),
            parser.get(section, "default_timeout", fallback=None),
            _DEFAULTS_MCP.default_timeout,
        )
        max_tool_name_length = int(
            parser.get(
                section,
                "max_tool_name_length",
                fallback=str(_DEFAULTS_MCP.max_tool_name_length),
            )
        )
        return MCPConfig(
            config_file=config_file,
            default_timeout=max(default_timeout, 0.1),
            max_tool_name_length=max(max_tool_name_length, 8),
        )

    def _build_search(self, parser: configparser.ConfigParser, env_values: dict[str, str]) -> SearchConfig:
        section = "search"
        baidu_api_key = (
            self._env(env_values, "HAGENT_BAIDU_API_KEY")
            or parser.get(section, "baidu_api_key", fallback=_DEFAULTS_SEARCH.baidu_api_key)
        )
        return SearchConfig(baidu_api_key=baidu_api_key.strip())

    @staticmethod
    def _float(raw: str | None, ini_value: Any, default: float) -> float:
        if raw:
            try:
                return float(raw)
            except ValueError as exc:
                raise ConfigError(f"浮点型配置项非法：{raw}") from exc
        if ini_value:
            try:
                return float(ini_value)
            except (TypeError, ValueError) as exc:
                raise ConfigError(f"浮点型配置项非法：{ini_value}") from exc
        return default


__all__ = [
    "DEFAULT_AGENTS_FILENAME",
    "DEFAULT_CONFIG_FILENAME",
    "DEFAULT_CONFIG_TEMPLATE",
    "DEFAULT_SYSTEM_PROMPT",
    "AgentConfig",
    "AppConfig",
    "ConfigLoader",
    "FilesystemConfig",
    "LLMConfig",
    "MCPConfig",
    "SearchConfig",
    "UIConfig",
]

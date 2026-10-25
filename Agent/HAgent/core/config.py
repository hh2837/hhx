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

ENV_CONFIG_PATH = "XAGENT_CONFIG"
ENV_WORKSPACE = "XAGENT_WORKSPACE"
ENV_THEME = "XAGENT_THEME"

DEFAULT_SYSTEM_PROMPT = (
    "你是一个命令行助手，拥有本地文件系统与时间相关的工具能力。"
    "回答要简洁、准确，必要时主动调用工具获取真实信息，不要臆造。"
)


@dataclass(frozen=True, slots=True)
class LLMConfig:
    """大模型服务配置。"""

    base_url: str = "http://localhost:1234/v1"
    api_key: str = ""
    model: str = ""
    timeout: float = 120.0
    temperature: float = 0.7

    @property
    def chat_completions_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"


@dataclass(frozen=True, slots=True)
class AgentConfig:
    """Agent 编排配置。"""

    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    max_tool_rounds: int = 8
    max_history_messages: int = 200


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
    """界面配置（核心层只保留与业务相关的少数几项）。"""

    theme: str = "textual-dark"
    show_sidebar: bool = True
    sidebar_width: int = 42


@dataclass(frozen=True, slots=True)
class AppConfig:
    """应用总配置。"""

    llm: LLMConfig = LLMConfig()
    agent: AgentConfig = AgentConfig()
    filesystem: FilesystemConfig = FilesystemConfig()
    ui: UIConfig = UIConfig()
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


@dataclass(frozen=True, slots=True)
class ConfigLoader:
    """配置加载器。

    使用示例::

        config = ConfigLoader().load()
    """

    config_path: Path | None = None
    env_file: Path | None = None

    @staticmethod
    def project_root() -> Path:
        """xAgent 项目根目录（core 包的上一级）。"""
        return Path(__file__).resolve().parent.parent

    @classmethod
    def default_config_path(cls) -> Path:
        return cls.project_root() / DEFAULT_CONFIG_FILENAME

    def resolve_config_path(self) -> Path | None:
        if self.config_path is not None:
            return Path(self.config_path)
        env_path = os.environ.get(ENV_CONFIG_PATH)
        if env_path:
            return Path(env_path)
        default = self.default_config_path()
        return default if default.exists() else None

    def load(self) -> AppConfig:
        """加载配置并返回 :class:`AppConfig`。"""
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

        workspace = Path(
            env_values.get("workspace") or parser.get("Agent", "workspace", fallback="") or Path.cwd()
        ).expanduser()

        config = AppConfig(
            llm=llm,
            agent=agent,
            filesystem=filesystem,
            ui=ui,
            workspace=workspace.resolve(),
            config_path=Path(config_path) if config_path else None,
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
        base_url = self._env(env_values, "XAGENT_LLM_BASE_URL") or parser.get(
            section, "base_url", fallback=_DEFAULTS_LLM.base_url
        )
        api_key = self._env(env_values, "XAGENT_LLM_API_KEY") or parser.get(section, "api_key", fallback="")
        model = self._env(env_values, "XAGENT_LLM_MODEL") or parser.get(section, "model", fallback="")
        timeout = self._float(
            self._env(env_values, "XAGENT_LLM_TIMEOUT"), parser.get(section, "timeout", fallback=None), 120.0
        )
        temperature = self._float(
            self._env(env_values, "XAGENT_LLM_TEMPERATURE"),
            parser.get(section, "temperature", fallback=None),
            0.7,
        )
        return LLMConfig(
            base_url=base_url.strip(),
            api_key=api_key.strip(),
            model=model.strip(),
            timeout=timeout,
            temperature=temperature,
        )

    def _build_agent(self, parser: configparser.ConfigParser, env_values: dict[str, str]) -> AgentConfig:
        section = "Agent"
        system_prompt = self._env(env_values, "XAGENT_SYSTEM_PROMPT") or parser.get(
            section, "system_prompt", fallback=_DEFAULTS_AGENT.system_prompt
        )
        max_tool_rounds = int(
            self._env(env_values, "XAGENT_MAX_TOOL_ROUNDS")
            or parser.get(section, "max_tool_rounds", fallback=str(_DEFAULTS_AGENT.max_tool_rounds))
        )
        max_history_messages = int(
            parser.get(section, "max_history_messages", fallback=str(_DEFAULTS_AGENT.max_history_messages))
        )
        return AgentConfig(
            system_prompt=system_prompt,
            max_tool_rounds=max_tool_rounds,
            max_history_messages=max_history_messages,
        )

    def _build_filesystem(
        self, parser: configparser.ConfigParser, env_values: dict[str, str]
    ) -> FilesystemConfig:
        section = "Filesystem"
        root = self._env(env_values, "XAGENT_FS_ROOT") or parser.get(section, "root", fallback="") or None
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
        return UIConfig(theme=theme, show_sidebar=show_sidebar, sidebar_width=sidebar_width)

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
    "DEFAULT_SYSTEM_PROMPT",
    "AgentConfig",
    "AppConfig",
    "ConfigLoader",
    "FilesystemConfig",
    "LLMConfig",
    "UIConfig",
]

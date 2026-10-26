import sys

path = r"D:\LLM\Agent\HAgent\core\config.py"
with open(path, encoding="utf-8") as f:
    s = f.read()

if "SearchConfig" in s:
    print("already")
    sys.exit(0)

old = '''@dataclass(frozen=True, slots=True)
class UIConfig:
    """界面配置（核心层只保留与业务相关的少数几项）"""

    theme: str = "textual-dark"
    show_sidebar: bool = True
    sidebar_width: int = 42


@dataclass(frozen=True, slots=True)
class AppConfig:
    """应用总配置"""

    llm: LLMConfig = LLMConfig()
    agent: AgentConfig = AgentConfig()
    filesystem: FilesystemConfig = FilesystemConfig()
    ui: UIConfig = UIConfig()
    workspace: Path = field(default_factory=Path.cwd)
    config_path: Path | None = None

    @property
    def sandbox_root(self) -> Path:
        """文件工具实际使用的沙箱根目录
        优先使用配置中显式指定的根目录，否则以工作目录为准
        """
        return self.filesystem.root or self.workspace

    def with_workspace(self, workspace: Path) -> AppConfig:
        """派生一个以指定目录作为工作区的新配置"""
        return replace(self, workspace=Path(workspace).resolve())


# dataclass(slots=True) 的类属性是 slot 描述符而非默认值，这里统一取实例作为默认值来源
_DEFAULTS_LLM = LLMConfig()
_DEFAULTS_AGENT = AgentConfig()
_DEFAULTS_FILESYSTEM = FilesystemConfig()
_DEFAULTS_UI = UIConfig()
'''

new = '''@dataclass(frozen=True, slots=True)
class UIConfig:
    """界面配置（核心层只保留与业务相关的少数几项）"""

    theme: str = "textual-dark"
    show_sidebar: bool = True
    sidebar_width: int = 42


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
    search: SearchConfig = SearchConfig()
    workspace: Path = field(default_factory=Path.cwd)
    config_path: Path | None = None

    @property
    def sandbox_root(self) -> Path:
        """文件工具实际使用的沙箱根目录
        优先使用配置中显式指定的根目录，否则以工作目录为准
        """
        return self.filesystem.root or self.workspace

    def with_workspace(self, workspace: Path) -> AppConfig:
        """派生一个以指定目录作为工作区的新配置"""
        return replace(self, workspace=Path(workspace).resolve())


# dataclass(slots=True) 的类属性是 slot 描述符而非默认值，这里统一取实例作为默认值来源
_DEFAULTS_LLM = LLMConfig()
_DEFAULTS_AGENT = AgentConfig()
_DEFAULTS_FILESYSTEM = FilesystemConfig()
_DEFAULTS_UI = UIConfig()
_DEFAULTS_SEARCH = SearchConfig()
'''

if old not in s:
    print("notfound")
    sys.exit(1)

s2 = s.replace(old, new)
with open(path, "w", encoding="utf-8") as f:
    f.write(s2)
print("ok")

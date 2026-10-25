"""xAgent 核心层（core）。

本包是整个项目的"业务内核"，不依赖任何界面框架，只依赖标准库与 HTTP 客户端。
所有前端（``tui`` / 未来的 ``web`` / ``desktop`` / ``mobile``）都只允许通过
这里导出的公共 API 访问业务能力，从而保证：

* 业务逻辑只有一份实现，多端复用；
* 前端可以随时替换或新增，互不影响；
* 核心层可以被独立单元测试，不需要启动界面。

公共 API 约定：前端请从 ``core`` 顶层导入，不要直接依赖 ``core.<子模块>``，
子模块结构属于内部实现，可能在不通知前端的情况下调整。
"""

from .agent import Agent, Session, SessionStore
from .config import (
    AgentConfig,
    AppConfig,
    ConfigLoader,
    FilesystemConfig,
    LLMConfig,
    UIConfig,
)
from .errors import (
    AgentError,
    ConfigError,
    LLMConnectionError,
    LLMError,
    LLMResponseError,
    MaxToolRoundsExceeded,
    ToolError,
    ToolExecutionError,
    ToolNotFoundError,
    XAgentError,
)
from .events import (
    AssistantDelta,
    AssistantMessage,
    AssistantMessageStarted,
    ErrorOccurred,
    Event,
    EventEmitter,
    RunFinished,
    RunStarted,
    ToolCallFinished,
    ToolCallRequested,
    UserMessageEcho,
)
from .factory import build_agent, build_client, build_tools
from .llm import LLMClient, OpenAICompatibleClient, StreamChunk, ToolCallDelta
from .models import Message, ToolCall
from .tools import ToolRegistry, ToolResult, ToolSpec, register_builtin_tools

__version__ = "0.1.0"

__all__ = [
    "Agent",
    "AgentConfig",
    "AgentError",
    "AppConfig",
    "AssistantDelta",
    "AssistantMessage",
    "AssistantMessageStarted",
    "ConfigError",
    "ConfigLoader",
    "ErrorOccurred",
    "Event",
    "EventEmitter",
    "FilesystemConfig",
    "LLMClient",
    "LLMConfig",
    "LLMConnectionError",
    "LLMError",
    "LLMResponseError",
    "MaxToolRoundsExceeded",
    "Message",
    "OpenAICompatibleClient",
    "RunFinished",
    "RunStarted",
    "Session",
    "SessionStore",
    "StreamChunk",
    "ToolCall",
    "ToolCallDelta",
    "ToolCallFinished",
    "ToolCallRequested",
    "ToolError",
    "ToolExecutionError",
    "ToolNotFoundError",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
    "UIConfig",
    "UserMessageEcho",
    "XAgentError",
    "__version__",
    "build_agent",
    "build_client",
    "build_tools",
    "register_builtin_tools",
]

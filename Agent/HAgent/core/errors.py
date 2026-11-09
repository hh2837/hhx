"""统一异常体系。

所有跨层抛出的异常都继承自 :class:`HAgentError`，前端只需要捕获这一个基类
即可把任意内部错误转换成用户可读的提示，而不必知道具体实现细节。
"""

from __future__ import annotations


class HAgentError(Exception):
    """HAgent 所有业务异常的根类型。"""


class ConfigError(HAgentError):
    """配置文件缺失、格式非法或取值不合法。"""


class LLMError(HAgentError):
    """调用大模型过程中发生的错误。"""


class LLMConnectionError(LLMError):
    """无法连接到大模型服务（网络不可达、超时等）。"""


class LLMResponseError(LLMError):
    """大模型返回了无法解析的响应。"""


class ToolError(HAgentError):
    """工具执行相关错误。"""


class ToolNotFoundError(ToolError):
    """请求调用了未注册的工具。"""


class ToolExecutionError(ToolError):
    """工具在执行过程中失败。"""


class AgentError(HAgentError):
    """Agent 运行编排相关错误。"""


class MaxToolRoundsExceeded(AgentError):
    """单轮对话内工具调用次数超过上限。"""


class ContextError(AgentError):
    """上下文归档、压缩或检索过程中发生的错误。"""


class ContextCompactionRequired(ContextError):
    """上下文已达到阈值，必须先执行 /compact 才能继续普通对话。"""


class SkillError(HAgentError):
    """Skill 发现、解析或加载相关错误。"""


class SkillNotFoundError(SkillError):
    """请求加载了不存在的 Skill。"""


class MCPError(HAgentError):
    """MCP 配置、连接或工具调用相关错误。"""


class MCPConfigError(MCPError):
    """读取或解析 .mcp.json 配置失败。"""


class MCPConnectionError(MCPError):
    """无法连接 MCP Server。"""


class MCPToolError(MCPError):
    """调用 MCP 工具失败。"""


__all__ = [
    "AgentError",
    "ConfigError",
    "ContextCompactionRequired",
    "ContextError",
    "LLMConnectionError",
    "LLMError",
    "LLMResponseError",
    "MCPConfigError",
    "MCPConnectionError",
    "MCPError",
    "MCPToolError",
    "MaxToolRoundsExceeded",
    "SkillError",
    "SkillNotFoundError",
    "ToolError",
    "ToolExecutionError",
    "ToolNotFoundError",
    "HAgentError",
]

"""统一异常体系。

所有跨层抛出的异常都继承自 :class:`XAgentError`，前端只需要捕获这一个基类
即可把任意内部错误转换成用户可读的提示，而不必知道具体实现细节。
"""

from __future__ import annotations


class XAgentError(Exception):
    """xAgent 所有业务异常的根类型。"""


class ConfigError(XAgentError):
    """配置文件缺失、格式非法或取值不合法。"""


class LLMError(XAgentError):
    """调用大模型过程中发生的错误。"""


class LLMConnectionError(LLMError):
    """无法连接到大模型服务（网络不可达、超时等）。"""


class LLMResponseError(LLMError):
    """大模型返回了无法解析的响应。"""


class ToolError(XAgentError):
    """工具执行相关错误。"""


class ToolNotFoundError(ToolError):
    """请求调用了未注册的工具。"""


class ToolExecutionError(ToolError):
    """工具在执行过程中失败。"""


class AgentError(XAgentError):
    """Agent 运行编排相关错误。"""


class MaxToolRoundsExceeded(AgentError):
    """单轮对话内工具调用次数超过上限。"""


__all__ = [
    "AgentError",
    "ConfigError",
    "LLMConnectionError",
    "LLMError",
    "LLMResponseError",
    "MaxToolRoundsExceeded",
    "ToolError",
    "ToolExecutionError",
    "ToolNotFoundError",
    "XAgentError",
]

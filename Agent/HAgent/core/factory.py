"""装配工厂：把配置组装成一个可运行的 :class:`Agent`。

前端只需调用 :func:`build_agent`，无需了解内部的客户端 / 工具细节。
"""

from __future__ import annotations

import dataclasses

from .agent.agent import Agent
from .config import AppConfig
from .llm.client import LLMClient
from .llm.openai_client import OpenAICompatibleClient
from .tools.registry import ToolRegistry, register_builtin_tools
from .tools.search_tools import register_search_tools
from .tools.webfetch_tools import register_webfetch_tools
from .tools.runcli_tools import register_runcli_tools


def build_tools(config: AppConfig) -> ToolRegistry:
    """按配置构建工具注册表（内置时序 + 文件系统工具 + 搜索工具 + 网页抓取工具 + CLI工具）"""
    registry = ToolRegistry()
    filesystem = dataclasses.replace(config.filesystem, root=config.sandbox_root)
    register_builtin_tools(registry, filesystem)
    register_search_tools(registry, config.search)
    register_webfetch_tools(registry)
    register_runcli_tools(registry)
    return registry


def build_client(config: AppConfig) -> LLMClient:
    """按配置构建大模型客户端。"""
    return OpenAICompatibleClient(config.llm)


def build_agent(config: AppConfig, client: LLMClient | None = None, tools: ToolRegistry | None = None) -> Agent:
    """按配置装配一个 :class:`Agent`。"""
    return Agent(
        client=client or build_client(config),
        tools=tools or build_tools(config),
        config=config.agent,
        system_prompt=config.agent.system_prompt,
    )


__all__ = ["build_agent", "build_client", "build_tools"]

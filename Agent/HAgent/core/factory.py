"""装配工厂：把配置组装成一个可运行的 :class:`Agent`。

前端只需调用 :func:`build_agent`，无需了解内部的客户端 / 工具细节。
"""

from __future__ import annotations

import dataclasses

from .agent.agent import Agent
from .config import AppConfig
from .context import ContextStore, default_context_directory
from .llm.client import LLMClient
from .llm.openai_client import OpenAICompatibleClient
from .mcp import MCPClientManager, register_mcp_tools
from .skills import SkillRegistry
from .tools.context_tools import register_recall_context_tool
from .tools.registry import ToolRegistry, register_builtin_tools
from .tools.runcli_tools import register_runcli_tools
from .tools.search_tools import register_search_tools
from .tools.webfetch_tools import register_webfetch_tools


def build_tools(config: AppConfig, *, load_mcp: bool = True) -> ToolRegistry:
    """按配置构建工具注册表（本地工具 + 可选 MCP 工具）。"""
    registry = ToolRegistry()
    filesystem = dataclasses.replace(config.filesystem, root=config.sandbox_root)
    register_builtin_tools(registry, filesystem)
    register_search_tools(registry, config.search)
    register_webfetch_tools(registry)
    register_runcli_tools(registry)
    if load_mcp:
        build_mcp_tools(config, registry)
    register_recall_context_tool(
        registry,
        ContextStore(
            default_context_directory(config.workspace, config.agent.archive_dirname),
            max_results=config.agent.max_search_results,
            snippet_chars=config.agent.snippet_chars,
        ),
    )
    return registry


def build_mcp_tools(
    config: AppConfig,
    registry: ToolRegistry,
    manager: MCPClientManager | None = None,
) -> MCPClientManager | None:
    """连接 MCP Server 并把工具注册到已有注册表。

    该函数会阻塞直到连接完成；TUI 应放到后台线程中调用，避免界面启动被拖慢。
    """
    return register_mcp_tools(
        registry,
        root=config.workspace,
        manager=manager,
        config_file=config.mcp.config_file,
        default_timeout=config.mcp.default_timeout,
        max_tool_name_length=config.mcp.max_tool_name_length,
    )


def build_client(config: AppConfig) -> LLMClient:
    """按配置构建大模型客户端。"""
    return OpenAICompatibleClient(config.llm)


def build_agent(
    config: AppConfig,
    client: LLMClient | None = None,
    tools: ToolRegistry | None = None,
    skills: SkillRegistry | None = None,
    *,
    load_mcp: bool = True,
) -> Agent:
    """按配置装配一个 :class:`Agent`。"""
    return Agent(
        client=client or build_client(config),
        tools=tools or build_tools(config, load_mcp=load_mcp),
        config=config.agent,
        system_prompt=config.agent.system_prompt,
        skills=skills,
        context_window=config.llm.context_window,
        context_dir=default_context_directory(config.workspace),
        workspace=config.workspace,
        agents_file=config.agent.agents_file,
        agents_max_bytes=config.agent.agents_max_bytes,
    )


__all__ = ["build_agent", "build_client", "build_mcp_tools", "build_tools"]

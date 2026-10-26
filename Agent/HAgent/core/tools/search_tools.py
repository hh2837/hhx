from __future__ import annotations

import json
from typing import Any

import requests

from ..config import SearchConfig
from .base import ToolResult
from .registry import ToolRegistry

QIANFAN_SEARCH_URL = "https://qianfan.baidubce.com/v2/ai_search/chat/completions"


def _extract_results(data: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if not isinstance(data, dict):
        return results
    for key in ("references", "web_results", "results", "search_results"):
        if key in data and isinstance(data[key], list):
            for item in data[key]:
                if isinstance(item, dict):
                    results.append(item)
            break
    if not results and "choices" in data and isinstance(data["choices"], list):
        for choice in data["choices"]:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message") or {}
            if isinstance(message, dict):
                for key in ("references", "web_results", "results"):
                    if key in message and isinstance(message[key], list):
                        for item in message[key]:
                            if isinstance(item, dict):
                                results.append(item)
                        if results:
                            break
                if results:
                    break
            for key in ("references", "web_results"):
                if key in choice and isinstance(choice[key], list):
                    for item in choice[key]:
                        if isinstance(item, dict):
                            results.append(item)
                    if results:
                        break
    return results


def _format_results(query: str, data: dict[str, Any]) -> str:
    results = _extract_results(data)
    lines: list[str] = []
    lines.append("搜索关键词/问题：" + str(query))
    lines.append("")

    summary = None
    if isinstance(data, dict):
        for key in ("summary", "answer", "content", "response"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                summary = val.strip()
                break
        if summary is None and "choices" in data and isinstance(data["choices"], list):
            for choice in data["choices"]:
                if not isinstance(choice, dict):
                    continue
                message = choice.get("message") or {}
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str) and content.strip():
                        summary = content.strip()
                        break
                delta = choice.get("delta") or {}
                if isinstance(delta, dict):
                    content = delta.get("content")
                    if isinstance(content, str) and content.strip():
                        summary = content.strip()
                        break

    if summary:
        lines.append("搜索摘要：")
        lines.append(summary)
        lines.append("")

    if not results:
        if not summary:
            lines.append("未找到结构化的参考来源。")
            lines.append("原始响应：")
            try:
                lines.append(json.dumps(data, ensure_ascii=False, indent=2))
            except Exception:
                lines.append(str(data))
        return "\n".join(lines)

    lines.append("参考来源：")
    for idx, item in enumerate(results, 1):
        title = item.get("title") or item.get("name") or item.get("web_title") or item.get("site_name") or ""
        url = item.get("url") or item.get("link") or item.get("web_url") or item.get("href") or ""
        snippet = item.get("snippet") or item.get("summary") or item.get("content") or item.get("abstract") or ""
        lines.append(f"{idx}. 标题：{title or '（无标题）'}")
        if url:
            lines.append(f"   URL：{url}")
        if snippet:
            snippet_clean = str(snippet).strip().replace("\n", " ")
            if len(snippet_clean) > 200:
                snippet_clean = snippet_clean[:197] + "..."
            lines.append(f"   摘要：{snippet_clean}")
        lines.append("")

    return "\n".join(lines).rstrip()


class SearchTools:
    def __init__(self, config: SearchConfig | None = None) -> None:
        self._config = config or SearchConfig()

    def searchweb(self, query: str) -> str:
        query_str = str(query).strip() if query is not None else ""
        if not query_str:
            err = ToolResult.failure("搜索关键词或问题不能为空。").error
            return err or "搜索关键词或问题不能为空。"

        api_key = (self._config.baidu_api_key or "").strip()
        if not api_key:
            err = ToolResult.failure("缺少百度千帆 API 配置：请在 config.ini 的 [search] 小节设置 baidu_api_key，或通过环境变量 XAGENT_BAIDU_API_KEY 配置。").error
            return err or "缺少搜索配置"

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "messages": [{"role": "user", "content": query_str}],
            "search_source": "baidu_search_v2",
            "search_recency_filter": "noLimit",
            "enable_citation": True,
        }

        try:
            resp = requests.post(QIANFAN_SEARCH_URL, headers=headers, json=payload, timeout=30)
        except requests.RequestException as exc:
            err = ToolResult.failure(f"网络请求失败：{exc}").error
            return err or f"网络请求失败：{exc}"

        try:
            data = resp.json()
        except ValueError:
            text = resp.text[:500]
            err = ToolResult.failure(f"API 返回非 JSON 响应（状态码 {resp.status_code}）：{text}").error
            return err or "API 返回非 JSON 响应"

        if resp.status_code >= 400:
            msg = None
            if isinstance(data, dict):
                msg = data.get("error") or data.get("message") or data.get("msg")
                if isinstance(msg, dict):
                    msg = msg.get("message") or msg.get("msg") or str(msg)
            err_text = str(msg) if msg else json.dumps(data, ensure_ascii=False)[:500]
            err = ToolResult.failure(f"API 返回错误（状态码 {resp.status_code}）：{err_text}").error
            return err or f"API 返回错误（状态码 {resp.status_code}）"

        try:
            return _format_results(query_str, data)
        except Exception as exc:
            err = ToolResult.failure(f"处理搜索结果失败：{exc}").error
            return err or f"处理搜索结果失败：{exc}"


def register_search_tools(registry: ToolRegistry, search_config: SearchConfig | None = None) -> ToolRegistry:
    tools = SearchTools(search_config)
    registry.tool(name="searchweb")(tools.searchweb)
    return registry


__all__ = ["SearchTools", "register_search_tools"]

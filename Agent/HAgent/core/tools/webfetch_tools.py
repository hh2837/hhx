from __future__ import annotations

import json
import os
import subprocess
import tempfile
from typing import Any
from urllib.parse import urlparse

import trafilatura
from trafilatura.settings import use_config

from .base import ToolResult
from .registry import ToolRegistry


class WebFetchTools:
    def __init__(self) -> None:
        pass

    def fetchweb(self, url: str) -> str:
        """获取指定网页的主要内容并转换为Markdown格式。
        Args:
            url: 要获取的网页URL
        """
        url_str = str(url).strip() if url is not None else ""
        if not url_str:
            err = ToolResult.failure("URL不能为空。").error
            return err or "URL不能为空。"

        parsed = urlparse(url_str)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            err = ToolResult.failure("无效的URL：仅支持http/https协议。").error
            return err or "无效的URL：仅支持http/https协议。"

        curl_exe = "curl"
        # prefer system curl
        curl_path = r"C:\Windows\System32\curl.exe"
        if os.path.exists(curl_path):
            curl_exe = curl_path

        cmd = [
            curl_exe,
            "-L",
            "--silent",
            "--show-error",
            "--connect-timeout",
            "10",
            "--max-time",
            "30",
            "-H",
            "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "-H",
            "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            url_str,
        ]

        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=40)
        except subprocess.TimeoutExpired:
            err = ToolResult.failure("网页访问超时。").error
            return err or "网页访问超时。"
        except OSError as exc:
            err = ToolResult.failure(f"调用curl失败：{exc}").error
            return err or f"调用curl失败：{exc}"
        except Exception as exc:
            err = ToolResult.failure(f"网页访问失败：{exc}").error
            return err or f"网页访问失败：{exc}"

        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
            stderr_clean = stderr.strip().replace("\n", " ")
            if len(stderr_clean) > 200:
                stderr_clean = stderr_clean[:197] + "..."
            err = ToolResult.failure(f"网页访问失败（curl返回码 {proc.returncode}）：{stderr_clean}").error
            return err or f"网页访问失败（curl返回码 {proc.returncode}）"

        html_bytes = proc.stdout
        if not html_bytes:
            err = ToolResult.failure("获取到空的HTML内容。").error
            return err or "获取到空的HTML内容。"

        try:
            html = html_bytes.decode("utf-8", errors="replace")
        except Exception as exc:
            err = ToolResult.failure(f"HTML解码失败：{exc}").error
            return err or f"HTML解码失败：{exc}"

        try:
            config = use_config()
            config.set("DEFAULT", "include_comments", "false")
            config.set("DEFAULT", "include_tables", "true")
            config.set("DEFAULT", "include_links", "true")
            config.set("DEFAULT", "include_images", "false")
            config.set("DEFAULT", "output_format", "markdown")
            markdown = trafilatura.extract(
                html,
                config=config,
                output_format="markdown",
                include_comments=False,
                include_tables=True,
                include_links=True,
                include_images=False,
                favor_precision=True,
            )
        except Exception as exc:
            err = ToolResult.failure(f"HTML解析或正文提取失败：{exc}").error
            return err or f"HTML解析或正文提取失败：{exc}"

        if not markdown or not str(markdown).strip():
            err = ToolResult.failure("正文无法提取（可能是动态页面、需要登录或内容受限）。").error
            return err or "正文无法提取（可能是动态页面、需要登录或内容受限）。"

        result = []
        result.append(f"原始URL：{url_str}")
        result.append("")
        result.append(str(markdown).strip())
        return "\n".join(result)


def register_webfetch_tools(registry: ToolRegistry) -> ToolRegistry:
    tools = WebFetchTools()
    registry.tool(name="fetchweb")(tools.fetchweb)
    return registry


__all__ = ["WebFetchTools", "register_webfetch_tools"]

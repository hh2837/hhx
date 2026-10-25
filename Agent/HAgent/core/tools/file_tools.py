"""文件系统相关内置工具。

所有路径都会经过 :meth:`FilesystemConfig.resolve` 归一化，并默认限制在沙箱
根目录内，避免模型越权访问系统其他位置。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from ..config import FilesystemConfig
from ..errors import ToolExecutionError
from .registry import ToolRegistry


class FileTools:
    """文件系统工具集合。

    以类为单位聚合，便于按不同配置（沙箱根目录、编码等）实例化。
    """

    def __init__(self, config: FilesystemConfig | None = None) -> None:
        self._config = config or FilesystemConfig()

    @property
    def config(self) -> FilesystemConfig:
        return self._config

    # -------------------------------------------------------------- 只读工具

    def get_cwd(self) -> str:
        """获取当前工作目录。"""
        root = self._config.root or Path.cwd()
        return str(root)

    def list_dir(self, path: str = ".") -> str:
        """列出指定目录下的文件和子目录。

        Args:
            path: 目录路径，默认为当前目录
        """
        target = self._resolve(path)
        if not target.exists():
            return f"路径不存在：{path}"
        if not target.is_dir():
            return f"不是目录：{path}"
        items = sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
        if not items:
            return "（空目录）"
        return "\n".join(f"{item.name}{'/' if item.is_dir() else ''}" for item in items)

    def file_info(self, path: str) -> str:
        """获取指定路径的文件信息（类型、扩展名）。

        Args:
            path: 文件或目录路径
        """
        target = self._resolve(path)
        if not target.exists():
            return f"路径不存在：{path}"
        kind = "目录" if target.is_dir() else "文件"
        ext = target.suffix
        size = target.stat().st_size if target.is_file() else 0
        return f"{target} 是{kind}，扩展名：{ext or '无'}，大小：{size} 字节"

    def read_file(self, path: str) -> str:
        """读取指定文本文件的内容。

        Args:
            path: 文件路径
        """
        target = self._resolve(path)
        if not target.exists():
            return f"文件不存在：{path}"
        if not target.is_file():
            return f"不是文件：{path}"
        size = target.stat().st_size
        if size > self._config.max_read_bytes:
            return (
                f"文件过大（{size} 字节），已超过上限 {self._config.max_read_bytes} 字节，拒绝读取。"
            )
        try:
            return target.read_text(encoding=self._config.encoding, errors="replace")
        except OSError as exc:
            raise ToolExecutionError(f"读取文件失败：{exc}") from exc

    # -------------------------------------------------------------- 写入工具

    def create_file(self, path: str, content: str = "") -> str:
        """新建文件并可写入初始内容。

        Args:
            path: 文件路径
            content: 初始内容，默认为空
        """
        target = self._resolve(path)
        if target.exists():
            return f"文件已存在：{path}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content or "", encoding=self._config.encoding)
        return f"已创建文件：{target}"

    def write_file(self, path: str, content: str) -> str:
        """修改（覆盖写入）指定文本文件的内容。

        Args:
            path: 文件路径
            content: 要写入的内容
        """
        target = self._resolve(path)
        if not target.exists():
            return f"文件不存在：{path}"
        if target.is_dir():
            return f"不是文件：{path}"
        target.write_text(content or "", encoding=self._config.encoding)
        return f"已写入文件：{target}"

    def create_dir(self, path: str) -> str:
        """新建目录。

        Args:
            path: 目录路径
        """
        target = self._resolve(path)
        target.mkdir(parents=True, exist_ok=True)
        return f"已创建目录：{target}"

    def delete_dir(self, path: str) -> str:
        """删除目录（含非空目录）。

        Args:
            path: 目录路径
        """
        target = self._resolve(path)
        if not target.exists():
            return f"目录不存在：{path}"
        if not target.is_dir():
            return f"不是目录：{path}"
        shutil.rmtree(target)
        return f"已删除目录：{target}"

    def delete_file(self, path: str) -> str:
        """删除文件。

        Args:
            path: 文件路径
        """
        target = self._resolve(path)
        if not target.exists():
            return f"文件不存在：{path}"
        if target.is_dir():
            return f"不是文件：{path}"
        os.remove(target)
        return f"已删除文件：{target}"

    def move_path(self, src: str, dst: str) -> str:
        """重命名或移动文件/目录。

        Args:
            src: 源路径
            dst: 目标路径
        """
        source = self._resolve(src)
        destination = self._resolve(dst)
        if not source.exists():
            return f"路径不存在：{src}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        return f"已重命名/移动：{source} -> {destination}"

    # -------------------------------------------------------------- 内部实现

    def _resolve(self, path: str | os.PathLike[str]) -> Path:
        return self._config.resolve(path)


def register_file_tools(registry: ToolRegistry, config: FilesystemConfig | None = None) -> ToolRegistry:
    """把文件系统工具注册到注册表。"""
    tools = FileTools(config)

    @registry.tool()
    def get_cwd() -> str:
        """获取当前工作目录。"""
        return tools.get_cwd()

    @registry.tool()
    def list_dir(path: str = ".") -> str:
        """列出指定目录下的文件和子目录。

        Args:
            path: 目录路径，默认为当前目录
        """
        return tools.list_dir(path)

    @registry.tool()
    def file_info(path: str) -> str:
        """获取指定路径的文件信息（类型、扩展名）。

        Args:
            path: 文件或目录路径
        """
        return tools.file_info(path)

    @registry.tool()
    def read_file(path: str) -> str:
        """读取指定文本文件的内容。

        Args:
            path: 文件路径
        """
        return tools.read_file(path)

    @registry.tool()
    def create_file(path: str, content: str = "") -> str:
        """新建文件并可写入初始内容。

        Args:
            path: 文件路径
            content: 初始内容，默认为空
        """
        return tools.create_file(path, content)

    @registry.tool()
    def write_file(path: str, content: str) -> str:
        """修改（覆盖写入）指定文本文件的内容。

        Args:
            path: 文件路径
            content: 要写入的内容
        """
        return tools.write_file(path, content)

    @registry.tool()
    def create_dir(path: str) -> str:
        """新建目录。

        Args:
            path: 目录路径
        """
        return tools.create_dir(path)

    @registry.tool()
    def delete_dir(path: str) -> str:
        """删除目录（含非空目录）。

        Args:
            path: 目录路径
        """
        return tools.delete_dir(path)

    @registry.tool()
    def delete_file(path: str) -> str:
        """删除文件。

        Args:
            path: 文件路径
        """
        return tools.delete_file(path)

    @registry.tool()
    def move_path(src: str, dst: str) -> str:
        """重命名或移动文件/目录。

        Args:
            src: 源路径
            dst: 目标路径
        """
        return tools.move_path(src, dst)

    return registry


__all__ = ["FileTools", "register_file_tools"]

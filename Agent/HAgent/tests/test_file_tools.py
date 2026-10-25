"""文件系统工具的测试（全部在临时目录内进行）。"""

from __future__ import annotations

from pathlib import Path

from core import FilesystemConfig, ToolRegistry
from core.tools.file_tools import register_file_tools


def _registry(root: Path) -> ToolRegistry:
    registry = ToolRegistry()
    register_file_tools(registry, FilesystemConfig(root=root))
    return registry


def test_创建与读取文件(tmp_path: Path) -> None:
    registry = _registry(tmp_path)

    created = registry.execute("create_file", {"path": "demo.txt", "content": "你好"})
    assert created.ok and "已创建文件" in created.content
    assert (tmp_path / "demo.txt").read_text(encoding="utf-8") == "你好"

    read = registry.execute("read_file", {"path": "demo.txt"})
    assert read.ok and read.content == "你好"


def test_列出目录与文件信息(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    registry.execute("create_file", {"path": "a.txt", "content": "x"})
    registry.execute("create_dir", {"path": "sub"})

    listing = registry.execute("list_dir", {"path": "."})
    assert listing.ok and "a.txt" in listing.content and "sub/" in listing.content

    info = registry.execute("file_info", {"path": "a.txt"})
    assert info.ok and ".txt" in info.content


def test_重命名与删除(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    registry.execute("create_file", {"path": "a.txt", "content": "x"})

    moved = registry.execute("move_path", {"src": "a.txt", "dst": "b.txt"})
    assert moved.ok and (tmp_path / "b.txt").exists()

    deleted = registry.execute("delete_file", {"path": "b.txt"})
    assert deleted.ok and not (tmp_path / "b.txt").exists()


def test_沙箱外路径被拒绝(tmp_path: Path) -> None:
    registry = _registry(tmp_path / "sandbox")
    (tmp_path / "sandbox").mkdir()

    result = registry.execute("read_file", {"path": str(tmp_path / "outside.txt")})
    assert not result.ok
    assert "根目录" in (result.error or "")


def test_超大文件拒绝读取(tmp_path: Path) -> None:
    registry = ToolRegistry()
    register_file_tools(registry, FilesystemConfig(root=tmp_path, max_read_bytes=4))
    (tmp_path / "big.txt").write_text("0123456789", encoding="utf-8")

    result = registry.execute("read_file", {"path": "big.txt"})
    assert "过大" in result.content


def test_读取不存在的文件给出提示(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    result = registry.execute("read_file", {"path": "nope.txt"})
    assert result.ok
    assert "文件不存在" in result.content

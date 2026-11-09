"""历史上下文检索工具（recallContext）。"""

from __future__ import annotations

from ..context import ContextStore
from .base import ToolResult
from .registry import ToolRegistry


def register_recall_context_tool(
    registry: ToolRegistry,
    context_store: ContextStore | None = None,
) -> ToolRegistry:
    """把 ``recallContext`` 注册为普通 Function Calling 工具。"""
    if "recallContext" in registry:
        return registry

    store = context_store or ContextStore()

    @registry.tool(
        name="recallContext",
        description=(
            "检索此前保存的原始上下文归档。当压缩摘要缺少某些历史细节时，"
            "使用本工具按关键词查找原始对话、工具调用参数或工具结果。"
            "不指定 id 时会在全部历史归档中检索。"
        ),
    )
    def recall_context(text: str, id: str | None = None) -> ToolResult:
        """检索历史上下文归档。

        Args:
            text: 要查找的关键词或文本内容；多个关键词用空格分隔
            id: 可选。指定归档编号（例如 20261022-153000）；不填则检索全部归档
        """
        try:
            hits = store.search(text, archive_id=id)
        except (OSError, ValueError) as exc:
            return ToolResult.failure(f"检索历史上下文失败：{exc}")

        if not hits:
            scope = f"归档 {id}" if id else "全部历史归档"
            return ToolResult.success(f"在{scope}中未找到与“{text}”匹配的内容。")

        scope = f"归档 {id}" if id else "全部历史归档"
        lines = [f"在{scope}中找到 {len(hits)} 条相关记录："]
        for number, hit in enumerate(hits, 1):
            lines.append(
                f"\n[{number}] 归档 {hit.archive_id} · 第 {hit.index} 条 · 角色：{hit.role or '未知'}\n"
                f"{hit.snippet}"
            )
        if len(hits) >= store.max_results:
            lines.append(
                "\n（结果数量已达到上限，无法一次性返回更多内容；"
                "可使用更具体的关键词或指定归档编号再次检索。）"
            )
        return ToolResult.success("\n".join(lines))

    return registry


__all__ = ["register_recall_context_tool"]

"""工具注册表：工具的发现、schema 生成与执行分发。

设计目标
--------
* 业务模块（时间工具、文件工具……）各自提供工具，注册表只负责"登记 + 分发"。
* JSON Schema 默认从函数签名与 docstring 自动生成，避免手写重复的描述；
  也允许显式传入 ``parameters`` 覆盖自动生成的结果。
"""

from __future__ import annotations

import inspect
import types
import typing
from collections.abc import Callable, Iterator, Sequence
from typing import (
    TYPE_CHECKING,
    Any,
    Union,
    get_args,
    get_origin,
)

if TYPE_CHECKING:  # pragma: no cover - 仅用于类型检查
    from ..config import FilesystemConfig

from ..errors import ToolExecutionError, ToolNotFoundError
from .base import ToolResult, ToolSpec

_PRIMITIVE_SCHEMA: dict[Any, dict[str, Any]] = {
    str: {"type": "string"},
    int: {"type": "integer"},
    float: {"type": "number"},
    bool: {"type": "boolean"},
    list: {"type": "array"},
    dict: {"type": "object"},
    type(None): {"type": "null"},
}


def _schema_for_annotation(annotation: Any) -> dict[str, Any]:
    """把 Python 类型注解转换成 JSON Schema 片段。"""
    if annotation is inspect.Parameter.empty:
        return {"type": "string"}

    if annotation in _PRIMITIVE_SCHEMA:
        return dict(_PRIMITIVE_SCHEMA[annotation])

    origin = get_origin(annotation)

    if origin is Union or origin is types.UnionType:
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(args) == 1:
            return _schema_for_annotation(args[0])
        return {"anyOf": [_schema_for_annotation(arg) for arg in args]}

    if origin in (list, set, tuple, frozenset):
        args = get_args(annotation)
        schema: dict[str, Any] = {"type": "array"}
        if args:
            schema["items"] = _schema_for_annotation(args[0])
        return schema

    if origin is dict:
        args = get_args(annotation)
        schema = {"type": "object"}
        if len(args) == 2:
            schema["additionalProperties"] = _schema_for_annotation(args[1])
        return schema

    if isinstance(annotation, type):
        if issubclass(annotation, bool):
            return {"type": "boolean"}
        if issubclass(annotation, int):
            return {"type": "integer"}
        if issubclass(annotation, float):
            return {"type": "number"}
        if issubclass(annotation, str):
            return {"type": "string"}
    return {"type": "string"}


def _parse_docstring(func: Callable[..., Any]) -> tuple[str, dict[str, str]]:
    """解析 docstring，返回（工具描述, 参数描述字典）。

    支持 Google 风格的 ``Args:`` 小节与 Sphinx 风格的 ``:param name:`` 字段。
    """
    doc = inspect.getdoc(func) or ""
    if not doc:
        return "", {}

    lines = doc.splitlines()
    description_lines: list[str] = []
    params: dict[str, str] = {}

    in_args_section = False
    for raw_line in lines:
        stripped = raw_line.strip()
        if stripped.lower() in ("args:", "arguments:", "参数:"):
            in_args_section = True
            continue
        if stripped.lower() in ("returns:", "return:", "raises:", "yields:", "examples:", "example:"):
            in_args_section = False
            continue

        if stripped.startswith(":param"):
            body = stripped.lstrip(":").partition("param")[2]
            name, _, text = body.partition(":")
            params[name.strip()] = text.strip()
            continue

        if in_args_section:
            if stripped and ":" in stripped:
                name, _, text = stripped.partition(":")
                params[name.strip().split(" ")[0]] = text.strip()
            continue

        if stripped:
            description_lines.append(stripped)

    return " ".join(description_lines).strip(), params


def build_parameters_schema(func: Callable[..., Any]) -> dict[str, Any]:
    """根据函数签名自动生成 JSON Schema。"""
    signature = inspect.signature(func)
    try:
        hints = typing.get_type_hints(func)
    except Exception:  # noqa: BLE001 - 注解无法解析时退化为空注解
        hints = {}

    properties: dict[str, Any] = {}
    required: list[str] = []
    _, doc_params = _parse_docstring(func)

    for name, parameter in signature.parameters.items():
        if name in ("self", "cls"):
            continue
        if parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        annotation = hints.get(name, parameter.annotation)
        schema = _schema_for_annotation(annotation)
        if name in doc_params:
            schema["description"] = doc_params[name]
        properties[name] = schema
        if parameter.default is inspect.Parameter.empty:
            required.append(name)

    result: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        result["required"] = required
    return result


class ToolRegistry:
    """工具注册表。

    使用示例::

        registry = ToolRegistry()

        @registry.tool()
        def add(a: int, b: int) -> int:
            '''相加。

            Args:
                a: 第一个加数
                b: 第二个加数
            '''
            return a + b
    """

    def __init__(self, specs: Sequence[ToolSpec] = ()) -> None:
        self._tools: dict[str, ToolSpec] = {}
        for spec in specs:
            self.register(spec)

    # ------------------------------------------------------------------ 注册

    def register(self, spec: ToolSpec) -> ToolSpec:
        """登记一个工具（同名覆盖）。"""
        if not spec.name:
            raise ToolExecutionError("工具名称不能为空")
        self._tools[spec.name] = spec
        return spec

    def tool(
        self,
        name: str | None = None,
        description: str | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """装饰器：把一个函数注册成工具。

        Args:
            name: 工具名，缺省使用函数名。
            description: 工具描述，缺省取 docstring 首段。
            parameters: 显式 JSON Schema，缺省根据签名自动生成。
        """

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            doc_description, _ = _parse_docstring(func)
            spec = ToolSpec(
                name=name or func.__name__,
                description=(description or doc_description or "").strip(),
                parameters=parameters or build_parameters_schema(func),
                handler=func,
            )
            self.register(spec)
            return func

        return decorator

    # ------------------------------------------------------------------ 查询

    def get(self, name: str) -> ToolSpec:
        """按名称获取工具；不存在时抛出 :class:`ToolNotFoundError`。"""
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(f"未知工具：{name}") from exc

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def specs(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def schemas(self) -> list[dict[str, Any]]:
        """导出 OpenAI function calling 所需的 ``tools`` 数组。"""
        return [spec.to_openai_schema() for spec in self._tools.values()]

    # ------------------------------------------------------------------ 执行

    def execute(self, name: str, arguments: dict[str, Any] | None = None) -> ToolResult:
        """执行工具并返回统一结果（不向调用方抛异常）。"""
        try:
            spec = self.get(name)
        except ToolNotFoundError as exc:
            return ToolResult.failure(str(exc))

        kwargs = dict(arguments or {})
        try:
            inspect.signature(spec.handler).bind(**kwargs)
        except TypeError as exc:
            return ToolResult.failure(f"调用参数错误：{exc}")

        try:
            result = spec.handler(**kwargs)
        except Exception as exc:  # noqa: BLE001 - 工具异常统一转换为失败结果
            return ToolResult.failure(f"{type(exc).__name__}: {exc}")

        if isinstance(result, ToolResult):
            return result
        if result is None:
            return ToolResult.success("")
        return ToolResult.success(str(result))

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def __iter__(self) -> Iterator[ToolSpec]:
        return iter(self._tools.values())


def register_builtin_tools(
    registry: ToolRegistry,
    filesystem: FilesystemConfig | None = None,
) -> ToolRegistry:
    """把内置工具（时间 + 文件系统）挂到注册表上。"""
    from ..config import FilesystemConfig
    from .datetime_tools import register_datetime_tools
    from .file_tools import register_file_tools

    register_datetime_tools(registry)
    register_file_tools(registry, filesystem or FilesystemConfig())
    return registry


__all__ = [
    "ToolRegistry",
    "build_parameters_schema",
    "register_builtin_tools",
]

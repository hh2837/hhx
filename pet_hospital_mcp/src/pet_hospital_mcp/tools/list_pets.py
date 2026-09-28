"""``list_pets`` 工具 —— 严格适配 Go REST API 的 ``GET /api/v1/pets``。

只实现并仅保留这一个工具（阶段一）；后续阶段新增工具时，在 ``tools/`` 下新增
模块并提供与这里相同的 ``register(mcp, rest_client)`` 入口即可。
"""

from __future__ import annotations

import json
import time
from typing import Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..errors import ErrorCode, build_error
from ..logging_config import get_logger
from ..rest_client import BackendError, BackendInvalidResponseError, RestClient

logger = get_logger(__name__)

# ============================================================================
# 后端允许值 —— 已按真实 Go 服务校准（来源：GET /api/v1/meta 枚举字典）
# 校准日期：2026-09-20
# ============================================================================

Species = Literal["犬", "猫", "兔", "鸟", "仓鼠", "爬宠", "其他"]
SPECIES_VALUES: tuple[str, ...] = Species.__args__

Status = Literal["待就诊", "就诊中", "住院中", "已康复", "慢性病随访"]
STATUS_VALUES: tuple[str, ...] = Status.__args__

SortBy = Literal[
    "id",
    "name",
    "ownerName",
    "species",
    "doctor",
    "disease",
    "status",
    "totalCost",
    "visitCount",
    "createdAt",
    "updatedAt",
]
SORT_BY_VALUES: tuple[str, ...] = SortBy.__args__

Order = Literal["asc", "desc"]
ORDER_VALUES: tuple[str, ...] = Order.__args__


# ============================================================================
# 输入模型
# ============================================================================

class ListPetsParams(BaseModel):
    """``GET /api/v1/pets`` 的查询参数（与 Go API 逐字段对应，无私有业务参数）。

    严格校验：
    - ``species`` / ``status`` / ``sortBy`` / ``order`` 仅接受后端允许值；
    - ``page >= 1``；
    - ``1 <= pageSize <= 500``；
    - ``min`` / ``max`` 非负有限数，且 ``min <= max``；
    - 拒绝未知字段、NaN、Infinity 与类型不正确的输入。
    """

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )

    q: str | None = Field(default=None, description="全局关键词搜索（如姓名、症状等）")
    name: str | None = Field(default=None, description="按宠物名称精确过滤")
    ownerName: str | None = Field(default=None, description="按主人姓名过滤")
    ownerPhone: str | None = Field(default=None, description="按主人手机号过滤")
    species: Species | None = Field(default=None, description="按物种过滤")
    doctor: str | None = Field(default=None, description="按主治医生过滤")
    disease: str | None = Field(default=None, description="按病症过滤")
    status: Status | None = Field(default=None, description="按就诊状态过滤")
    min: float | None = Field(default=None, ge=0, description="费用区间下限（非负）")
    max: float | None = Field(default=None, ge=0, description="费用区间上限（非负）")
    sortBy: SortBy | None = Field(default=None, description="排序字段")
    order: Order | None = Field(default=None, description="排序方向：asc / desc")
    page: int = Field(default=1, ge=1, description="页码，从 1 开始")
    pageSize: int = Field(default=20, ge=1, le=500, description="每页条数（1-500）")

    @model_validator(mode="after")
    def _check_min_max(self) -> "ListPetsParams":
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min must be less than or equal to max")
        return self


# ============================================================================
# 成功输出模型（对应 Go API 成功响应的 ``data``）
# ============================================================================

class PetCharge(BaseModel):
    """单条收费明细（真实结构：id/item/category/amount/doctor/date）。"""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    item: str | None = None
    category: str | None = None
    amount: float | None = None
    doctor: str | None = None
    date: str | None = None


class PetRecord(BaseModel):
    """单条历史病历（真实结构：id/visitDate/doctor/diagnosis/symptoms/...）。"""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    visitDate: str | None = None
    doctor: str | None = None
    diagnosis: str | None = None
    symptoms: str | None = None
    treatment: str | None = None
    prescription: list[str] | None = None
    weightKg: float | None = None
    temperature: float | None = None
    followUp: str | None = None
    charge: float | None = None
    createdAt: str | None = None


class Pet(BaseModel):
    """单只宠物（真实结构；``records`` / ``charges`` 可能为 ``null`` 或数组）。"""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    name: str | None = None
    species: str | None = None
    breed: str | None = None
    gender: str | None = None
    ageMonths: int | None = None
    color: str | None = None
    chipNo: str | None = None
    ownerName: str | None = None
    ownerPhone: str | None = None
    ownerAddr: str | None = None
    doctor: str | None = None
    disease: str | None = None
    status: str | None = None
    allergy: str | None = None
    records: list[PetRecord] | None = None
    charges: list[PetCharge] | None = None
    totalCost: float | None = None
    visitCount: int | None = None
    createdAt: str | None = None
    updatedAt: str | None = None


class ListPetsData(BaseModel):
    """``GET /api/v1/pets`` 成功响应中 ``data`` 的契约。"""

    model_config = ConfigDict(extra="allow")

    items: list[Pet]
    total: int
    page: int
    pageSize: int
    totalPages: int
    totalCost: float


# ============================================================================
# 工具
# ============================================================================

_TOOL_DESCRIPTION = (
    "查询宠物医院的患者宠物列表，等价于调用上游 Go REST API 的 GET /api/v1/pets。"
    "支持关键词搜索、按姓名/主人/物种/医生/病症/状态过滤、按费用区间（min/max，非负且 min<=max）"
    "过滤、排序（sortBy 可选：id/name/ownerName/species/doctor/disease/status/totalCost/"
    "visitCount/createdAt/updatedAt；order 可选：asc/desc）与分页（page>=1；pageSize 1-500）。"
    "species 可选：犬/猫/兔/鸟/仓鼠/爬宠/其他；"
    "status 可选：待就诊/就诊中/住院中/已康复/慢性病随访。"
    "参数以 JSON 对象传入（字段名与后端查询参数一致，均可选）。"
    "返回 Go API data 中的列表分页结构：items、total、page、pageSize、totalPages、totalCost，"
    "其中每只宠物的 records/charges 可能为 null 或数组，id 为字符串编号（如 PET-000001）。"
    "失败时返回统一错误结构 {error: {code, message, details}}，"
    "code 取值：VALIDATION_ERROR/BACKEND_TIMEOUT/BACKEND_UNAVAILABLE/BACKEND_API_ERROR/"
    "BACKEND_INVALID_RESPONSE/INTERNAL_ERROR。"
)


def _raise_unified(code: ErrorCode, message: str, details: dict[str, Any] | None = None) -> None:
    """抛出携带统一错误 JSON 的 ToolError（SDK 2.x 中消息可原样到达模型）。"""
    raise ToolError(json.dumps(build_error(code, message, details), ensure_ascii=False))


def _extract_data(body: dict[str, Any]) -> dict[str, Any]:
    """从 Go 成功响应信封中提取 ``data`` 对象。"""
    data = body.get("data")
    if not isinstance(data, dict):
        raise BackendInvalidResponseError(
            "response body is missing a valid 'data' object",
            details={"reason": "expected an object at response['data']"},
        )
    return data


def register(mcp: MCPServer, rest_client: RestClient) -> None:
    """在 ``mcp`` 上注册 ``list_pets`` 工具。"""

    @mcp.tool(name="list_pets", description=_TOOL_DESCRIPTION)
    async def list_pets(params: Any) -> ListPetsData:
        """列出宠物（完整参数契约见工具 description）。

        参数类型声明为 ``Any``：所有输入（含非对象、null 等）都进入
        ``ListPetsParams.model_validate`` 统一校验路径，确保任何无效输入都
        返回统一的 ``VALIDATION_ERROR`` 结构（SDK 层不做前置类型拦截）。
        """
        started = time.monotonic()
        status = "ok"
        validated: ListPetsParams | None = None

        try:
            try:
                validated = ListPetsParams.model_validate(params)
            except ValidationError as exc:
                status = ErrorCode.VALIDATION_ERROR.value
                _raise_unified(
                    ErrorCode.VALIDATION_ERROR,
                    "Invalid input parameters",
                    {"errors": _sanitized_errors(exc)},
                )

            query = validated.model_dump(exclude_none=True)
            logger.debug(
                "list_pets_call",
                extra={"tool_name": "list_pets", "params": query},
            )
            body = await rest_client.get("/api/v1/pets", params=query)
            result = ListPetsData.model_validate(_extract_data(body))
        except ToolError:
            raise
        except BackendError as exc:
            status = exc.code.value
            _raise_unified(exc.code, exc.message, exc.details)
        except ValidationError as exc:
            status = ErrorCode.BACKEND_INVALID_RESPONSE.value
            _raise_unified(
                ErrorCode.BACKEND_INVALID_RESPONSE,
                "Backend response does not match the expected data model",
                {"errors": _sanitized_errors(exc)},
            )
        except Exception:
            status = ErrorCode.INTERNAL_ERROR.value
            logger.exception("unexpected_tool_error", extra={"tool_name": "list_pets"})
            _raise_unified(ErrorCode.INTERNAL_ERROR, "Internal server error")
        finally:
            duration_ms = round((time.monotonic() - started) * 1000, 1)
            logger.info(
                "tool_call",
                extra={
                    "tool_name": "list_pets",
                    "params": validated.model_dump() if validated is not None else params,
                    "status": status,
                    "duration_ms": duration_ms,
                },
            )

        return result


def _sanitized_errors(exc: ValidationError) -> list[dict[str, Any]]:
    """把 Pydantic 校验错误收敛为可序列化且不含原始输入值的摘要。"""
    return [
        {"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")}
        for e in exc.errors(include_url=False)
    ]

"""输入模型（ListPetsParams）模型级单测。

覆盖协议层无法送达的边界值（NaN / Infinity 会被 MCP 客户端序列化为 null），
直接在 Pydantic 模型层验证严格拒绝行为。
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from pet_hospital_mcp.tools.list_pets import (
    ORDER_VALUES,
    SORT_BY_VALUES,
    SPECIES_VALUES,
    STATUS_VALUES,
    ListPetsParams,
)


def _rejected(**params) -> ValidationError:
    with pytest.raises(ValidationError):
        ListPetsParams.model_validate(params)
    return ValidationError


async def test_model_accepts_valid_min_max():
    m = ListPetsParams.model_validate({"min": 1.0, "max": 100.0})
    assert m.min == 1.0 and m.max == 100.0


async def test_model_accepts_int_for_float_range():
    m = ListPetsParams.model_validate({"min": 5, "max": 100})
    assert m.min == 5.0 and m.max == 100.0


async def test_model_rejects_nan():
    with pytest.raises(ValidationError):
        ListPetsParams.model_validate({"min": float("nan")})
    with pytest.raises(ValidationError):
        ListPetsParams.model_validate({"max": float("nan")})


async def test_model_rejects_infinity():
    with pytest.raises(ValidationError):
        ListPetsParams.model_validate({"min": float("inf")})
    with pytest.raises(ValidationError):
        ListPetsParams.model_validate({"max": float("-inf")})


async def test_model_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ListPetsParams.model_validate({"mystery": 1})


async def test_model_rejects_min_greater_than_max():
    with pytest.raises(ValidationError):
        ListPetsParams.model_validate({"min": 200.0, "max": 100.0})


async def test_model_rejects_wrong_types():
    with pytest.raises(ValidationError):
        ListPetsParams.model_validate({"page": "5"})
    with pytest.raises(ValidationError):
        ListPetsParams.model_validate({"q": 123})


async def test_allowed_value_constants_are_consistent():
    """允许值常量与 Literal 类型保持一致（与 GET /api/v1/meta 枚举字典一致）。"""
    assert tuple(SPECIES_VALUES) == ("犬", "猫", "兔", "鸟", "仓鼠", "爬宠", "其他")
    assert "待就诊" in STATUS_VALUES
    assert "totalCost" in SORT_BY_VALUES
    assert "visitCount" in SORT_BY_VALUES
    assert ORDER_VALUES == ("asc", "desc")

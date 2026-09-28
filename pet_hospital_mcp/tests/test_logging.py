"""日志脱敏测试：ownerPhone / ownerAddr / chipNo 及其 snake_case 写法递归脱敏。"""

from __future__ import annotations

from pet_hospital_mcp.logging_config import redact


def test_redacts_camel_and_snake_sensitive_keys():
    payload = {
        "tool_name": "list_pets",
        "params": {
            "ownerPhone": "13800000000",
            "ownerAddr": "Chengdu 610000",
            "chipNo": "CHIP-9",
            "owner_phone": "13900000000",
            "owner_addr": "Beijing",
            "chip_no": "CHIP-8",
            "name": "Mimi",  # 普通字段不受影响
        },
    }
    out = redact(payload)
    assert out["params"]["ownerPhone"] == "***"
    assert out["params"]["ownerAddr"] == "***"
    assert out["params"]["chipNo"] == "***"
    assert out["params"]["owner_phone"] == "***"
    assert out["params"]["owner_addr"] == "***"
    assert out["params"]["chip_no"] == "***"
    assert out["params"]["name"] == "Mimi"


def test_redacts_nested_and_list_values():
    payload = {
        "items": [
            {"ownerPhone": "1", "records": [{"doctor": "A", "ownerPhone": "2"}]},
            {"ownerAddr": "3", "charges": []},
        ]
    }
    out = redact(payload)
    assert out["items"][0]["ownerPhone"] == "***"
    assert out["items"][0]["records"][0]["ownerPhone"] == "***"
    assert out["items"][1]["ownerAddr"] == "***"


def test_redact_handles_non_mapping_values():
    assert redact("plain") == "plain"
    assert redact(42) == 42
    assert redact(None) is None
    assert redact([1, "x", {"ownerPhone": "9"}]) == [1, "x", {"ownerPhone": "***"}]

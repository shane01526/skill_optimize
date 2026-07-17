"""程式驗證 gate（jsonschema）：客觀判斷 JSON 是否符合 schema，能真正拉開弱 baseline。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from refiner.e2e_general import _validate_json_schema

_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["id", "amount", "currency"],
    "properties": {
        "id": {"type": "string"},
        "amount": {"type": "number"},
        "currency": {"type": "string", "enum": ["TWD", "USD"]},
    },
}


def test_valid_json_passes():
    ans = '```json\n{"id": "TX-1", "amount": 100, "currency": "USD"}\n```'
    v = _validate_json_schema(ans, _SCHEMA)
    assert v["parsed_ok"] is True
    assert v["schema_valid"] is True
    assert v["error_count"] == 0
    assert v["required_coverage"] == 1.0


def test_missing_required_field_fails():
    ans = '{"id": "TX-1", "amount": 100}'  # 缺 currency
    v = _validate_json_schema(ans, _SCHEMA)
    assert v["schema_valid"] is False
    assert v["required_coverage"] == round(2 / 3, 3)
    assert any("currency" in e for e in v["errors"])


def test_wrong_type_fails():
    ans = '{"id": "TX-1", "amount": "one hundred", "currency": "USD"}'  # amount 應為 number
    v = _validate_json_schema(ans, _SCHEMA)
    assert v["schema_valid"] is False
    assert v["error_count"] >= 1


def test_bad_enum_fails():
    ans = '{"id": "TX-1", "amount": 100, "currency": "JPY"}'  # 不在 enum
    v = _validate_json_schema(ans, _SCHEMA)
    assert v["schema_valid"] is False


def test_non_json_output_fails():
    ans = "這是一段說明文字，沒有 JSON。金額大概一百塊美金。"
    v = _validate_json_schema(ans, _SCHEMA)
    assert v["parsed_ok"] is False
    assert v["schema_valid"] is False
    assert v["required_coverage"] == 0.0

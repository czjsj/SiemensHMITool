# -*- coding: utf-8 -*-
"""Tests for VariableEngine type inference and normalize_data_type."""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.variable_engine import VariableEngine, normalize_data_type
from backend.domain.ir_v2 import ScreenItemSpec
from backend.domain.enums import ScreenItemType


def test_button_tag_type_bool():
    """button -> Bool."""
    ir = {
        "meta": {"screen_name": "TestScreen", "hmi_type": "Comfort"},
        "objects": [
            {"id": "btn_start", "type": "button", "text": "启动", "x": 100, "y": 100, "width": 120, "height": 40},
        ],
        "tags": [],
        "scripts": [],
    }
    engine = VariableEngine()
    result = engine.generate(ir)
    assert result["tags"]
    assert result["tags"][0]["data_type"] == "Bool"


def test_indicator_tag_type_bool():
    """indicator -> Bool."""
    ir = {
        "meta": {"screen_name": "TestScreen", "hmi_type": "Comfort"},
        "objects": [
            {"id": "ind_run", "type": "indicator", "text": "运行", "x": 100, "y": 100, "width": 60, "height": 60},
        ],
        "tags": [],
        "scripts": [],
    }
    engine = VariableEngine()
    result = engine.generate(ir)
    assert result["tags"]
    assert result["tags"][0]["data_type"] == "Bool"


def test_symbolic_io_tag_type_int():
    """symbolic_io_field -> Int."""
    ir = {
        "meta": {"screen_name": "TestScreen", "hmi_type": "Comfort"},
        "objects": [
            {"id": "sio_mode", "type": "symbolic_io_field", "text": "模式选择", "x": 100, "y": 100, "width": 120, "height": 40},
        ],
        "tags": [],
        "scripts": [],
    }
    engine = VariableEngine()
    result = engine.generate(ir)
    assert result["tags"]
    assert result["tags"][0]["data_type"] == "Int"


def test_io_field_explicit_data_type_real():
    """io_field with data_type='Real' -> Real (via infer_tag_data_type_for_item)."""
    engine = VariableEngine()
    item = ScreenItemSpec(
        id="io_temp",
        name="io_temp",
        type=ScreenItemType.IO_FIELD,
        properties={"data_type": "Real"},
    )
    result = engine.infer_tag_data_type_for_item(item)
    assert result == "Real"


def test_io_field_text_speed_setting_real():
    """io_field with text '速度设定' -> Real (via infer_tag_data_type_for_item)."""
    engine = VariableEngine()
    item = ScreenItemSpec(
        id="io_speed",
        name="io_speed",
        type=ScreenItemType.IO_FIELD,
        text={"zh-CN": "速度设定"},
    )
    result = engine.infer_tag_data_type_for_item(item)
    assert result == "Real"


def test_io_field_no_hint_default_int():
    """io_field without hint -> Int."""
    ir = {
        "meta": {"screen_name": "TestScreen", "hmi_type": "Comfort"},
        "objects": [
            {"id": "io_count", "type": "io_field", "text": "计数", "x": 100, "y": 100, "width": 120, "height": 40},
        ],
        "tags": [],
        "scripts": [],
    }
    engine = VariableEngine()
    result = engine.generate(ir)
    assert result["tags"]
    assert result["tags"][0]["data_type"] == "Int"


def test_normalize_data_type_bool_variants():
    """normalize_data_type handles bool variants."""
    assert normalize_data_type("bool") == "Bool"
    assert normalize_data_type("BOOLEAN") == "Bool"
    assert normalize_data_type("Bit") == "Bool"


def test_normalize_data_type_int_variants():
    """normalize_data_type handles int variants."""
    assert normalize_data_type("int") == "Int"
    assert normalize_data_type("Integer") == "Int"
    assert normalize_data_type("Short") == "Int"


def test_normalize_data_type_real_variants():
    """normalize_data_type handles real variants."""
    assert normalize_data_type("real") == "Real"
    assert normalize_data_type("Float") == "Real"
    assert normalize_data_type("Double") == "Real"


def test_normalize_data_type_string_variants():
    """normalize_data_type handles string variants."""
    assert normalize_data_type("string") == "String"
    assert normalize_data_type("Str") == "String"


def test_normalize_data_type_fallback():
    """normalize_data_type returns fallback for empty/unknown."""
    assert normalize_data_type(None) == "Int"
    assert normalize_data_type("") == "Int"
    assert normalize_data_type("unknown_type") == "Int"
    assert normalize_data_type(None, fallback="Bool") == "Bool"

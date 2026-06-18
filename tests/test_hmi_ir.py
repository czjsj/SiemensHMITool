# -*- coding: utf-8 -*-
"""测试 IR 校验模块：新增字段兼容性。"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.hmi_ir import validate_ir, IRValidationError


def test_validate_ir_basic():
    """基本 IR 校验正常通过。"""
    ir = {
        "meta": {"screen_name": "Test_1", "title": "测试", "resolution": "1280x800", "hmi_type": "Comfort"},
        "objects": [{"id": "TXT_Hello", "type": "Text", "x": 10, "y": 20, "width": 200, "height": 40, "text": "你好"}],
        "tags": [],
    }
    result = validate_ir(ir)
    assert result["meta"]["screen_name"] == "Test_1"
    assert len(result["objects"]) == 1


def test_validate_ir_accepts_generation_mode():
    """IR 应接受并归一化 generation_mode 字段。"""
    ir = {
        "meta": {"screen_name": "T1", "generation_mode": "unified_direct"},
        "objects": [{"id": "TXT_A", "type": "Text", "x": 0, "y": 0, "text": "A"}],
    }
    result = validate_ir(ir)
    assert result["meta"]["generation_mode"] == "unified_direct"


def test_validate_ir_defaults_generation_mode():
    """未提供 generation_mode 时默认 auto。"""
    ir = {
        "meta": {"screen_name": "T1"},
        "objects": [{"id": "TXT_A", "type": "Text", "x": 0, "y": 0, "text": "A"}],
    }
    result = validate_ir(ir)
    assert result["meta"]["generation_mode"] == "auto"


def test_validate_ir_invalid_generation_mode_falls_back():
    """非法的 generation_mode 应回退到 auto。"""
    ir = {
        "meta": {"screen_name": "T1", "generation_mode": "invalid_mode"},
        "objects": [{"id": "TXT_A", "type": "Text", "x": 0, "y": 0, "text": "A"}],
    }
    result = validate_ir(ir)
    assert result["meta"]["generation_mode"] == "auto"


def test_validate_ir_accepts_template_fields():
    """meta 中应保留 template_screen 和 template_xml 可选字段。"""
    ir = {
        "meta": {
            "screen_name": "T1",
            "template_screen": "Template_Motor",
            "template_xml": "exports/templates/Template_Motor_template.xml",
        },
        "objects": [{"id": "TXT_A", "type": "Text", "x": 0, "y": 0, "text": "A"}],
    }
    result = validate_ir(ir)
    assert result["meta"]["template_screen"] == "Template_Motor"
    assert result["meta"]["template_xml"] == "exports/templates/Template_Motor_template.xml"


def test_validate_ir_accepts_template_ref():
    """对象应接受 template_ref 可选字段。"""
    ir = {
        "meta": {"screen_name": "T1"},
        "objects": [
            {"id": "BTN_Start", "type": "Button", "x": 100, "y": 200, "width": 120, "height": 50, "text": "启动", "template_ref": "BTN_Template"},
        ],
    }
    result = validate_ir(ir)
    obj = result["objects"][0]
    assert obj.get("template_ref") == "BTN_Template"


def test_validate_ir_rejects_empty_objects():
    """objects 为空时应抛出异常。"""
    ir = {"meta": {"screen_name": "T1"}, "objects": []}
    with pytest.raises(IRValidationError, match="为空"):
        validate_ir(ir)


def test_validate_ir_all_object_types():
    """所有 5 种对象类型应都能通过校验。"""
    ir = {
        "meta": {"screen_name": "Full_Test"},
        "tags": [
            {"name": "Tag_Bool", "data_type": "Bool"},
            {"name": "Tag_Real", "data_type": "Real"},
            {"name": "Tag_Int", "data_type": "Int"},
        ],
        "text_lists": [
            {"name": "Mode_List", "entries": [{"value": 0, "text": "Off"}, {"value": 1, "text": "On"}]},
        ],
        "scripts": [
            {"name": "Sub_Test", "language": "VBS", "purpose": "test", "code": "SmartTags(\"Tag_Bool\") = 1"},
        ],
        "objects": [
            {"id": "IO_Speed", "type": "IOField", "x": 100, "y": 100, "width": 140, "height": 40, "mode": "Output", "process_tag": "Tag_Real", "display_format": "Decimal", "decimal_digits": 2, "label": "速度", "unit": "rpm"},
            {"id": "SIO_Mode", "type": "SymbolicIOField", "x": 100, "y": 160, "width": 160, "height": 40, "mode": "Output", "process_tag": "Tag_Int", "text_list": "Mode_List", "label": "模式"},
            {"id": "BTN_Start", "type": "Button", "x": 100, "y": 220, "width": 120, "height": 50, "text": "启动", "press_script": "Sub_Test", "background_color": "#2BB673"},
            {"id": "LMP_Run", "type": "Indicator", "x": 400, "y": 100, "radius": 22, "process_tag": "Tag_Bool", "color_on": "#27D17F", "color_off": "#3A4250", "blink": False, "label": "运行"},
            {"id": "TXT_Title", "type": "Text", "x": 600, "y": 30, "width": 320, "height": 40, "text": "标题", "font_size": 24, "bold": True, "color": "#E6EDF3"},
        ],
    }
    result = validate_ir(ir)
    assert len(result["objects"]) == 5
    assert result["meta"]["generation_mode"] == "auto"

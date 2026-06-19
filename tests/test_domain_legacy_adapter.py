# -*- coding: utf-8 -*-
"""测试 LegacyIrAdapter — 旧 IR dict 到 HmiProjectSpec 的转换。"""
import sys
import os
import pytest
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.domain.legacy_adapter import LegacyIrAdapter
from backend.domain.ir_v2 import HmiProjectSpec
from backend.domain.enums import (
    HmiFamily,
    ScreenItemType,
    BindingKind,
    SemanticEvent,
    SemanticActionType,
    TagScope,
)
from backend.domain.diagnostics import DiagnosticCodes
from backend.domain.validation import validate_ir_v2


# ---------------------------------------------------------------------------
# 旧 IR fixtures（模拟 validate_ir + VariableEngine 输出）
# ---------------------------------------------------------------------------

def make_minimal_legacy_ir(**overrides) -> dict:
    """构建最小可用的旧 IR 结构。"""
    ir = {
        "meta": {
            "screen_name": "Screen_1",
            "title": "测试画面",
            "description": "",
            "resolution": "1280x800",
            "hmi_type": "Comfort",
            "generation_mode": "auto",
            "template_screen": "",
            "template_xml": "",
        },
        "tags": [],
        "text_lists": [],
        "scripts": [],
        "objects": [
            {
                "id": "TXT_Hello",
                "type": "Text",
                "x": 100,
                "y": 50,
                "width": 200,
                "height": 40,
                "text": "你好",
                "font_size": 18,
                "bold": False,
                "color": "#E6EDF3",
            },
        ],
        "_screen_size": {"width": 1280, "height": 800},
        "_warnings": [],
    }
    ir.update(overrides)
    return ir


def make_motor_control_ir() -> dict:
    """电机控制画面完整旧 IR — 与方案文档 §25 场景对齐。"""
    return {
        "meta": {
            "screen_name": "Motor_Control",
            "title": "电机控制",
            "resolution": "800x480",
            "hmi_type": "Comfort",
        },
        "tags": [
            {"name": "Motor_Start", "data_type": "Bool", "address": "DB1.Motor.Start", "comment": "启动"},
            {"name": "Motor_Stop", "data_type": "Bool", "address": "DB1.Motor.Stop", "comment": "停止"},
            {"name": "Motor_Reset", "data_type": "Bool", "address": "DB1.Motor.Reset", "comment": "复位"},
            {"name": "Motor_AutoMode", "data_type": "Bool", "address": "DB1.Motor.AutoMode", "comment": "自动模式"},
            {"name": "Motor_Running", "data_type": "Bool", "address": "DB1.Motor.Running", "comment": "运行"},
            {"name": "Motor_Fault", "data_type": "Bool", "address": "DB1.Motor.Fault", "comment": "故障"},
            {"name": "Motor_SpeedSP", "data_type": "Real", "address": "DB1.Motor.SpeedSP", "comment": "速度设定"},
            {"name": "Motor_SpeedPV", "data_type": "Real", "address": "DB1.Motor.SpeedPV", "comment": "实际速度"},
            {"name": "Screen_Enable", "data_type": "Bool", "address": "", "comment": "屏幕使能（内部）"},
        ],
        "objects": [
            {
                "id": "TXT_Title",
                "type": "Text",
                "x": 300, "y": 10,
                "width": 200, "height": 36,
                "text": "电机控制",
                "font_size": 22,
                "bold": True,
                "color": "#E6EDF3",
            },
            {
                "id": "BTN_Start",
                "type": "Button",
                "x": 50, "y": 80,
                "width": 100, "height": 50,
                "text": "启动",
                "process_tag": "Motor_Start",
                "tag_mode": "momentary",
                "background_color": "#2BB673",
            },
            {
                "id": "BTN_Stop",
                "type": "Button",
                "x": 180, "y": 80,
                "width": 100, "height": 50,
                "text": "停止",
                "process_tag": "Motor_Stop",
                "tag_mode": "momentary",
                "background_color": "#E25563",
            },
            {
                "id": "BTN_Reset",
                "type": "Button",
                "x": 310, "y": 80,
                "width": 100, "height": 50,
                "text": "复位",
                "process_tag": "Motor_Reset",
                "tag_mode": "momentary",
                "background_color": "#FFB300",
            },
            {
                "id": "BTN_Mode",
                "type": "Button",
                "x": 440, "y": 80,
                "width": 100, "height": 50,
                "text": "手/自动",
                "process_tag": "Motor_AutoMode",
                "tag_mode": "toggle",
                "background_color": "#29B6F6",
            },
            {
                "id": "STS_Run",
                "type": "Indicator",
                "x": 80, "y": 200,
                "radius": 22,
                "process_tag": "Motor_Running",
                "color_on": "#27D17F",
                "color_off": "#3A4250",
                "blink": False,
                "label": "运行",
            },
            {
                "id": "LMP_Fault",
                "type": "Indicator",
                "x": 200, "y": 200,
                "radius": 22,
                "process_tag": "Motor_Fault",
                "color_on": "#E25563",
                "color_off": "#3A4250",
                "blink": True,
                "label": "故障",
            },
            {
                "id": "IO_SpeedSP",
                "type": "IOField",
                "x": 80, "y": 280,
                "width": 140, "height": 40,
                "mode": "InputOutput",
                "process_tag": "Motor_SpeedSP",
                "display_format": "Decimal",
                "decimal_digits": 1,
                "label": "速度设定",
                "unit": "rpm",
            },
            {
                "id": "IO_SpeedPV",
                "type": "IOField",
                "x": 280, "y": 280,
                "width": 140, "height": 40,
                "mode": "Output",
                "process_tag": "Motor_SpeedPV",
                "display_format": "Decimal",
                "decimal_digits": 1,
                "label": "实际速度",
                "unit": "rpm",
            },
        ],
        "_screen_size": {"width": 800, "height": 480},
    }


# ---------------------------------------------------------------------------
# 测试
# ---------------------------------------------------------------------------


class TestLegacyIrAdapterBasic:
    """基本转换功能。"""

    def test_convert_minimal_ir(self):
        """最小旧 IR 可以成功转换。"""
        ir = make_minimal_legacy_ir()
        adapter = LegacyIrAdapter()
        project, diags = adapter.convert(ir)

        assert isinstance(project, HmiProjectSpec)
        assert project.schema_version == "2.0"
        assert project.metadata.project_name == "Screen_1"
        assert project.target.family == HmiFamily.COMFORT
        assert len(project.screens) == 1
        assert len(project.screens[0].items) == 1

    def test_convert_invalid_input(self):
        """非 dict 输入不崩溃，返回空 project。"""
        adapter = LegacyIrAdapter()
        project, diags = adapter.convert("not_a_dict")  # type: ignore
        assert project.metadata.project_name == "__empty__"
        assert any(d.code == "IR_VALIDATION_ERROR" for d in diags)

    def test_convert_empty_dict(self):
        """空 dict 不崩溃。"""
        adapter = LegacyIrAdapter()
        project, diags = adapter.convert({})
        assert project.schema_version == "2.0"

    def test_converts_hmi_type_to_family(self):
        """旧 hmi_type 正确映射到 HmiFamily。"""
        for hmi_type, expected_family in [
            ("Comfort", HmiFamily.COMFORT),
            ("Basic", HmiFamily.BASIC),
            ("Unified", HmiFamily.UNIFIED),
        ]:
            ir = make_minimal_legacy_ir()
            ir["meta"]["hmi_type"] = hmi_type
            project, _ = LegacyIrAdapter().convert(ir)
            assert project.target.family == expected_family


class TestLegacyIrAdapterTags:
    """变量转换。"""

    def test_converts_tags(self):
        ir = make_minimal_legacy_ir()
        ir["tags"] = [
            {"name": "Tag_Bool", "data_type": "Bool", "address": "M1.0", "comment": "布尔变量"},
            {"name": "Tag_Real", "data_type": "Real", "address": "DB1.Speed", "comment": "实型变量"},
            {"name": "Tag_Internal", "data_type": "Bool", "address": "", "comment": ""},
        ]
        project, diags = LegacyIrAdapter().convert(ir)

        assert len(project.tags) == 3
        assert project.tags[0].name == "Tag_Bool"
        assert project.tags[0].data_type == "Bool"
        assert project.tags[0].scope == TagScope.EXTERNAL  # 有 address
        assert project.tags[2].scope == TagScope.INTERNAL  # 无 address

    def test_duplicate_tags_handled(self):
        """重复变量名只保留第一个。"""
        ir = make_minimal_legacy_ir()
        ir["tags"] = [
            {"name": "Tag_A", "data_type": "Bool"},
            {"name": "Tag_A", "data_type": "Real"},
        ]
        project, diags = LegacyIrAdapter().convert(ir)
        assert len(project.tags) == 1
        # 应有重复警告
        assert any("重复" in d.message for d in diags)

    def test_nameless_tag_skip(self):
        """无名称的变量跳过并记录诊断。"""
        ir = make_minimal_legacy_ir()
        ir["tags"] = [{"name": "", "data_type": "Bool"}]
        project, diags = LegacyIrAdapter().convert(ir)
        assert len(project.tags) == 0
        assert any("无名称" in d.message for d in diags)


class TestLegacyIrAdapterObjects:
    """对象转换。"""

    def test_converts_all_object_types(self):
        """所有 5 种对象类型正确转换。"""
        ir = make_minimal_legacy_ir()
        ir["objects"] = [
            {"id": "BTN_Test", "type": "Button", "x": 10, "y": 10, "width": 120, "height": 50,
             "text": "按钮", "process_tag": "Tag_Bool", "tag_mode": "momentary"},
            {"id": "IO_Test", "type": "IOField", "x": 10, "y": 70, "width": 140, "height": 40,
             "process_tag": "Tag_Real", "mode": "Output", "display_format": "Decimal"},
            {"id": "SIO_Test", "type": "SymbolicIOField", "x": 10, "y": 120, "width": 160, "height": 40,
             "process_tag": "Tag_Int", "mode": "Output", "text_list": "Mode_List"},
            {"id": "STS_Test", "type": "Indicator", "x": 400, "y": 10, "radius": 22,
             "process_tag": "Tag_I", "color_on": "#27D17F", "color_off": "#3A4250", "blink": False},
            {"id": "TXT_Test", "type": "Text", "x": 100, "y": 200, "width": 200, "height": 40,
             "text": "标题", "font_size": 18, "bold": False},
        ]
        project, diags = LegacyIrAdapter().convert(ir)
        items = project.screens[0].items
        assert len(items) == 5

        btn = next(it for it in items if it.type == ScreenItemType.BUTTON)
        assert btn.tag_binding == "Tag_Bool"

        io = next(it for it in items if it.type == ScreenItemType.IO_FIELD)
        assert io.properties["mode"] == "Output"

        indicator = next(it for it in items if it.type == ScreenItemType.INDICATOR)
        assert indicator.properties["color_on"] == "#27D17F"

        text = next(it for it in items if it.type == ScreenItemType.TEXT)
        assert text.text["zh-CN"] == "标题"

    def test_button_momentary_generates_press_release_events(self):
        """momentary 按钮生成 press + release 事件。"""
        ir = make_minimal_legacy_ir()
        ir["objects"] = [
            {"id": "BTN_Go", "type": "Button", "x": 10, "y": 10, "width": 120, "height": 50,
             "text": "执行", "process_tag": "Tag_Bool", "tag_mode": "momentary"},
        ]
        project, _ = LegacyIrAdapter().convert(ir)
        item = project.screens[0].items[0]
        events = item.events
        assert len(events) == 2
        assert events[0].event == SemanticEvent.PRESS
        assert events[0].actions[0].type == SemanticActionType.SET_BIT
        assert events[1].event == SemanticEvent.RELEASE
        assert events[1].actions[0].type == SemanticActionType.RESET_BIT

    def test_button_toggle_generates_click_toggle_event(self):
        """toggle 按钮生成 click + toggle 事件。"""
        ir = make_minimal_legacy_ir()
        ir["objects"] = [
            {"id": "MEM_Switch", "type": "Button", "x": 10, "y": 10, "width": 120, "height": 50,
             "text": "切换", "process_tag": "Tag_Bool", "tag_mode": "toggle"},
        ]
        project, _ = LegacyIrAdapter().convert(ir)
        item = project.screens[0].items[0]
        events = item.events
        assert len(events) == 1
        assert events[0].event == SemanticEvent.CLICK
        assert events[0].actions[0].type == SemanticActionType.TOGGLE_BIT

    def test_indicator_generates_color_binding(self):
        """Indicator 生成离散颜色绑定。"""
        ir = make_minimal_legacy_ir()
        ir["objects"] = [
            {"id": "STS_Run", "type": "Indicator", "x": 100, "y": 100, "radius": 22,
             "process_tag": "Running", "color_on": "#27D17F", "color_off": "#3A4250", "blink": False},
        ]
        project, _ = LegacyIrAdapter().convert(ir)
        item = project.screens[0].items[0]
        bindings = item.bindings
        assert len(bindings) >= 1
        color_binding = next(b for b in bindings if b.property == "background_color")
        assert color_binding.kind == BindingKind.DISCRETE
        assert len(color_binding.config["states"]) == 2

    def test_indicator_blink_generates_flashing_binding(self):
        """blink Indicator 生成闪烁绑定。"""
        ir = make_minimal_legacy_ir()
        ir["objects"] = [
            {"id": "LMP_Alarm", "type": "Indicator", "x": 100, "y": 100, "radius": 22,
             "process_tag": "Fault", "color_on": "#E25563", "color_off": "#3A4250", "blink": True},
        ]
        project, _ = LegacyIrAdapter().convert(ir)
        item = project.screens[0].items[0]
        flash_bindings = [b for b in item.bindings if b.kind == BindingKind.FLASHING]
        assert len(flash_bindings) == 1
        assert flash_bindings[0].source_tag == "Fault"

    def test_unknown_object_type_warns(self):
        """未知对象类型产生警告但不崩溃。"""
        ir = make_minimal_legacy_ir()
        ir["objects"] = [
            {"id": "UNK_X", "type": "AlarmView", "x": 0, "y": 0},
        ]
        project, diags = LegacyIrAdapter().convert(ir)
        assert len(project.screens[0].items) == 0  # 已跳过
        assert any("无 V2 对应类型" in d.message for d in diags)


class TestLegacyIrAdapterScripts:
    """脚本转换。"""

    def test_converts_scripts(self):
        ir = make_minimal_legacy_ir()
        ir["scripts"] = [
            {"name": "Sub_Toggle", "language": "VBS", "purpose": "翻转变量", "code": "SmartTags(\"X\") = Not SmartTags(\"X\")"},
        ]
        project, diags = LegacyIrAdapter().convert(ir)
        assert len(project.scripts) == 1
        assert project.scripts[0].name == "Sub_Toggle"


class TestLegacyIrAdapterTextLists:
    """文本列表转换为 ResourceSpec。"""

    def test_converts_text_lists(self):
        ir = make_minimal_legacy_ir()
        ir["text_lists"] = [
            {"name": "Mode_List", "entries": [
                {"value": 0, "text": "手动"},
                {"value": 1, "text": "自动"},
            ]},
        ]
        project, diags = LegacyIrAdapter().convert(ir)
        assert len(project.resources) == 1
        assert project.resources[0].name == "Mode_List"
        assert project.resources[0].kind == "text_list"


class TestLegacyIrAdapterMotorControl:
    """完整电机控制画面集成测试。"""

    def test_full_motor_control_converts(self):
        """电机控制场景完整转换。"""
        ir = make_motor_control_ir()
        project, diags = LegacyIrAdapter().convert(ir)

        assert project.metadata.project_name == "Motor_Control"
        assert project.target.family == HmiFamily.COMFORT
        assert len(project.tags) == 9
        assert len(project.screens) == 1

        screen = project.screens[0]
        assert screen.width == 800
        assert screen.height == 480
        assert len(screen.items) == 9

        # 检查对象类型分布
        types = [item.type for item in screen.items]
        assert types.count(ScreenItemType.BUTTON) == 4
        assert types.count(ScreenItemType.INDICATOR) == 2
        assert types.count(ScreenItemType.IO_FIELD) == 2
        assert types.count(ScreenItemType.TEXT) == 1

    def test_motor_control_v2_passes_validation(self):
        """转换后的 V2 项目能通过 validate_ir_v2。"""
        ir = make_motor_control_ir()
        project, diags = LegacyIrAdapter().convert(ir)

        val_diags = validate_ir_v2(project)
        errors = [d for d in val_diags if d.severity.value == "error"]
        assert len(errors) == 0, f"不应有校验错误: {errors}"

    def test_motor_control_v2_json_roundtrip(self):
        """转换后的 V2 项目可 JSON 序列化再反序列化。"""
        ir = make_motor_control_ir()
        project, _ = LegacyIrAdapter().convert(ir)

        json_str = project.model_dump_json()
        restored = HmiProjectSpec.model_validate_json(json_str)
        assert restored.schema_version == "2.0"
        assert len(restored.screens[0].items) == 9

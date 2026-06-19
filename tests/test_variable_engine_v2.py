# -*- coding: utf-8 -*-
"""测试 PR-02: VariableEngine 语义化 — enrich() 输出 HmiProjectSpec。"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.variable_engine import VariableEngine, enrich_to_v2, auto_bind_variables
from backend.domain.ir_v2 import HmiProjectSpec
from backend.domain.enums import (
    ScreenItemType,
    SemanticEvent,
    SemanticActionType,
    BindingKind,
    TagScope,
    HmiFamily,
)


# ---------------------------------------------------------------------------
# 共享 fixtures
# ---------------------------------------------------------------------------

def make_button_ir(tag_mode="momentary"):
    return {
        "meta": {"screen_name": "Test", "resolution": "800x480", "hmi_type": "Comfort"},
        "objects": [
            {"id": "BTN_Go", "type": "Button", "x": 100, "y": 200,
             "width": 120, "height": 50, "text": "执行", "tag_mode": tag_mode},
        ],
        "_screen_size": {"width": 800, "height": 480},
    }


def make_motor_ir():
    return {
        "meta": {"screen_name": "Motor_Ctrl", "resolution": "800x480", "hmi_type": "Comfort"},
        "objects": [
            {"id": "TXT_Title", "type": "Text", "x": 300, "y": 10,
             "width": 200, "height": 36, "text": "电机控制", "font_size": 22, "bold": True},
            {"id": "BTN_Start", "type": "Button", "x": 50, "y": 80,
             "width": 100, "height": 50, "text": "启动", "tag_mode": "momentary"},
            {"id": "BTN_Stop", "type": "Button", "x": 180, "y": 80,
             "width": 100, "height": 50, "text": "停止", "tag_mode": "momentary"},
            {"id": "BTN_Mode", "type": "Button", "x": 310, "y": 80,
             "width": 100, "height": 50, "text": "手/自动", "tag_mode": "toggle"},
            {"id": "STS_Run", "type": "Indicator", "x": 80, "y": 200,
             "radius": 22, "label": "运行", "color_on": "#27D17F", "color_off": "#3A4250"},
            {"id": "LMP_Fault", "type": "Indicator", "x": 200, "y": 200,
             "radius": 22, "label": "故障", "color_on": "#E25563", "color_off": "#3A4250",
             "blink": True},
            {"id": "IO_Speed", "type": "IOField", "x": 80, "y": 280,
             "width": 140, "height": 40, "mode": "Output",
             "display_format": "Decimal", "decimal_digits": 1, "label": "速度", "unit": "rpm"},
        ],
        "_screen_size": {"width": 800, "height": 480},
    }


# ---------------------------------------------------------------------------
# 测试 enrich() — 新 V3.0 API
# ---------------------------------------------------------------------------

class TestVariableEngineEnrich:
    """VariableEngine.enrich() 测试。"""

    def test_enrich_returns_hmi_project_spec(self):
        """enrich() 返回 HmiProjectSpec 实例。"""
        ir = make_button_ir()
        engine = VariableEngine()
        project = engine.enrich(ir)
        assert isinstance(project, HmiProjectSpec)
        assert project.schema_version == "2.0"
        assert len(project.screens) == 1
        assert len(project.screens[0].items) == 1

    def test_enrich_button_momentary_generates_semantic_actions(self):
        """momentary 按钮 → SET_BIT + RESET_BIT 语义动作（无 VBS）。"""
        ir = make_button_ir("momentary")
        engine = VariableEngine()
        project = engine.enrich(ir)

        item = project.screens[0].items[0]
        assert item.type == ScreenItemType.BUTTON

        # 有 press + release 事件
        events = item.events
        assert len(events) == 2
        assert events[0].event == SemanticEvent.PRESS
        assert events[0].actions[0].type == SemanticActionType.SET_BIT
        assert events[0].actions[0].value == 1

        assert events[1].event == SemanticEvent.RELEASE
        assert events[1].actions[0].type == SemanticActionType.RESET_BIT
        assert events[1].actions[0].value == 0

    def test_enrich_button_toggle_generates_toggle_action(self):
        """toggle 按钮 → TOGGLE_BIT 语义动作。"""
        ir = make_button_ir("toggle")
        engine = VariableEngine()
        project = engine.enrich(ir)

        item = project.screens[0].items[0]
        events = item.events
        assert len(events) == 1
        assert events[0].event == SemanticEvent.CLICK
        assert events[0].actions[0].type == SemanticActionType.TOGGLE_BIT

    def test_enrich_button_auto_detects_toggle_from_text(self):
        """从文本关键词自动检测 toggle 按钮。"""
        ir = make_button_ir()
        # 不显式设 tag_mode，靠文本 "手/自动" 检测
        ir["objects"][0] = {
            "id": "BTN_Switch", "type": "Button", "x": 10, "y": 10,
            "width": 120, "height": 50, "text": "手动/自动",
        }
        engine = VariableEngine()
        project = engine.enrich(ir)
        item = project.screens[0].items[0]
        assert item.properties.get("tag_mode") == "toggle"
        assert item.events[0].actions[0].type == SemanticActionType.TOGGLE_BIT

    def test_enrich_indicator_generates_color_binding(self):
        """Indicator → 离散颜色 BindingSpec。"""
        ir = {
            "meta": {"screen_name": "Test"},
            "objects": [
                {"id": "STS_Run", "type": "Indicator", "x": 100, "y": 100,
                 "radius": 22, "label": "运行",
                 "color_on": "#27D17F", "color_off": "#3A4250"},
            ],
            "_screen_size": {"width": 800, "height": 480},
        }
        engine = VariableEngine()
        project = engine.enrich(ir)
        item = project.screens[0].items[0]

        color_bindings = [b for b in item.bindings if b.property == "background_color"]
        assert len(color_bindings) >= 1
        assert color_bindings[0].kind == BindingKind.DISCRETE
        assert len(color_bindings[0].config["states"]) == 2

    def test_enrich_indicator_alarm_generates_flashing_binding(self):
        """报警 Indicator → 闪烁 BindingSpec。"""
        ir = {
            "meta": {"screen_name": "Test"},
            "objects": [
                {"id": "LMP_Fault", "type": "Indicator", "x": 100, "y": 100,
                 "radius": 22, "label": "故障",
                 "color_on": "#E25563", "color_off": "#3A4250", "blink": True},
            ],
            "_screen_size": {"width": 800, "height": 480},
        }
        engine = VariableEngine()
        project = engine.enrich(ir)
        item = project.screens[0].items[0]

        flash_bindings = [b for b in item.bindings if b.kind == BindingKind.FLASHING]
        assert len(flash_bindings) >= 1

    def test_enrich_iofield_generates_tag_and_binding(self):
        """IOField → TagSpec + DIRECT_TAG BindingSpec。"""
        ir = {
            "meta": {"screen_name": "Test"},
            "objects": [
                {"id": "IO_Speed", "type": "IOField", "x": 80, "y": 280,
                 "width": 140, "height": 40, "mode": "Output",
                 "display_format": "Decimal", "decimal_digits": 1,
                 "label": "速度"},
            ],
            "_screen_size": {"width": 800, "height": 480},
        }
        engine = VariableEngine()
        project = engine.enrich(ir)
        item = project.screens[0].items[0]

        assert item.tag_binding is not None
        assert any(t.name == item.tag_binding for t in project.tags)
        item_tag = next(t for t in project.tags if t.name == item.tag_binding)
        assert item_tag.data_type == "Real"  # decimal_digits=1 → Real

    def test_enrich_creates_tags_in_project(self):
        """enrich 在 project.tags 中创建推断的变量。"""
        ir = make_motor_ir()
        engine = VariableEngine()
        project = engine.enrich(ir)

        # 应该有 BTN_Start, BTN_Stop, BTN_Mode, STS_Run, LMP_Fault, IO_Speed 对应的变量
        tag_names = {t.name for t in project.tags}
        assert len(tag_names) >= 6

    def test_enrich_respects_existing_tag_binding(self):
        """已有 process_tag 的对象不覆盖。"""
        ir = make_button_ir()
        ir["objects"][0]["process_tag"] = "MyCustomTag"
        engine = VariableEngine()
        project = engine.enrich(ir)

        item = project.screens[0].items[0]
        assert item.tag_binding == "MyCustomTag"

    def test_enrich_text_not_modified(self):
        """Text 对象不变量绑定。"""
        ir = {
            "meta": {"screen_name": "Test"},
            "objects": [
                {"id": "TXT_Hello", "type": "Text", "x": 10, "y": 20,
                 "width": 200, "height": 40, "text": "Hello"},
            ],
            "_screen_size": {"width": 800, "height": 480},
        }
        engine = VariableEngine()
        project = engine.enrich(ir)
        item = project.screens[0].items[0]
        assert item.tag_binding is None
        assert len(item.events) == 0
        assert len(item.bindings) == 0

    def test_enrich_full_motor_control(self):
        """完整电机控制场景 enrich。"""
        ir = make_motor_ir()
        engine = VariableEngine()
        project = engine.enrich(ir)

        items = project.screens[0].items
        assert len(items) == 7

        # 按钮有语义事件
        buttons = [it for it in items if it.type == ScreenItemType.BUTTON]
        assert len(buttons) == 3
        for btn in buttons:
            assert len(btn.events) > 0

        # Indicators 有颜色绑定
        indicators = [it for it in items if it.type == ScreenItemType.INDICATOR]
        assert len(indicators) == 2
        for ind in indicators:
            color_bindings = [b for b in ind.bindings if b.property == "background_color"]
            assert len(color_bindings) >= 1

    def test_enrich_to_v2_convenience(self):
        """enrich_to_v2() 便捷函数正常工作。"""
        ir = make_button_ir()
        project = enrich_to_v2(ir)
        assert isinstance(project, HmiProjectSpec)


# ---------------------------------------------------------------------------
# 测试 generate() — 旧兼容入口
# ---------------------------------------------------------------------------

class TestVariableEngineGenerateBackwardCompat:
    """generate() 旧兼容入口测试。"""

    def test_generate_still_works(self):
        """generate() 仍返回旧格式 dict。"""
        ir = make_button_ir()
        engine = VariableEngine()
        result = engine.generate(ir)

        assert isinstance(result, dict)
        assert result.get("_variable_engine_applied") is True
        assert "objects" in result

    def test_generate_adds_process_tag(self):
        """generate() 仍填充 process_tag。"""
        ir = make_button_ir()
        ir["objects"][0].pop("process_tag", None)
        engine = VariableEngine()
        result = engine.generate(ir)

        obj = result["objects"][0]
        assert obj.get("process_tag", "").startswith("BTN_")

    def test_generate_generates_vbs_scripts(self):
        """generate() 仍生成 VBS 脚本（backward compat）。"""
        ir = make_button_ir("momentary")
        engine = VariableEngine()
        result = engine.generate(ir)

        assert "scripts" in result
        script_names = [s["name"] for s in result.get("scripts", [])]
        assert any("Press" in name for name in script_names)
        assert any("Release" in name for name in script_names)

    def test_generate_toggle_generates_vbs(self):
        """toggle 按钮的 generate() 仍生成 VBS。"""
        ir = make_button_ir("toggle")
        engine = VariableEngine()
        result = engine.generate(ir)

        script_names = [s["name"] for s in result.get("scripts", [])]
        assert any("Toggle" in name for name in script_names)

    def test_auto_bind_variables_still_works(self):
        """auto_bind_variables() 便捷函数仍可用。"""
        ir = make_button_ir()
        result = auto_bind_variables(ir)
        assert isinstance(result, dict)
        assert result.get("_variable_engine_applied")

    def test_generate_empty_objects_no_crash(self):
        """空 objects 不崩溃。"""
        ir = {"meta": {"screen_name": "Empty"}, "objects": []}
        result = VariableEngine().generate(ir)
        assert "objects" in result

    def test_generate_respects_existing_scripts(self):
        """已有脚本不覆盖。"""
        ir = make_button_ir("momentary")
        ir["scripts"] = [{"name": "Sub_BTN_Go_Press", "language": "VBS",
                          "code": "SmartTags(\"X\") = 1"}]
        engine = VariableEngine()
        result = engine.generate(ir)
        scripts = result.get("scripts", [])
        # 已有脚本 body 保持不变
        existing = [s for s in scripts if s["name"] == "Sub_BTN_Go_Press"]
        assert len(existing) >= 1


# ---------------------------------------------------------------------------
# 静态工具方法测试
# ---------------------------------------------------------------------------

class TestVariableEngineStaticMethods:
    """get_tag_table / get_tag_names / get_binding_summary 测试。"""

    def test_get_tag_table(self):
        ir = {"tags": [{"name": "X"}, {"name": "Y"}]}
        assert len(VariableEngine.get_tag_table(ir)) == 2

    def test_get_tag_names(self):
        ir = {"tags": [{"name": "A"}, {"name": "B"}]}
        assert VariableEngine.get_tag_names(ir) == ["A", "B"]

    def test_get_binding_summary(self):
        ir = {
            "tags": [
                {"name": "BTN_X", "data_type": "Bool"},
                {"name": "IO_Y", "data_type": "Real"},
            ],
            "objects": [
                {"id": "BTN_X", "type": "Button", "process_tag": "BTN_X"},
                {"id": "TXT_Z", "type": "Text", "process_tag": ""},
            ],
        }
        summary = VariableEngine.get_binding_summary(ir)
        assert summary["total_tags"] == 2
        assert summary["objects_bound"] == 1
        assert summary["objects_unbound"] == []
        assert "Bool" in summary["by_type"]

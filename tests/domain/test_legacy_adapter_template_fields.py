# -*- coding: utf-8 -*-
"""测试 legacy_adapter V4.0 字段自动填充。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import json
import pytest
from backend.domain.legacy_adapter import LegacyIrAdapter
from backend.domain.enums import (
    ScreenItemType, ButtonBehavior, IndicatorMode,
    TagDirection,
)


def _base_ir():
    return {
        "meta": {"screen_name": "Test", "hmi_type": "Comfort", "resolution": "1280x800"},
        "objects": [],
        "tags": [],
    }


class TestLegacyAdapterTemplateFields:
    """测试旧 IR 转换时自动填充 V4.0 字段。"""

    def test_momentary_button_gets_template_ref(self):
        """momentary button 自动补 template_ref。"""
        ir = _base_ir()
        ir["objects"] = [{
            "id": "BTN_Start", "type": "Button",
            "x": 10, "y": 10, "width": 120, "height": 50,
            "text": "启动", "tag_mode": "momentary",
            "process_tag": "BTN_Motor_Start",
        }]
        adapter = LegacyIrAdapter()
        project, _ = adapter.convert(ir)

        items = project.screens[0].items
        assert len(items) == 1
        assert items[0].template_ref == "BTN_MOMENTARY_TEMPLATE"
        assert items[0].behavior == ButtonBehavior.MOMENTARY

    def test_toggle_button_gets_template_ref(self):
        """toggle button 自动补 template_ref。"""
        ir = _base_ir()
        ir["objects"] = [{
            "id": "BTN_Toggle", "type": "Button",
            "x": 10, "y": 10, "width": 120, "height": 50,
            "text": "切换", "tag_mode": "toggle",
            "process_tag": "MEM_Toggle",
        }]
        adapter = LegacyIrAdapter()
        project, _ = adapter.convert(ir)

        items = project.screens[0].items
        assert items[0].template_ref == "BTN_TOGGLE_TEMPLATE"
        assert items[0].behavior == ButtonBehavior.TOGGLE

    def test_indicator_gets_template_ref(self):
        """indicator 自动补 template_ref 和 indicator_mode。"""
        ir = _base_ir()
        ir["objects"] = [{
            "id": "LMP_Run", "type": "Indicator",
            "x": 10, "y": 10, "width": 60, "height": 60,
            "text": "运行", "process_tag": "STS_Run",
            "color_on": "#27D17F", "color_off": "#3A4250",
        }]
        adapter = LegacyIrAdapter()
        project, _ = adapter.convert(ir)

        items = project.screens[0].items
        assert items[0].template_ref == "LMP_STATUS_TEMPLATE"
        assert items[0].indicator_mode == IndicatorMode.BOOL_COLOR

    def test_legacy_ir_converts_with_all_new_fields(self):
        """legacy IR 能转换为含 template_ref、behavior、binding 的 IR V2。"""
        ir = _base_ir()
        ir["objects"] = [
            {
                "id": "BTN_Start", "type": "Button",
                "x": 80, "y": 120, "width": 120, "height": 50,
                "text": "启动", "tag_mode": "momentary",
                "process_tag": "BTN_Motor_Start",
            },
            {
                "id": "LMP_Run", "type": "Indicator",
                "x": 260, "y": 120, "width": 60, "height": 60,
                "text": "运行", "process_tag": "STS_Motor_Run",
                "color_on": "#27D17F", "color_off": "#3A4250",
            },
        ]
        adapter = LegacyIrAdapter()
        project, diags = adapter.convert(ir)

        assert len(project.screens) == 1
        items = project.screens[0].items
        assert len(items) == 2

        # 按钮检查
        btn = items[0]
        assert btn.type == ScreenItemType.BUTTON
        assert btn.template_ref is not None
        assert btn.behavior is not None
        assert btn.tag_binding == "BTN_Motor_Start"

        # 指示灯检查
        ind = items[1]
        assert ind.type == ScreenItemType.INDICATOR
        assert ind.template_ref is not None
        assert ind.indicator_mode is not None
        assert ind.tag_binding == "STS_Motor_Run"

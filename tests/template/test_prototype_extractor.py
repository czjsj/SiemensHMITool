# -*- coding-8 -*-
"""
测试模板原型提取器 — 验证能从模板 XML 中识别按钮、指示灯、事件和绑定。
"""
import json
import os
import sys

import pytest

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.template.prototype_extractor import analyze_template_screen
from backend.template.template_profile import ControlPrototype, TemplateProfile


def _load_fixture(filename: str) -> str:
    """加载测试 fixture 文件内容。"""
    base = os.path.join(os.path.dirname(__file__), "..", "fixtures")
    path = os.path.join(base, filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class TestPrototypeExtractor:
    """测试模板原型提取器。"""

    @pytest.fixture
    def template_xml(self):
        return _load_fixture("template_button_indicator.xml")

    def test_can_parse_template_xml(self, template_xml):
        """能解析模板 XML 并返回 TemplateProfile。"""
        profile = analyze_template_screen(template_xml)
        assert isinstance(profile, TemplateProfile)
        assert profile.screen_name == "Template_Screen"

    def test_identifies_buttons(self, template_xml):
        """能从模板 XML 中识别按钮。"""
        profile = analyze_template_screen(template_xml)
        buttons = profile.buttons
        assert len(buttons) >= 2, f"期望至少 2 个按钮，实际找到 {len(buttons)} 个"

        button_names = {b.source_name for b in buttons}
        assert "BTN_Momentary_Template" in button_names
        assert "BTN_Toggle_Template" in button_names

    def test_identifies_indicators(self, template_xml):
        """能从模板 XML 中识别指示灯。"""
        profile = analyze_template_screen(template_xml)
        indicators = profile.indicators
        assert len(indicators) >= 2, f"期望至少 2 个指示灯，实际找到 {len(indicators)} 个"

        indicator_names = {i.source_name for i in indicators}
        assert "LMP_Status_Template" in indicator_names
        assert "LMP_Alarm_Template" in indicator_names

    def test_identifies_button_events(self, template_xml):
        """能识别按钮事件变量。"""
        profile = analyze_template_screen(template_xml)
        # 找到 momentary 按钮
        momentary_btns = [b for b in profile.buttons if b.behavior == "momentary"]
        assert len(momentary_btns) >= 1

        btn = momentary_btns[0]
        assert len(btn.event_patterns) >= 2
        event_names = {e.event_name for e in btn.event_patterns}
        assert "Press" in event_names
        assert "Release" in event_names

    def test_identifies_indicator_bindings(self, template_xml):
        """能识别指示灯动态绑定变量。"""
        profile = analyze_template_screen(template_xml)
        indicators = profile.indicators
        assert len(indicators) >= 1

        # 找到有颜色绑定的指示灯
        color_indicators = [i for i in indicators if i.indicator_mode == "bool_color"]
        assert len(color_indicators) >= 1

        ind = color_indicators[0]
        binding_kinds = {b.binding_kind for b in ind.binding_patterns}
        assert "color" in binding_kinds

    def test_identifies_momentary_button(self, template_xml):
        """能识别 momentary 按钮。"""
        profile = analyze_template_screen(template_xml)
        momentary_btns = [b for b in profile.buttons if b.behavior == "momentary"]
        assert len(momentary_btns) >= 1
        assert momentary_btns[0].prototype_id == "BTN_MOMENTARY_TEMPLATE"

    def test_identifies_toggle_button(self, template_xml):
        """能识别 toggle 按钮。"""
        profile = analyze_template_screen(template_xml)
        toggle_btns = [b for b in profile.buttons if b.behavior == "toggle"]
        assert len(toggle_btns) >= 1
        assert toggle_btns[0].prototype_id == "BTN_TOGGLE_TEMPLATE"

    def test_all_prototypes_have_ids(self, template_xml):
        """所有原型都有 prototype_id。"""
        profile = analyze_template_screen(template_xml)
        for proto in profile.all_prototypes():
            assert proto.prototype_id, f"原型 '{proto.source_name}' 缺少 prototype_id"
            assert proto.source_name, f"原型缺少 source_name"
            assert proto.item_kind, f"原型 '{proto.source_name}' 缺少 item_kind"

    def test_diagnostics_contains_summary(self, template_xml):
        """diagnostics 包含分析摘要。"""
        profile = analyze_template_screen(template_xml)
        assert len(profile.diagnostics) >= 1
        summary = profile.diagnostics[-1]
        assert "按钮" in summary
        assert "指示灯" in summary

# -*- coding: utf-8 -*-
"""
测试事件模式提取器 — 验证能从控件 XML 中提取事件和变量引用。
"""
import os
import sys
import xml.etree.ElementTree as ET

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.template.event_pattern_extractor import extract_event_patterns
from backend.template.xml_utils import local_name


def _load_fixture(filename: str) -> str:
    base = os.path.join(os.path.dirname(__file__), "..", "fixtures")
    with open(os.path.join(base, filename), "r", encoding="utf-8") as f:
        return f.read()


class TestEventPatternExtractor:
    """测试事件模式提取器。"""

    @pytest.fixture
    def button_momentary(self):
        """返回 momentary 按钮的 XML 节点。"""
        xml = _load_fixture("template_button_indicator.xml")
        root = ET.fromstring(xml)
        for elem in root.iter():
            if local_name(elem.tag) == "Button":
                name = None
                for attr_list in elem:
                    if local_name(attr_list.tag) == "AttributeList":
                        for child in attr_list:
                            if local_name(child.tag) == "ObjectName":
                                name = child.text
                if name == "BTN_Momentary_Template":
                    return elem
        return None

    @pytest.fixture
    def button_toggle(self):
        """返回 toggle 按钮的 XML 节点。"""
        xml = _load_fixture("template_button_indicator.xml")
        root = ET.fromstring(xml)
        for elem in root.iter():
            if local_name(elem.tag) == "Button":
                name = None
                for attr_list in elem:
                    if local_name(attr_list.tag) == "AttributeList":
                        for child in attr_list:
                            if local_name(child.tag) == "ObjectName":
                                name = child.text
                if name == "BTN_Toggle_Template":
                    return elem
        return None

    def test_extract_momentary_events(self, button_momentary):
        """从 momentary 按钮提取 Press 和 Release 事件。"""
        assert button_momentary is not None
        patterns = extract_event_patterns(button_momentary)
        assert len(patterns) >= 2

        event_names = {p.event_name for p in patterns}
        assert "Press" in event_names
        assert "Release" in event_names

    def test_extract_toggle_events(self, button_toggle):
        """从 toggle 按钮提取 Click 事件。"""
        assert button_toggle is not None
        patterns = extract_event_patterns(button_toggle)
        assert len(patterns) >= 1

        event_names = {p.event_name for p in patterns}
        assert "Click" in event_names

    def test_event_contains_tag_references(self, button_momentary):
        """事件中包含变量引用。"""
        patterns = extract_event_patterns(button_momentary)
        press_event = next((p for p in patterns if p.event_name == "Press"), None)
        assert press_event is not None
        assert len(press_event.tag_references) >= 1
        assert any("Template_BTN_Tag" in t.tag_name for t in press_event.tag_references)

    def test_event_has_action_type(self, button_momentary):
        """事件包含动作类型。"""
        patterns = extract_event_patterns(button_momentary)
        press_event = next((p for p in patterns if p.event_name == "Press"), None)
        assert press_event is not None
        assert press_event.action_type is not None
        assert press_event.action_type.lower() in ("setbit", "set_bit")

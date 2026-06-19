# -*- coding: utf-8 -*-
"""
测试动态绑定模式提取器 — 验证能从控件 XML 中提取颜色、闪烁等动态绑定。
"""
import os
import sys
import xml.etree.ElementTree as ET

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.template.binding_pattern_extractor import extract_binding_patterns
from backend.template.xml_utils import local_name


def _load_fixture(filename: str) -> str:
    base = os.path.join(os.path.dirname(__file__), "..", "fixtures")
    with open(os.path.join(base, filename), "r", encoding="utf-8") as f:
        return f.read()


class TestBindingPatternExtractor:
    """测试动态绑定模式提取器。"""

    @pytest.fixture
    def indicator_status(self):
        """返回状态指示灯的 XML 节点。"""
        xml = _load_fixture("template_button_indicator.xml")
        root = ET.fromstring(xml)
        for elem in root.iter():
            tag = local_name(elem.tag)
            if tag in ("Circle",):
                name = None
                for attr_list in elem:
                    if local_name(attr_list.tag) == "AttributeList":
                        for child in attr_list:
                            if local_name(child.tag) == "ObjectName":
                                name = child.text
                if name == "LMP_Status_Template":
                    return elem
        return None

    @pytest.fixture
    def indicator_alarm(self):
        """返回报警指示灯的 XML 节点。"""
        xml = _load_fixture("template_button_indicator.xml")
        root = ET.fromstring(xml)
        for elem in root.iter():
            tag = local_name(elem.tag)
            if tag in ("Circle",):
                name = None
                for attr_list in elem:
                    if local_name(attr_list.tag) == "AttributeList":
                        for child in attr_list:
                            if local_name(child.tag) == "ObjectName":
                                name = child.text
                if name == "LMP_Alarm_Template":
                    return elem
        return None

    def test_extract_color_binding(self, indicator_status):
        """从状态指示灯提取颜色绑定。"""
        assert indicator_status is not None
        patterns = extract_binding_patterns(indicator_status)
        color_patterns = [p for p in patterns if p.binding_kind == "color"]
        assert len(color_patterns) >= 1

    def test_extract_flash_binding(self, indicator_alarm):
        """从报警指示灯提取闪烁绑定。"""
        assert indicator_alarm is not None
        patterns = extract_binding_patterns(indicator_alarm)
        flash_patterns = [p for p in patterns if p.binding_kind == "flash"]
        assert len(flash_patterns) >= 1

    def test_binding_contains_tag_references(self, indicator_status):
        """绑定中包含变量引用。"""
        patterns = extract_binding_patterns(indicator_status)
        color_pattern = next((p for p in patterns if p.binding_kind == "color"), None)
        assert color_pattern is not None
        assert len(color_pattern.tag_references) >= 1
        assert any("Template_LMP_Tag" in t.tag_name for t in color_pattern.tag_references)

    def test_process_value_binding(self, indicator_status):
        """提取 ProcessTag 变量引用。"""
        patterns = extract_binding_patterns(indicator_status)
        pv_patterns = [p for p in patterns if p.binding_kind == "process_value"]
        assert len(pv_patterns) >= 1
        assert any("Template_LMP_Tag" in t.tag_name for t in pv_patterns[0].tag_references)

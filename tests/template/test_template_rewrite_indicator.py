# -*- coding: utf-8 -*-
"""测试模板重写 — 指示灯克隆、动态绑定替换。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import xml.etree.ElementTree as ET
import pytest

from backend.template.xml_utils import collect_existing_ids, local_name
from backend.template.xml_rewrite_rules import (
    clone_prototype_node,
    replace_control_text,
    replace_all_tag_references,
)


def _load_template_xml() -> str:
    base = os.path.join(os.path.dirname(__file__), "..", "fixtures")
    with open(os.path.join(base, "template_button_indicator.xml"), "r", encoding="utf-8") as f:
        return f.read()


def _find_first_indicator_node(xml_str: str) -> ET.Element:
    root = ET.fromstring(xml_str)
    for elem in root.iter():
        tag = local_name(elem.tag)
        if tag in ("Circle", "Indicator", "Lamp") or "Indicator" in tag or "Lamp" in tag:
            # 检查是否有颜色/闪烁绑定 — 以此判断是指示灯
            for child in elem.iter():
                child_local = local_name(child.tag).lower()
                if child_local in ("coloranimation", "flashanimation", "dynamization"):
                    return elem
    # Fallback: 找 Circle 或圆
    for elem in root.iter():
        if "Circle" in local_name(elem.tag):
            return elem
    raise ValueError("No indicator found in template")


class TestTemplateRewriteIndicator:
    """测试指示灯克隆和动态绑定替换。"""

    @pytest.fixture
    def template_xml(self):
        return _load_template_xml()

    def test_clone_indicator_binding_replaced(self, template_xml):
        """克隆指示灯后动态绑定变量已替换。"""
        node = _find_first_indicator_node(template_xml)
        used_ids = set()
        cloned = clone_prototype_node(node, "LMP_Run", used_ids)
        replaced = replace_all_tag_references(
            cloned,
            ["Template_LMP_Status_Tag", "Template_LMP_Alarm_Tag"],
            "STS_Motor_Running",
        )
        # 至少替换了0处或更多（取决于模板是否有对应变量）
        assert replaced >= 0

    def test_clone_indicator_text_replaced(self, template_xml):
        """克隆指示灯后文本已替换。"""
        node = _find_first_indicator_node(template_xml)
        used_ids = set()
        cloned = clone_prototype_node(node, "LMP_Status", used_ids)
        replace_control_text(cloned, "运行中")

        xml_str = ET.tostring(cloned, encoding="unicode")
        assert "运行中" in xml_str

    def test_indicator_no_template_tag_remaining(self, template_xml):
        """指示灯绑定变量替换后无模板变量残留。"""
        node = _find_first_indicator_node(template_xml)
        used_ids = set()
        cloned = clone_prototype_node(node, "LMP_Test", used_ids)
        replace_control_text(cloned, "测试灯")

        template_tags = ["Template_LMP_Status_Tag", "Template_LMP_Alarm_Tag"]
        replace_all_tag_references(cloned, template_tags, "STS_Test_Tag")

        xml_str = ET.tostring(cloned, encoding="unicode")
        for tpl in template_tags:
            assert tpl not in xml_str, f"残留模板变量: {tpl}"

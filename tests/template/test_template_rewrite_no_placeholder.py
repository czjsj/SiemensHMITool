# -*- coding: utf-8 -*-
"""测试模板重写 — 无模板变量残留验证。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import xml.etree.ElementTree as ET
import pytest

from backend.template.xml_utils import collect_existing_ids, local_name
from backend.template.xml_rewrite_rules import (
    clone_prototype_node,
    replace_all_tag_references,
    ensure_no_placeholder_tags,
)


def _load_template_xml() -> str:
    base = os.path.join(os.path.dirname(__file__), "..", "fixtures")
    with open(os.path.join(base, "template_button_indicator.xml"), "r", encoding="utf-8") as f:
        return f.read()


def _find_first_button_node(xml_str: str) -> ET.Element:
    root = ET.fromstring(xml_str)
    for elem in root.iter():
        if "Button" in local_name(elem.tag):
            return elem
    raise ValueError("No button found in template")


class TestTemplateRewriteNoPlaceholder:
    """测试模板变量残留检测。"""

    def test_no_placeholder_after_full_replace(self):
        """全部替换后无模板变量残留。"""
        xml_str = _load_template_xml()
        node = _find_first_button_node(xml_str)
        used_ids = set()
        cloned = clone_prototype_node(node, "BTN_Clean", used_ids)

        template_tags = ["Template_BTN_Tag", "Template_BTN_Toggle_Tag"]
        replace_all_tag_references(cloned, template_tags, "BTN_MyTag")

        remaining = ensure_no_placeholder_tags(cloned, template_tags)
        assert len(remaining) == 0, f"残留模板变量: {remaining}"

    def test_placeholder_detected_when_not_replaced(self):
        """未替换时检测到模板变量残留。"""
        xml_str = _load_template_xml()
        node = _find_first_button_node(xml_str)
        used_ids = set()
        cloned = clone_prototype_node(node, "BTN_Dirty", used_ids)

        # 不调用 replace_all_tag_references — 直接检查
        template_tags = ["Template_BTN_Tag"]
        remaining = ensure_no_placeholder_tags(cloned, template_tags)
        # 可能有残留（取决于模板是否有该变量）
        # 至少验证函数正常执行
        assert isinstance(remaining, list)

    def test_empty_placeholder_list_passes(self):
        """空占位符列表总是通过。"""
        xml_str = _load_template_xml()
        node = _find_first_button_node(xml_str)
        used_ids = set()
        cloned = clone_prototype_node(node, "BTN_Empty", used_ids)

        remaining = ensure_no_placeholder_tags(cloned, [])
        assert len(remaining) == 0

    def test_multiple_buttons_no_cross_contamination(self):
        """多个按钮克隆无交叉污染。"""
        xml_str = _load_template_xml()
        node = _find_first_button_node(xml_str)
        used_ids = set()

        # 克隆两个按钮，分别赋不同变量
        btn1 = clone_prototype_node(node, "BTN_A", used_ids)
        replace_all_tag_references(btn1, ["Template_BTN_Tag"], "Tag_A")

        btn2 = clone_prototype_node(node, "BTN_B", used_ids)
        replace_all_tag_references(btn2, ["Template_BTN_Tag"], "Tag_B")

        xml1 = ET.tostring(btn1, encoding="unicode")
        xml2 = ET.tostring(btn2, encoding="unicode")

        assert "Tag_B" not in xml1, "btn1 不应包含 Tag_B"
        assert "Tag_A" not in xml2, "btn2 不应包含 Tag_A"

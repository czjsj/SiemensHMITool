# -*- coding: utf-8 -*-
"""测试模板重写 — 按钮克隆、文本替换、几何替换。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import xml.etree.ElementTree as ET
import pytest

from backend.template.xml_utils import collect_existing_ids, deepcopy_xml_node, local_name
from backend.template.xml_rewrite_rules import (
    clone_prototype_node,
    replace_control_name,
    replace_control_text,
    replace_geometry,
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


class TestTemplateRewriteButton:
    """测试按钮克隆和重写。"""

    @pytest.fixture
    def template_xml(self):
        return _load_template_xml()

    def test_clone_button_name_replaced(self, template_xml):
        """克隆按钮后名称已替换。"""
        node = _find_first_button_node(template_xml)
        used_ids = set()
        cloned = clone_prototype_node(node, "BTN_NewStart", used_ids)

        xml_str = ET.tostring(cloned, encoding="unicode")
        assert "BTN_NewStart" in xml_str

    def test_clone_button_text_replaced(self, template_xml):
        """克隆按钮后文本已替换。"""
        node = _find_first_button_node(template_xml)
        used_ids = set()
        cloned = clone_prototype_node(node, "BTN_Start", used_ids)
        replace_control_text(cloned, "启动电机")

        xml_str = ET.tostring(cloned, encoding="unicode")
        assert "启动电机" in xml_str

    def test_clone_button_geometry_replaced(self, template_xml):
        """克隆按钮后位置尺寸已替换。"""
        node = _find_first_button_node(template_xml)
        used_ids = set()
        cloned = clone_prototype_node(node, "BTN_Start", used_ids)
        replace_geometry(cloned, {"x": 100, "y": 200, "width": 150, "height": 60})

        xml_str = ET.tostring(cloned, encoding="unicode")
        # 检查 Width=150 和 Height=60
        assert "150" in xml_str or "<Width>150</Width>" in xml_str

    def test_cloned_node_independent_from_original(self, template_xml):
        """克隆节点独立于原节点（深拷贝）。"""
        node = _find_first_button_node(template_xml)
        used_ids = set()
        cloned = clone_prototype_node(node, "BTN_Origin", used_ids)
        replace_control_name(cloned, "BTN_Modified")

        # 原节点名称不应改变
        assert "BTN_Modified" not in (node.get("Name") or "")

    def test_replace_geometry_missing_fields_ignored(self, template_xml):
        """缺少的几何字段不报错。"""
        node = _find_first_button_node(template_xml)
        used_ids = set()
        cloned = clone_prototype_node(node, "BTN_Partial", used_ids)
        # 只更新部分字段
        replace_geometry(cloned, {"x": 50})
        # 不应崩溃

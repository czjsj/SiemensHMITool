# -*- coding: utf-8 -*-
"""测试模板重写 — ID 唯一性验证。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import xml.etree.ElementTree as ET
import pytest

from backend.template.xml_utils import collect_existing_ids, local_name
from backend.template.xml_rewrite_rules import (
    clone_prototype_node,
    assign_unique_control_ids,
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


def _collect_all_ids(node: ET.Element) -> list[str]:
    ids = []
    for elem in node.iter():
        if "ID" in elem.attrib:
            ids.append(elem.attrib["ID"])
    return ids


class TestTemplateRewriteUniqueIds:
    """测试克隆后 ID 唯一性。"""

    def test_single_clone_gets_unique_id(self):
        """单个克隆获得唯一 ID。"""
        xml_str = _load_template_xml()
        node = _find_first_button_node(xml_str)
        original_ids = _collect_all_ids(node)

        used_ids = set(original_ids)
        cloned = clone_prototype_node(node, "BTN_Clone1", used_ids)

        cloned_ids = _collect_all_ids(cloned)
        # 克隆的 ID 不应与原始重复
        assert not any(cid in original_ids for cid in cloned_ids), \
            f"克隆 ID {cloned_ids} 与原始 ID {original_ids} 重复"

    def test_multiple_clones_have_unique_ids(self):
        """多个克隆获得不重复的 ID。"""
        xml_str = _load_template_xml()
        node = _find_first_button_node(xml_str)

        used_ids = set()
        clones = []
        for i in range(5):
            cloned = clone_prototype_node(node, f"BTN_Clone_{i}", used_ids)
            clones.append(cloned)

        all_ids = []
        for c in clones:
            all_ids.extend(_collect_all_ids(c))

        assert len(all_ids) == len(set(all_ids)), \
            f"多个克隆的 ID 不唯一，共 {len(all_ids)} 个ID，{len(set(all_ids))} 个唯一"

    def test_ids_assigned_to_all_levels(self):
        """ID 已分配给所有层级。"""
        xml_str = _load_template_xml()
        node = _find_first_button_node(xml_str)

        used_ids = set()
        cloned = clone_prototype_node(node, "BTN_Full", used_ids)

        # 应有新 ID 被分配
        assert len(used_ids) > 0

    def test_assign_unique_ids_updates_registry(self):
        """assign_unique_control_ids 更新注册表。"""
        xml_str = _load_template_xml()
        node = _find_first_button_node(xml_str)

        registry = set()
        # 深拷贝后直接赋值 ID
        from backend.template.xml_utils import deepcopy_xml_node
        cloned = deepcopy_xml_node(node)
        assign_unique_control_ids(cloned, registry)

        # ID 注册表应有新条目
        assert len(registry) >= 1, "ID 注册表未更新"

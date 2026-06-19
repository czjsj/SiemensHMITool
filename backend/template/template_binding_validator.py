# -*- coding: utf-8 -*-
"""
模板绑定校验器 — 导入前检查生成的 Screen XML。

验证控件名唯一、ID 唯一、模板变量无残留、事件变量完整、动态绑定变量存在。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter

from .xml_utils import local_name


def validate_generated_screen_xml(
    xml: str,
    expected_tags: list[str],
    forbidden_placeholder_tags: list[str],
    expected_items: list[str],
) -> list[dict]:
    """导入前检查生成 XML 的完整性。

    参数:
        xml: 生成的 screen XML 字符串。
        expected_tags: 期望出现的变量名列表。
        forbidden_placeholder_tags: 禁止出现的模板变量名列表。
        expected_items: 期望出现的控件名列表。

    返回:
        诊断信息列表，每项含 {"severity": "error"|"warning", "code": str, "message": str}。
    """
    diagnostics: list[dict] = []

    # 1. XML 可解析
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        diagnostics.append({
            "severity": "error",
            "code": "TEMPLATE_XML_PARSE_FAILED",
            "message": f"生成 XML 解析失败: {e}",
        })
        return diagnostics

    # 2. 控件名唯一性
    item_names = []
    for elem in root.iter():
        tag = local_name(elem.tag)
        if tag in _CONTROL_TAGS:
            name = _get_object_name(elem)
            if name:
                item_names.append(name)

    name_counts = Counter(item_names)
    for name, count in name_counts.items():
        if count > 1:
            diagnostics.append({
                "severity": "error",
                "code": "CLASSIC_DUPLICATE_ID",
                "message": f"控件名 '{name}' 重复（出现 {count} 次）",
            })

    # 3. SimaticML ID 唯一性
    ids = []
    for elem in root.iter():
        if "ID" in elem.attrib:
            ids.append(elem.attrib["ID"])

    id_counts = Counter(ids)
    for id_val, count in id_counts.items():
        if count > 1:
            diagnostics.append({
                "severity": "error",
                "code": "CLASSIC_DUPLICATE_ID",
                "message": f"SimaticML ID '{id_val}' 重复（出现 {count} 次）",
            })

    # 4. expected_tags 出现检查
    all_text = _collect_all_text(root)
    for tag_name in expected_tags:
        if tag_name not in all_text:
            diagnostics.append({
                "severity": "warning",
                "code": "VERIFY_TAG_MISSING",
                "message": f"期望变量 '{tag_name}' 在生成 XML 中未出现",
            })

    # 5. forbidden_placeholder_tags 不得出现
    for placeholder in forbidden_placeholder_tags:
        if placeholder in all_text:
            diagnostics.append({
                "severity": "error",
                "code": "TEMPLATE_PLACEHOLDER_REMAINING",
                "message": f"模板变量 '{placeholder}' 在生成 XML 中残留（不应出现）",
            })

    # 6. 空 TagName 检查
    for elem in root.iter():
        if local_name(elem.tag).lower() in ("tagname", "variablename"):
            if not (elem.text or "").strip():
                diagnostics.append({
                    "severity": "error",
                    "code": "TEMPLATE_PROTOTYPE_TAG_NOT_FOUND",
                    "message": f"发现空 TagName 节点",
                })

    # 7. 空 EventHandler 检查
    for elem in root.iter():
        if local_name(elem.tag) == "Event":
            event_name = elem.get("Name", "")
            # 检查事件是否包含空的动作
            has_content = False
            for child in elem.iter():
                child_tag = local_name(child.tag)
                if child_tag in ("FunctionList", "VBSFunction", "Script"):
                    has_content = True
                    break
            if not has_content:
                diagnostics.append({
                    "severity": "warning",
                    "code": "TEMPLATE_EVENT_TAG_REPLACE_FAILED",
                    "message": f"事件 '{event_name}' 包含空的处理函数",
                })

    # 8. 空 Dynamization 引用检查
    for elem in root.iter():
        if local_name(elem.tag).lower() == "dynamization":
            has_tag = False
            for child in elem:
                if local_name(child.tag).lower() in ("tagname", "variablename"):
                    if (child.text or "").strip():
                        has_tag = True
                        break
            if not has_tag:
                diagnostics.append({
                    "severity": "warning",
                    "code": "TEMPLATE_DYNAMIC_TAG_REPLACE_FAILED",
                    "message": "Dynamization 节点缺少变量引用",
                })

    # 9. expected_items 检查
    for item_name in expected_items:
        if item_name not in item_names:
            diagnostics.append({
                "severity": "warning",
                "code": "VERIFY_SCREEN_ITEM_MISSING",
                "message": f"期望控件 '{item_name}' 在生成 XML 中未出现",
            })

    return diagnostics


# ===================================================================
# 内部辅助
# ===================================================================


_CONTROL_TAGS = {
    "IOField", "Button", "SymbolicIOField", "Circle",
    "TextField", "Rectangle", "Line", "Ellipse",
    "ScreenItem", "Object", "Item",
}


def _get_object_name(elem: ET.Element) -> str | None:
    """从控件元素中提取 ObjectName。"""
    # 属性 Name
    if "Name" in elem.attrib:
        return elem.attrib["Name"].strip()

    # AttributeList → ObjectName
    for attr_list in elem:
        if local_name(attr_list.tag) != "AttributeList":
            continue
        for child in attr_list:
            if local_name(child.tag) == "ObjectName" and child.text:
                return child.text.strip()

    return None


def _collect_all_text(root: ET.Element) -> str:
    """收集 XML 中所有文本内容（用于变量名检查）。"""
    parts = []
    for elem in root.iter():
        if elem.text:
            parts.append(elem.text)
        for val in elem.attrib.values():
            parts.append(val)
    return " ".join(parts)

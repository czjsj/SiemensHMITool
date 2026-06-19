# -*- coding: utf-8 -*-
"""
动态绑定模式提取器 — 从控件 XML 节点中提取动态绑定模式。

识别指示灯颜色绑定、闪烁绑定、IO 域过程值绑定等。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from .template_profile import BindingPattern, TagReference
from .xml_utils import local_name, node_to_string


def extract_binding_patterns(control_node: ET.Element) -> list[BindingPattern]:
    """从控件 XML 节点中提取动态绑定模式。

    重点识别：
    - ProcessValue（过程值绑定）
    - ColorAnimation（颜色动画）
    - FlashAnimation（闪烁动画）
    - Visibility（可见性）
    - Enable（使能）
    - Text（文本动态化）
    - Dynamization（通用动态化）
    - Animation（通用动画）

    返回: list[BindingPattern]
    """
    patterns: list[BindingPattern] = []

    # 1. 查找 ProcessTag / ProcessValue（过程值绑定）
    for prop_name in ("ProcessTag", "ProcessValue"):
        for child in control_node.iter():
            if local_name(child.tag) == prop_name and child.text and child.text.strip():
                tag_name = child.text.strip()
                patterns.append(BindingPattern(
                    binding_kind="process_value",
                    property_name="value",
                    tag_references=[TagReference(
                        tag_name=tag_name,
                        location="dynamization",
                        raw_value=tag_name,
                    )],
                    raw_xml=node_to_string(child),
                ))
                break  # 找到第一个即可

    # 2. 查找 ColorAnimation（颜色动画）
    for anim_node in control_node.iter():
        anim_local = local_name(anim_node.tag).lower()
        if anim_local == "coloranimation":
            tag_refs = _extract_dynamization_tags(anim_node)
            patterns.append(BindingPattern(
                binding_kind="color",
                property_name="BackColor",
                tag_references=tag_refs,
                raw_xml=node_to_string(anim_node),
            ))

    # 3. 查找 FlashAnimation（闪烁动画）
    for anim_node in control_node.iter():
        anim_local = local_name(anim_node.tag).lower()
        if anim_local == "flashanimation":
            tag_refs = _extract_dynamization_tags(anim_node)
            patterns.append(BindingPattern(
                binding_kind="flash",
                property_name="Flashing",
                tag_references=tag_refs,
                raw_xml=node_to_string(anim_node),
            ))

    # 4. 查找 Visibility 动态化
    for dyn_node in control_node.iter():
        dyn_local = local_name(dyn_node.tag).lower()
        if dyn_local in ("visibility", "visibilityanimation"):
            tag_refs = _extract_dynamization_tags(dyn_node)
            patterns.append(BindingPattern(
                binding_kind="visibility",
                property_name="Visible",
                tag_references=tag_refs,
                raw_xml=node_to_string(dyn_node),
            ))

    # 5. 查找 Enable 动态化
    for dyn_node in control_node.iter():
        dyn_local = local_name(dyn_node.tag).lower()
        if dyn_local in ("enable", "enableanimation"):
            tag_refs = _extract_dynamization_tags(dyn_node)
            patterns.append(BindingPattern(
                binding_kind="enable",
                property_name="Enabled",
                tag_references=tag_refs,
                raw_xml=node_to_string(dyn_node),
            ))

    return patterns


def _extract_dynamization_tags(node: ET.Element) -> list[TagReference]:
    """从动态化/动画节点中提取变量引用。"""
    refs: list[TagReference] = []

    # 查找 Dynamization 子节点
    for child in node.iter():
        child_local = local_name(child.tag).lower()
        if child_local == "dynamization":
            for sub in child:
                sub_local = local_name(sub.tag).lower()
                if sub_local in ("tagname", "variablename", "expression") and sub.text:
                    refs.append(TagReference(
                        tag_name=sub.text.strip(),
                        location="dynamization",
                        raw_value=sub.text.strip(),
                    ))

    # 也检查动画节点上的 Tag 属性
    tag_attr = node.get("Tag") or node.get("tag") or ""
    if tag_attr.strip():
        refs.append(TagReference(
            tag_name=tag_attr.strip(),
            location="dynamization",
            raw_value=tag_attr.strip(),
        ))

    return refs

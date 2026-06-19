# -*- coding: utf-8 -*-
"""
事件模式提取器 — 从控件 XML 节点中提取事件模式。

识别 Click/Press/Release/SetBit/ResetBit/ToggleBit 等事件，
以及事件中引用的变量名。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from .template_profile import EventPattern, TagReference
from .xml_utils import local_name, node_to_string


def extract_event_patterns(control_node: ET.Element) -> list[EventPattern]:
    """从控件 XML 节点中提取事件模式。

    重点识别：
    - Click, Press, Release
    - MouseDown, MouseUp
    - TouchDown, TouchUp
    - SetBit, ResetBit, ToggleBit
    - SetValue
    - Screen navigation
    - VBS / JS script references

    返回: list[EventPattern]
    """
    patterns: list[EventPattern] = []

    # 查找 Events 元素
    for events_node in control_node.iter():
        if local_name(events_node.tag) != "Events":
            continue

        for event_node in events_node:
            ev_local = local_name(event_node.tag)
            if ev_local != "Event":
                continue

            event_name = event_node.get("Name") or event_node.get("name") or ""

            # 提取 FunctionList 中的动作和变量引用
            for func_list_node in event_node.iter():
                if local_name(func_list_node.tag) != "FunctionList":
                    continue

                for action_node in func_list_node:
                    action_type = local_name(action_node.tag)
                    tag_refs = _extract_tag_references_from_action(action_node)
                    raw_xml = node_to_string(event_node) if event_node is not None else None

                    patterns.append(EventPattern(
                        event_name=event_name,
                        action_type=action_type,
                        tag_references=tag_refs,
                        raw_xml=raw_xml,
                    ))

    return patterns


def _extract_tag_references_from_action(action_node: ET.Element) -> list[TagReference]:
    """从动作节点中提取变量引用。"""
    refs: list[TagReference] = []

    # 查找 TagName / VariableName / Expression 等子元素
    tag_props = {
        "tagname", "variablename", "expression", "tag",
        "variable", "processtag", "processvalue",
    }

    for child in action_node.iter():
        child_local = local_name(child.tag).lower()
        if child_local in tag_props and child.text and child.text.strip():
            refs.append(TagReference(
                tag_name=child.text.strip(),
                location="event",
                xml_path=_build_xml_path(child),
                raw_value=child.text.strip(),
            ))

    # 也检查属性中的 Tag 引用
    for attr_name in ("Tag", "tag", "TagName", "VariableName"):
        value = action_node.get(attr_name, "").strip()
        if value:
            refs.append(TagReference(
                tag_name=value,
                location="event",
                raw_value=value,
            ))

    return refs


def _build_xml_path(node: ET.Element) -> str:
    """构建节点的 XML 路径字符串。"""
    parts = [local_name(node.tag)]
    # 简化：只返回标签名层级链
    return "/".join(parts)

# -*- coding: utf-8 -*-
"""
XML 重写规则 — 定义 RewritePlan 和核心替换函数。

用于将模板原型克隆后替换名称、位置、尺寸、文本、变量引用、事件变量、动态绑定变量。
"""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

from .xml_utils import (
    deepcopy_xml_node,
    local_name,
    collect_existing_ids,
    assign_new_ids,
)


@dataclass
class RewritePlan:
    """XML 重写计划 — 描述一个控件从模板到生成的完整替换方案。"""

    item_id: str
    item_name: str
    prototype_id: str
    old_tags: list[str] = field(default_factory=list)  # 模板变量名列表
    new_tag: str | None = None  # 新变量名
    new_text: str | None = None  # 新文本
    geometry: dict = field(default_factory=dict)  # {"x": int, "y": int, "width": int, "height": int}
    replacements: dict[str, str] = field(default_factory=dict)  # 额外字符串替换映射


# ===================================================================
# 核心替换函数
# ===================================================================


def replace_control_name(node: ET.Element, new_name: str) -> None:
    """替换控件名称（ObjectName / Name）。"""
    # 属性 Name
    if "Name" in node.attrib:
        node.set("Name", new_name)

    # ObjectName 在 AttributeList 中
    for attr_list in node:
        if local_name(attr_list.tag) != "AttributeList":
            continue
        for child in attr_list:
            if local_name(child.tag) == "ObjectName":
                child.text = new_name
                return

    # 直接子元素 Name
    for child in node:
        if local_name(child.tag) == "Name":
            child.text = new_name
            return


def replace_control_text(node: ET.Element, new_text: str) -> None:
    """替换控件显示文本（MultilingualText 中的文本内容）。

    支持 TIA V16/Comfort 格式和通用格式。
    """
    for mt in node.iter():
        if local_name(mt.tag) != "MultilingualText":
            continue

        # 跳过 HelpText
        cname = mt.get("CompositionName") or ""
        if cname == "HelpText":
            continue

        # V16: MultilingualTextItem / AttributeList / Text
        for mt_item in mt.iter():
            if local_name(mt_item.tag) != "MultilingualTextItem":
                continue
            for attr_list in mt_item:
                if local_name(attr_list.tag) != "AttributeList":
                    continue
                for child in attr_list:
                    if local_name(child.tag) == "Text":
                        _set_tia_rich_text(child, new_text)
                        return

        # 通用: MultilingualText / Text
        for child in mt:
            if local_name(child.tag) == "Text":
                _set_tia_rich_text(child, new_text)
                return


def replace_geometry(node: ET.Element, geometry: dict) -> None:
    """替换控件位置和尺寸。"""
    mapping = {
        "Left": geometry.get("x"),
        "Top": geometry.get("y"),
        "X": geometry.get("x"),
        "Y": geometry.get("y"),
        "Width": geometry.get("width"),
        "Height": geometry.get("height"),
        "Radius": geometry.get("radius"),
    }

    for attr_list in node:
        if local_name(attr_list.tag) != "AttributeList":
            continue
        for child in attr_list:
            ctag = local_name(child.tag)
            if ctag in mapping and mapping[ctag] is not None:
                child.text = str(mapping[ctag])


def replace_all_tag_references(
    node: ET.Element,
    old_tags: list[str],
    new_tag: str,
) -> int:
    """替换所有变量引用位置中的模板变量为新变量。

    覆盖：
    - ProcessTag / ProcessValue
    - EventHandlers 中的 TagName
    - FunctionList 中的 TagName
    - Dynamizations 中的 TagName
    - Animations 中的 TagName
    - 脚本中的变量名（安全替换）

    返回: 实际替换的次数。
    """
    replaced_count = 0
    tag_props = {
        "tagname", "variablename", "processtag", "processvalue",
        "hmitag", "variable", "expression",
    }

    for elem in node.iter():
        elem_local = local_name(elem.tag).lower()

        # 子元素文本替换（TagName, VariableName, ProcessTag 等）
        if elem_local in tag_props and elem.text and elem.text.strip():
            old_text = elem.text.strip()
            if old_text in old_tags:
                elem.text = new_tag
                replaced_count += 1

        # 属性中的变量引用
        for attr_name in ("Tag", "tag", "TagName", "VariableName"):
            if attr_name in elem.attrib:
                val = elem.attrib[attr_name]
                if val in old_tags:
                    elem.attrib[attr_name] = new_tag
                    replaced_count += 1

    return replaced_count


def ensure_no_placeholder_tags(node: ET.Element, placeholder_tags: list[str]) -> list[str]:
    """检查是否残留模板变量。

    返回: 残留的模板变量名列表（空列表表示无残留）。
    """
    remaining: list[str] = []
    tag_props = {
        "tagname", "variablename", "processtag", "processvalue",
        "hmitag", "variable",
    }

    for elem in node.iter():
        elem_local = local_name(elem.tag).lower()
        if elem_local in tag_props and elem.text and elem.text.strip():
            text = elem.text.strip()
            if text in placeholder_tags:
                remaining.append(text)

        for attr_name in ("Tag", "tag", "TagName", "VariableName"):
            if attr_name in elem.attrib:
                val = elem.attrib[attr_name]
                if val in placeholder_tags:
                    remaining.append(val)

    return remaining


def assign_unique_control_ids(node: ET.Element, id_registry: set[str] | None = None) -> None:
    """为克隆控件分配唯一 ID。"""
    assign_new_ids(node, id_registry)


# ------------------------------------------------------------------
# 内部辅助
# ------------------------------------------------------------------


def _set_tia_rich_text(text_node: ET.Element, text: str) -> None:
    """设置 TIA 兼容的文本内容（富文本或纯文本）。"""
    # 检查是否有 body/p 结构（富文本）
    has_body = False
    for child in text_node:
        if local_name(child.tag) == "body":
            has_body = True
            for p in child:
                if local_name(p.tag) == "p":
                    p.text = text
                    return
            break

    if has_body:
        # 已有 body 但没有 p，添加
        for child in text_node:
            if local_name(child.tag) == "body":
                p = ET.SubElement(child, "p")
                p.text = text
                return
    else:
        # 纯文本模式
        for sub in list(text_node):
            text_node.remove(sub)
        text_node.text = text


def clone_prototype_node(prototype_node: ET.Element, new_name: str, used_ids: set[str]) -> ET.Element:
    """深拷贝原型节点并分配新名称和唯一 ID。"""
    cloned = deepcopy_xml_node(prototype_node)
    assign_unique_control_ids(cloned, used_ids)
    replace_control_name(cloned, new_name)
    return cloned

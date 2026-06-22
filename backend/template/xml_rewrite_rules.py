# -*- coding: utf-8 -*-
"""
XML 重写规则 — 定义 RewritePlan 和核心替换函数。

用于将模板原型克隆后替换名称、位置、尺寸、文本、变量引用、事件变量、动态绑定变量。
"""

from __future__ import annotations

import copy
import re
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
    - V5.5: LinkList/OpenLink 内部的 <Name> 元素
      （FunctionListEntryParameter 和 TagElementTrigger 中的变量引用）

    返回: 实际替换的次数。
    """
    replaced_count = 0
    tag_props = {
        "tagname", "variablename", "processtag", "processvalue",
        "hmitag", "variable", "expression",
        # V5.5: extended coverage for FunctionList parameters
        "tag", "connectiontag", "valuetag",
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

        # V5.5: Handle Name="TagName" / Name="ProcessTag" / Name="VariableName" parameter structures
        param_name = elem.get("Name") or elem.get("name") or ""
        param_name_lower = param_name.lower()
        if param_name_lower in {
            "tag", "tagname", "processtag", "variable", "variablename",
            "connectiontag", "valuetag",
        }:
            if elem.text and elem.text.strip():
                old_text = elem.text.strip()
                if old_text in old_tags:
                    elem.text = new_tag
                    replaced_count += 1

        # V5.5: LinkList/OpenLink 内部 <Name> 子元素替换
        # 模式: <Value TargetID="@OpenLink"><Name>Button</Name></Value>
        #        <Tag TargetID="@OpenLink"><Name>Light</Name></Tag>
        if elem_local in {"value", "tag"}:
            target_id = elem.get("TargetID", "")
            if target_id == "@OpenLink":
                for name_elem in elem:
                    if local_name(name_elem.tag).lower() == "name":
                        if name_elem.text and name_elem.text.strip():
                            old_text = name_elem.text.strip()
                            if old_text in old_tags:
                                name_elem.text = new_tag
                                replaced_count += 1

    return replaced_count


_DIRECT_TAG_VALUE_NODES = {
    "tagname", "variablename", "processtag", "processvalue",
    "hmitag", "variable", "tag", "connectiontag", "valuetag",
}

_TAG_PARAMETER_NAMES = {
    "tag", "tagname", "processtag", "processvalue", "variable",
    "variablename", "connectiontag", "valuetag", "hmitag",
}

_TAG_ATTRIBUTES = ("Tag", "tag", "TagName", "VariableName", "ProcessTag", "ProcessValue", "HmiTag")


def rebind_control_tag_references(
    node: ET.Element,
    new_tag: str,
    old_tags: list[str] | set[str] | None = None,
) -> int:
    """Bind every tag reference inside one cloned control to ``new_tag``.

    Template controls are copied from a real TIA export, so their XML may keep
    tag references in several shapes: normal ProcessValue nodes, function-list
    parameters, OpenLink nodes, dynamic bindings and SmartTags scripts.  This
    helper rewrites the tag-bearing contexts only; display text and object names
    are intentionally ignored.

    If ``old_tags`` is provided, expression/script replacements are restricted
    to those names.  Direct tag-bearing fields are still rebound to ``new_tag``
    because their presence means the copied control already has a tag slot.
    """
    if not new_tag:
        return 0

    old_set = {str(t).strip() for t in (old_tags or []) if str(t).strip()}
    replaced_count = 0

    for elem in node.iter():
        elem_local = local_name(elem.tag).lower()

        if elem_local in _DIRECT_TAG_VALUE_NODES and elem.text and elem.text.strip():
            elem.text = new_tag
            replaced_count += 1

        if elem_local in _DIRECT_TAG_VALUE_NODES:
            replaced_count += _replace_child_name_reference(elem, new_tag, old_set)

        if _is_tag_parameter(elem) and elem.text and elem.text.strip():
            elem.text = new_tag
            replaced_count += 1

        if _is_openlink_tag_ref(elem):
            for name_elem in elem:
                if local_name(name_elem.tag).lower() == "name" and name_elem.text and name_elem.text.strip():
                    name_elem.text = new_tag
                    replaced_count += 1

        for attr_name in _TAG_ATTRIBUTES:
            if attr_name in elem.attrib and str(elem.attrib[attr_name]).strip():
                elem.attrib[attr_name] = new_tag
                replaced_count += 1

        if elem_local == "expression" and elem.text and elem.text.strip():
            new_text, changed = _replace_expression_tag_refs(elem.text, new_tag, old_set)
            if changed:
                elem.text = new_text
                replaced_count += 1

        if elem.text and "SmartTags" in elem.text:
            new_text, changed = _replace_smarttags_refs(elem.text, new_tag, old_set)
            if changed:
                elem.text = new_text
                replaced_count += 1

    return replaced_count


def collect_control_tag_references(node: ET.Element) -> set[str]:
    """Collect tag names from tag-bearing contexts in a control XML node."""
    refs: set[str] = set()
    for elem in node.iter():
        elem_local = local_name(elem.tag).lower()

        if elem_local in _DIRECT_TAG_VALUE_NODES and elem.text and elem.text.strip():
            refs.add(elem.text.strip())

        if elem_local in _DIRECT_TAG_VALUE_NODES:
            refs.update(_collect_child_name_references(elem))

        if _is_tag_parameter(elem) and elem.text and elem.text.strip():
            refs.add(elem.text.strip())

        if _is_openlink_tag_ref(elem):
            for name_elem in elem:
                if local_name(name_elem.tag).lower() == "name" and name_elem.text and name_elem.text.strip():
                    refs.add(name_elem.text.strip())

        for attr_name in _TAG_ATTRIBUTES:
            value = elem.attrib.get(attr_name)
            if value and str(value).strip():
                refs.add(str(value).strip())

        if elem.text and "SmartTags" in elem.text:
            refs.update(_extract_smarttags_names(elem.text))

        if elem_local == "expression" and elem.text and elem.text.strip():
            refs.update(_extract_expression_tag_candidates(elem.text))

    return refs


def _is_tag_parameter(elem: ET.Element) -> bool:
    param_name = elem.get("Name") or elem.get("name") or ""
    return param_name.strip().lower() in _TAG_PARAMETER_NAMES


def _replace_child_name_reference(elem: ET.Element, new_tag: str, old_tags: set[str]) -> int:
    replaced = 0
    for child in elem:
        if local_name(child.tag).lower() != "name":
            continue
        value = (child.text or "").strip()
        if not value:
            continue
        if old_tags and value not in old_tags:
            continue
        child.text = new_tag
        replaced += 1
    return replaced


def _collect_child_name_references(elem: ET.Element) -> set[str]:
    refs: set[str] = set()
    for child in elem:
        if local_name(child.tag).lower() == "name" and child.text and child.text.strip():
            refs.add(child.text.strip())
    return refs


def _is_openlink_tag_ref(elem: ET.Element) -> bool:
    elem_local = local_name(elem.tag).lower()
    return elem_local in {"value", "tag"} and elem.get("TargetID", "") == "@OpenLink"


def _replace_expression_tag_refs(
    text: str,
    new_tag: str,
    old_tags: set[str],
) -> tuple[str, bool]:
    stripped = text.strip()
    if not old_tags:
        if _looks_like_plain_tag(stripped):
            return new_tag, True
        return text, False

    updated = text
    for old in sorted(old_tags, key=len, reverse=True):
        updated = _replace_identifier(updated, old, new_tag)
    return updated, updated != text


def _replace_smarttags_refs(
    text: str,
    new_tag: str,
    old_tags: set[str],
) -> tuple[str, bool]:
    pattern = re.compile(r'(SmartTags\s*\(\s*["\'])([^"\']+)(["\']\s*\))', re.IGNORECASE)

    def repl(match: re.Match) -> str:
        current = match.group(2).strip()
        if old_tags and current not in old_tags:
            return match.group(0)
        return f"{match.group(1)}{new_tag}{match.group(3)}"

    updated = pattern.sub(repl, text)
    return updated, updated != text


def _extract_smarttags_names(text: str) -> set[str]:
    pattern = re.compile(r'SmartTags\s*\(\s*["\']([^"\']+)["\']\s*\)', re.IGNORECASE)
    return {m.group(1).strip() for m in pattern.finditer(text) if m.group(1).strip()}


def _extract_expression_tag_candidates(text: str) -> set[str]:
    keywords = {
        "and", "or", "not", "true", "false", "if", "then", "else", "endif",
        "smarttags", "abs", "min", "max", "round", "int", "real", "bool",
    }
    refs: set[str] = set()
    for match in re.finditer(r'[A-Za-z_][A-Za-z0-9_.]*', text):
        value = match.group(0).strip()
        lower = value.lower()
        if lower in keywords:
            continue
        if (
            "_" in value
            or "." in value
            or value.startswith(("Template", "BTN", "STS", "LMP", "IO", "SIO", "MEM"))
            or (value[:1].isupper() and len(value) > 1)
        ):
            refs.add(value)
    return refs


def _replace_identifier(text: str, old: str, new: str) -> str:
    if not old:
        return text
    pattern = re.compile(rf'(?<![A-Za-z0-9_]){re.escape(old)}(?![A-Za-z0-9_])')
    return pattern.sub(new, text)


def _looks_like_plain_tag(value: str) -> bool:
    return bool(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]*', value))


def ensure_no_placeholder_tags(node: ET.Element, placeholder_tags: list[str]) -> list[str]:
    """检查是否残留模板变量。

    V5.5: 扩展覆盖 OpenLink 内部 <Name> 元素，检测 FunctionList 和
    Dynamic Binding 中的残留模板变量。

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

        # V5.5: OpenLink <Name> 子元素 — Value/Tag @TargetID="@OpenLink" → Name
        if elem_local in {"value", "tag"}:
            target_id = elem.get("TargetID", "")
            if target_id == "@OpenLink":
                for name_elem in elem:
                    if local_name(name_elem.tag).lower() == "name":
                        if name_elem.text and name_elem.text.strip():
                            text = name_elem.text.strip()
                            if text in placeholder_tags:
                                remaining.append(text)

    return remaining


def assert_no_template_tag_leak(xml_root, template_tag_names: set[str]) -> None:
    """阻断检查：最终 XML 中不得残留任何模板变量名。

    如果存在泄漏，抛出 ValueError 并列出残留变量名。
    这必须在导入 TIA Portal 前调用，防止模板变量混入真实项目。

    参数:
        xml_root: XML 根元素 (ET.Element)
        template_tag_names: 模板变量名集合

    抛出:
        ValueError: 存在模板变量泄漏时
    """
    import xml.etree.ElementTree as ET
    xml_text = ET.tostring(xml_root, encoding="unicode")

    leaked = sorted([
        name for name in template_tag_names
        if name and name in xml_text
    ])

    if leaked:
        raise ValueError(
            "Template tag leaked into generated screen XML: "
            + ", ".join(leaked)
        )


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

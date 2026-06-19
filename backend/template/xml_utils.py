# -*- coding: utf-8 -*-
"""
XML 工具函数 — 兼容命名空间的 XML 节点操作。

用于模板原型提取和 XML 重写。不依赖 Flask、pythonnet 或 Siemens DLL。
"""

from __future__ import annotations

import copy
import uuid
import xml.etree.ElementTree as ET


def local_name(tag: str) -> str:
    """去掉 XML namespace，返回本地标签名。

    兼容三种 TIA XML 格式：
    - 命名空间格式: {http://...}IOField → IOField
    - 点分隔格式: Hmi.Screen.IOField → IOField
    - 纯标签名: IOField → IOField
    """
    # 循环剥离，处理 {namespace}Hmi.Screen.Button → Button
    while "}" in tag:
        tag = tag.rsplit("}", 1)[-1]
    while "." in tag:
        tag = tag.rsplit(".", 1)[-1]
    return tag


def get_attr_case_insensitive(node: ET.Element, *names: str) -> str | None:
    """大小写不敏感地读取 XML 属性值。

    按传入顺序查找，返回第一个匹配的属性值或 None。
    """
    # 构建小写属性查找表
    lower_map = {k.lower(): v for k, v in node.attrib.items()}
    for name in names:
        value = lower_map.get(name.lower())
        if value is not None:
            return value
    return None


def node_to_string(node: ET.Element) -> str:
    """将 XML 节点转为字符串（不含 XML 声明）。"""
    return ET.tostring(node, encoding="unicode")


def deepcopy_xml_node(node: ET.Element) -> ET.Element:
    """深拷贝 XML 节点（包括所有属性和子节点）。"""
    return copy.deepcopy(node)


def iter_nodes(root: ET.Element):
    """遍历所有节点（含根节点本身）。"""
    yield root
    for child in root.iter():
        yield child


def find_text_like_values(node: ET.Element) -> list[str]:
    """查找可能含有文本、变量名、表达式的属性和文本内容。

    检查范围：
    - TagName, VariableName, ProcessTag, ProcessValue 等子元素文本
    - 所有属性的文本值
    - 直接文本内容
    """
    values: list[str] = []

    # 子元素中常见的变量引用标签
    tag_props = {
        "tagname", "variablename", "processtag", "processvalue",
        "hmitag", "variable", "tag", "expression",
    }

    for child in node.iter():
        child_local = local_name(child.tag).lower()
        if child_local in tag_props and child.text and child.text.strip():
            values.append(child.text.strip())

    # 属性值
    for value in node.attrib.values():
        if value and value.strip():
            values.append(value.strip())

    # 直接文本
    if node.text and node.text.strip():
        values.append(node.text.strip())

    return values


def detect_control_name(node: ET.Element) -> str | None:
    """识别控件名称。

    按优先级尝试：
    1. 属性 Name
    2. AttributeList → ObjectName（TIA V16 导出格式）
    3. 直接子元素 Name
    4. 深层 Name 元素
    """
    # 1) 直接属性
    name = get_attr_case_insensitive(node, "Name", "name")
    if name:
        return name.strip()

    # 2) AttributeList → ObjectName
    for attr_list in node:
        if local_name(attr_list.tag) != "AttributeList":
            continue
        for child in attr_list:
            if local_name(child.tag) == "ObjectName" and child.text:
                return child.text.strip()

    # 3) 直接子元素 Name
    for child in node:
        if local_name(child.tag) == "Name" and child.text:
            return child.text.strip()

    # 4) 深层查找
    for child in node.iter():
        if local_name(child.tag) == "Name" and child.text:
            return child.text.strip()

    return None


def detect_control_type(node: ET.Element) -> str:
    """根据 XML 标签名和属性推断控件类型。

    返回: "button", "indicator", "io_field", "symbolic_io_field", "text", "unknown"
    """
    tag = local_name(node.tag).lower()
    name = (detect_control_name(node) or "").lower()
    type_attr = (get_attr_case_insensitive(node, "Type", "type") or "").lower()

    # 按 XML 标签名推断
    if tag in ("button",):
        return "button"
    if tag in ("circle", "ellipse", "rectangle"):
        # TIA 中 Circle/Ellipse 常用作指示灯
        if any(kw in name for kw in ("lmp_", "lamp", "indicator", "ind_")):
            return "indicator"
        # 如果有颜色动画，也是指示灯
        if _has_animation(node, "coloranimation") or _has_animation(node, "flashanimation"):
            return "indicator"
        # 默认按图形处理，但可能是装饰图形
        return "indicator"  # 保守判断：模板中的图形通常是可复用的指示灯
    if tag in ("iofield",):
        return "io_field"
    if tag in ("symboliciofield",):
        return "symbolic_io_field"
    if tag in ("textfield", "text"):
        return "text"

    # 按 Type 属性推断
    if type_attr in ("button",):
        return "button"
    if type_attr in ("iofield", "inputoutputfield"):
        return "io_field"
    if type_attr in ("symboliciofield",):
        return "symbolic_io_field"
    if type_attr in ("textfield", "text"):
        return "text"
    if type_attr in ("circle", "ellipse"):
        return "indicator"

    # 按名称前缀推断
    for prefix, kind in (
        ("btn_", "button"),
        ("lmp_", "indicator"),
        ("lamp_", "indicator"),
        ("ind_", "indicator"),
        ("io_", "io_field"),
        ("sio_", "symbolic_io_field"),
        ("txt_", "text"),
    ):
        if name.startswith(prefix):
            return kind

    return "unknown"


def _has_animation(node: ET.Element, animation_name: str) -> bool:
    """检查节点是否包含指定类型的动画。"""
    for child in node.iter():
        tag = local_name(child.tag).lower()
        if tag == animation_name:
            return True
        if tag == "animations":
            for sub in child:
                if local_name(sub.tag).lower() == animation_name:
                    return True
    return False


def assign_new_ids(node: ET.Element, id_registry: set | None = None) -> None:
    """为克隆节点及其后代分配新的 SimaticML ID，避免与已有 ID 重复。

    修改所有 'ID' 属性的节点（就地修改）。
    """
    if id_registry is None:
        id_registry = set()

    for elem in node.iter():
        for attr_name in ("ID", "UId", "id"):
            if attr_name in elem.attrib:
                old_id = elem.attrib[attr_name]
                new_id = _generate_unique_id(id_registry)
                elem.attrib[attr_name] = new_id
                break


def _generate_unique_id(used_ids: set) -> str:
    """生成唯一的十六进制 ID。"""
    # 尝试从已有 ID 中找到最大 hex 值
    max_value = -1
    for value in used_ids:
        try:
            max_value = max(max_value, int(str(value), 16))
        except (ValueError, TypeError):
            continue

    nxt = max_value + 1 if max_value >= 0 else len(used_ids) + 1
    while True:
        result = format(nxt, "X")
        if result not in used_ids:
            used_ids.add(result)
            return result
        nxt += 1


def collect_existing_ids(root: ET.Element) -> set[str]:
    """收集 XML 树中所有已使用的 ID 属性值。"""
    ids: set[str] = set()
    for elem in root.iter():
        for attr_name in ("ID", "UId", "id"):
            if attr_name in elem.attrib:
                ids.add(str(elem.attrib[attr_name]))
    return ids


def find_parent(root: ET.Element, target: ET.Element) -> ET.Element | None:
    """在 XML 树中查找 target 元素的父节点。"""
    for parent in root.iter():
        for child in list(parent):
            if child is target:
                return parent
    return None


def build_parent_map(root: ET.Element) -> dict:
    """构建 child → parent 映射。"""
    return {child: parent for parent in root.iter() for child in list(parent)}

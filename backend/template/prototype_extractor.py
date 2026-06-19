# -*- coding: utf-8 -*-
"""
模板原型提取器 — 分析模板画面 XML，提取所有可复用控件原型。

输出 TemplateProfile，包含按钮、指示灯及其他控件原型。
"""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET

from .template_profile import (
    ControlPrototype,
    EventPattern,
    ItemKind,
    TagReference,
    TemplateProfile,
)
from .xml_utils import (
    detect_control_name,
    detect_control_type,
    find_text_like_values,
    local_name,
)
from .event_pattern_extractor import extract_event_patterns
from .binding_pattern_extractor import extract_binding_patterns


# 控件名称前缀 → 控件种类
_NAME_PREFIX_MAP: dict[str, ItemKind] = {
    "BTN_": "button",
    "Button": "button",
    "LMP_": "indicator",
    "Lamp": "indicator",
    "Indicator": "indicator",
    "IO_": "io_field",
    "TXT_": "text",
}


def analyze_template_screen(template_xml: str) -> TemplateProfile:
    """输入模板画面 XML，输出 TemplateProfile。

    参数:
        template_xml: 从 TIA Portal 导出的模板画面 XML 字符串。

    返回:
        TemplateProfile 实例，包含所有识别到的控件原型。
    """
    diagnostics: list[str] = []
    all_tag_refs: list[TagReference] = []
    buttons: list[ControlPrototype] = []
    indicators: list[ControlPrototype] = []
    others: list[ControlPrototype] = []

    # 1. 解析 XML
    try:
        root = ET.fromstring(template_xml)
    except ET.ParseError as e:
        diagnostics.append(f"模板 XML 解析失败: {e}")
        return TemplateProfile(diagnostics=diagnostics)

    # 2. 提取画面名称
    screen_name = _extract_screen_name(root)

    # 3. 查找所有控件节点
    control_nodes = _find_control_nodes(root)

    # 4. 分析每个控件
    for node in control_nodes:
        name = detect_control_name(node)
        if not name:
            continue

        kind = _classify_control(name, node)
        tag_refs = _extract_tag_references(node)
        all_tag_refs.extend(tag_refs)

        events = extract_event_patterns(node)
        bindings = extract_binding_patterns(node)

        # 推断 behavior 或 indicator_mode
        behavior = None
        indicator_mode = None
        prototype_id = ""

        if kind == "button":
            behavior = _infer_button_behavior(events, node)
            prototype_id = _button_prototype_id(behavior)
        elif kind == "indicator":
            indicator_mode = _infer_indicator_mode(bindings, name)
            prototype_id = _indicator_prototype_id(indicator_mode)
        else:
            prototype_id = _other_prototype_id(kind, name)

        # 收集可替换变量名
        replaceable_tags = list({t.tag_name for t in tag_refs})

        prototype = ControlPrototype(
            prototype_id=prototype_id,
            source_name=name,
            item_kind=kind,
            behavior=behavior,
            indicator_mode=indicator_mode,
            xml_node=copy.deepcopy(node),
            tag_references=tag_refs,
            event_patterns=events,
            binding_patterns=bindings,
            replaceable_tags=replaceable_tags,
        )

        if kind == "button":
            buttons.append(prototype)
        elif kind == "indicator":
            indicators.append(prototype)
        else:
            others.append(prototype)

    diagnostics.append(
        f"模板分析完成: {len(buttons)} 个按钮, "
        f"{len(indicators)} 个指示灯, {len(others)} 个其他控件"
    )

    return TemplateProfile(
        screen_name=screen_name,
        buttons=buttons,
        indicators=indicators,
        others=others,
        all_tag_references=all_tag_refs,
        diagnostics=diagnostics,
    )


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------


def _extract_screen_name(root: ET.Element) -> str | None:
    """从模板 XML 中提取画面名称。"""
    for elem in root.iter():
        if local_name(elem.tag) == "Screen" or local_name(elem.tag).endswith("Screen"):
            # 属性 Name
            name = elem.get("Name", "").strip()
            if name:
                return name
            # AttributeList → Name
            for child in elem:
                if local_name(child.tag) != "AttributeList":
                    continue
                for attr in child:
                    if local_name(attr.tag) == "Name" and attr.text:
                        return attr.text.strip()
    return None


def _find_control_nodes(root: ET.Element) -> list[ET.Element]:
    """查找所有可能的 HMI 控件节点。"""
    comfort_item_tags = {
        "IOField", "Button", "SymbolicIOField", "Circle",
        "TextField", "Rectangle", "Line", "Ellipse",
        "GraphicView", "TrendView", "Gauge", "Slider",
        "Switch", "Roller", "UserView", "AlarmView",
    }
    generic_item_tags = {"ScreenItem", "Object", "Item", "SW.ScreenItem"}
    all_item_tags = comfort_item_tags | generic_item_tags

    nodes: list[ET.Element] = []
    for elem in root.iter():
        tag = local_name(elem.tag)
        if tag in all_item_tags:
            nodes.append(elem)
    return nodes


def _classify_control(name: str, node: ET.Element) -> ItemKind:
    """根据控件名称和 XML 类型判断控件种类。"""
    xml_type = detect_control_type(node)

    # XML 标签类型优先
    if xml_type == "button":
        return "button"
    if xml_type == "indicator":
        return "indicator"
    if xml_type == "io_field":
        return "io_field"
    if xml_type == "symbolic_io_field":
        return "symbolic_io_field"
    if xml_type == "text":
        return "text"

    # 按名称前缀判断
    name_lower = name.lower()
    for prefix, kind in _NAME_PREFIX_MAP.items():
        if name_lower.startswith(prefix.lower()):
            return kind

    return "unknown"


def _extract_tag_references(node: ET.Element) -> list[TagReference]:
    """从控件节点提取所有变量引用。"""
    refs: list[TagReference] = []

    # ProcessTag / ProcessValue
    for prop_name in ("ProcessTag", "ProcessValue"):
        for child in node.iter():
            if local_name(child.tag) == prop_name and child.text and child.text.strip():
                refs.append(TagReference(
                    tag_name=child.text.strip(),
                    location="property",
                ))

    # EventHandlers 中的 TagName
    tag_props = {"tagname", "variablename"}
    for child in node.iter():
        if local_name(child.tag).lower() in tag_props and child.text and child.text.strip():
            refs.append(TagReference(
                tag_name=child.text.strip(),
                location="event",
            ))

    # Dynamizations 中的 TagName
    for child in node.iter():
        if local_name(child.tag).lower() != "dynamization":
            continue
        for sub in child:
            if local_name(sub.tag).lower() in tag_props and sub.text and sub.text.strip():
                refs.append(TagReference(
                    tag_name=sub.text.strip(),
                    location="dynamization",
                ))

    return refs


def _infer_button_behavior(events: list[EventPattern], node: ET.Element) -> str | None:
    """推断按钮行为模式。

    规则:
    - 同时存在 Press/Release 或 MouseDown/MouseUp 且变量一致 → momentary
    - Click + Toggle → toggle
    - Click + SetBit → set
    - Click + ResetBit → reset
    - ScreenActivate / ChangeScreen → navigate
    """
    event_names = {e.event_name.lower() for e in events}
    action_types = {e.action_type.lower() for e in events if e.action_type}

    # momentary: Press + Release 配对
    if "press" in event_names and "release" in event_names:
        return "momentary"

    # Click + ToggleBit
    if "click" in event_names and "togglebit" in action_types:
        return "toggle"

    # Click + SetBit
    if "click" in event_names and "setbit" in action_types:
        return "set"

    # Click + ResetBit
    if "click" in event_names and "resetbit" in action_types:
        return "reset"

    # Check for navigation (activate_screen / change_screen)
    for ev in events:
        if ev.action_type and ev.action_type.lower() in ("activatescreen", "changescreen"):
            return "navigate"

    # 默认
    return "momentary"


def _infer_indicator_mode(
    bindings: list[any],
    name: str,
) -> str | None:
    """推断指示灯模式。

    规则（优先级从高到低）:
    - 名称含 alarm/报警关键词 → alarm
    - 名称含 warning/警告关键词 → warning
    - 有颜色动画 + 闪烁动画 → bool_blink
    - 有颜色动画(无闪烁) → bool_color
    - 多状态颜色 → multi_state
    - 默认 → status
    """
    from .template_profile import BindingPattern

    # 优先检查名称中的关键词（覆盖绑定推断）
    name_lower = name.lower()
    alarm_keywords = {"alarm", "fault", "error", "报警", "故障"}
    warning_keywords = {"warning", "警告"}

    for kw in alarm_keywords:
        if kw in name_lower:
            return "alarm"
    for kw in warning_keywords:
        if kw in name_lower:
            return "warning"

    # 基于绑定的推断
    binding_kinds = set()
    for b in bindings:
        if isinstance(b, BindingPattern):
            binding_kinds.add(b.binding_kind.lower())
        elif hasattr(b, "binding_kind"):
            binding_kinds.add(str(b.binding_kind).lower())

    has_color = "color" in binding_kinds
    has_flash = "flash" in binding_kinds

    if has_color and has_flash:
        return "bool_blink"
    if has_color:
        return "bool_color"

    return "status"


def _button_prototype_id(behavior: str | None) -> str:
    """根据行为生成按钮原型 ID。"""
    mapping = {
        "momentary": "BTN_MOMENTARY_TEMPLATE",
        "toggle": "BTN_TOGGLE_TEMPLATE",
        "set": "BTN_SET_TEMPLATE",
        "reset": "BTN_RESET_TEMPLATE",
        "navigate": "BTN_NAVIGATE_TEMPLATE",
    }
    return mapping.get(behavior or "", "BTN_DEFAULT_TEMPLATE")


def _indicator_prototype_id(mode: str | None) -> str:
    """根据模式生成指示灯原型 ID。"""
    mapping = {
        "bool_color": "LMP_STATUS_TEMPLATE",
        "bool_blink": "LMP_BLINK_TEMPLATE",
        "multi_state": "LMP_MULTI_STATE_TEMPLATE",
        "alarm": "LMP_ALARM_TEMPLATE",
        "warning": "LMP_WARNING_TEMPLATE",
        "status": "LMP_STATUS_TEMPLATE",
    }
    return mapping.get(mode or "", "LMP_DEFAULT_TEMPLATE")


def _other_prototype_id(kind: ItemKind, name: str) -> str:
    """为非按钮/指示灯控件生成原型 ID。"""
    kind_id = kind.upper() if kind != "unknown" else "OTHER"
    return f"{kind_id}_TEMPLATE"

# -*- coding: utf-8 -*-
"""
模板原型数据模型 — TemplateProfile, ControlPrototype, EventPattern, BindingPattern,
TagReference 等。

不依赖 Flask、pythonnet 或 Siemens DLL。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ItemKind = Literal["button", "indicator", "io_field", "symbolic_io_field", "text", "unknown"]


@dataclass
class TagReference:
    """变量引用 — 记录模板控件中引用的变量名及其位置。"""

    tag_name: str
    location: str  # "event", "dynamization", "property", "script", "text"
    xml_path: str | None = None
    raw_value: str | None = None


@dataclass
class EventPattern:
    """事件模式 — 描述模板控件中一个事件及其关联的变量引用。"""

    event_name: str  # "Press", "Release", "Click", "MouseDown", ...
    action_type: str | None = None  # "set_bit", "reset_bit", "toggle_bit", ...
    tag_references: list[TagReference] = field(default_factory=list)
    raw_xml: str | None = None


@dataclass
class BindingPattern:
    """动态绑定模式 — 描述模板控件中一个动态属性绑定及其变量引用。"""

    binding_kind: str  # "color", "flash", "visibility", "process_value", ...
    property_name: str | None = None
    tag_references: list[TagReference] = field(default_factory=list)
    raw_xml: str | None = None


@dataclass
class ControlPrototype:
    """控件原型 — 从模板 XML 中提取的可复用控件模板。"""

    prototype_id: str
    source_name: str  # 模板中控件的原始名称
    item_kind: ItemKind
    behavior: str | None = None  # "momentary", "toggle", "set", "reset", "navigate"
    indicator_mode: str | None = None  # "bool_color", "bool_blink", "multi_state", "alarm", "warning", "status"
    xml_node: Any | None = None  # xml.etree.ElementTree.Element (深拷贝)
    tag_references: list[TagReference] = field(default_factory=list)
    event_patterns: list[EventPattern] = field(default_factory=list)
    binding_patterns: list[BindingPattern] = field(default_factory=list)
    replaceable_tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TemplateProfile:
    """模板画面档案 — 对模板 XML 的完整分析结果。"""

    screen_name: str | None = None
    buttons: list[ControlPrototype] = field(default_factory=list)
    indicators: list[ControlPrototype] = field(default_factory=list)
    others: list[ControlPrototype] = field(default_factory=list)
    all_tag_references: list[TagReference] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)

    def all_prototypes(self) -> list[ControlPrototype]:
        """返回所有原型（按钮 + 指示灯 + 其他）。"""
        return self.buttons + self.indicators + self.others

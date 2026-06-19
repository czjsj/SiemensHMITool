# -*- coding: utf-8 -*-
"""Unified Reflection Adapter — 运行时类型反射与版本适配。

方案文档 §11.3 对齐。
"""
from __future__ import annotations
from typing import Any


class UnifiedReflectionAdapter:
    """Unified 运行时反射适配器。

    缓存在 runtime_cache/<tia-version>/<assembly-hash>.json。
    """

    # 控件类型 key → 候选 .NET 类型名列表
    UNIFIED_TYPE_KEYS: dict[str, list[str]] = {
        "button": ["HmiButton"],
        "io_field": ["HmiIOField", "HmiIoField"],
        "text": ["HmiTextBox", "HmiTextBlock"],
        "rectangle": ["HmiRectangle"],
        "ellipse": ["HmiEllipse"],
        "switch": ["HmiSwitch"],
        "slider": ["HmiSlider"],
        "graphic_view": ["HmiGraphicView"],
        "symbolic_io_field": ["HmiSymbolicIOField"],
        "indicator": ["HmiCircle", "HmiEllipse"],
    }

    # 属性 IR 名 → 候选 .NET 属性名列表
    PROPERTY_ALIASES: dict[str, list[str]] = {
        "left": ["Left", "X"],
        "top": ["Top", "Y"],
        "width": ["Width"],
        "height": ["Height"],
        "visible": ["Visible"],
        "enabled": ["Enabled", "Operability"],
        "background_color": ["BackColor", "BackgroundColor"],
        "foreground_color": ["ForeColor", "ForegroundColor"],
        "text": ["Text"],
        "font_size": ["FontSize"],
        "bold": ["Bold"],
    }

    # 语义事件 → 候选 Unified 事件枚举值
    EVENT_CANDIDATES: dict[str, list[str]] = {
        "press": ["Pressed", "PointerDown", "OnPress"],
        "release": ["Released", "PointerUp", "OnRelease"],
        "click": ["Clicked", "Click", "Tapped"],
        "change": ["Changed", "ValueChanged"],
        "loaded": ["Loaded"],
        "unloaded": ["Unloaded"],
        "activate": ["Activated"],
        "deactivate": ["Deactivated"],
    }

    def __init__(self):
        self._type_cache: dict[str, Any] = {}
        self._enum_cache: dict[str, Any] = {}

    def find_type(self, candidates: list[str]) -> Any | None:
        for name in candidates:
            if name in self._type_cache:
                return self._type_cache[name]
        return None

    def get_enum_values(self, enum_type_name: str) -> list[str]:
        cached = self._enum_cache.get(enum_type_name)
        if cached:
            return cached
        return []

    def has_property(self, obj: Any, name: str) -> bool:
        try:
            return hasattr(obj, name)
        except Exception:
            return False

    def resolve_type_key(self, item_type_key: str) -> list[str]:
        return self.UNIFIED_TYPE_KEYS.get(item_type_key, [item_type_key])

    def resolve_property(self, property_key: str) -> list[str]:
        return self.PROPERTY_ALIASES.get(property_key, [property_key])

    def resolve_event(self, semantic_event: str) -> list[str]:
        return self.EVENT_CANDIDATES.get(semantic_event, [semantic_event])

    def set_first_supported(self, obj: Any, names: list[str], value) -> bool:
        for name in names:
            try:
                if hasattr(obj, name):
                    setattr(obj, name, value)
                    return True
            except Exception:
                continue
        return False

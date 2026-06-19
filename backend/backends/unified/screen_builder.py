# -*- coding: utf-8 -*-
"""Unified Screen Builder — Screen 和 ScreenItem 创建。"""
from __future__ import annotations
from backend.domain.ir_v2 import ScreenSpec, ScreenItemSpec
from backend.domain.enums import ScreenItemType


class UnifiedScreenBuilder:
    """Unified 画面和控件创建器。"""

    def __init__(self):
        self._reflection = None  # 延迟注入 UnifiedReflectionAdapter

    def create_screen_spec(self, screen: ScreenSpec) -> dict:
        return {
            "Name": screen.name,
            "Width": screen.width,
            "Height": screen.height,
            "BackgroundColor": screen.background_color,
            "Folder": screen.folder or "",
            "ItemCount": len(screen.items),
        }

    def create_item_spec(self, item: ScreenItemSpec) -> dict:
        geo = item.geometry
        spec = {
            "Name": item.id,
            "Type": item.type.value,
            "Left": geo.x,
            "Top": geo.y,
            "Width": geo.width,
            "Height": geo.height,
        }
        if geo.radius:
            spec["Radius"] = geo.radius
        if item.tag_binding:
            spec["TagBinding"] = item.tag_binding
        if item.text:
            spec["Text"] = item.text
        return spec

    def apply_static_properties(self, item_spec: ScreenItemSpec) -> dict:
        """将静态属性转换为 Unified 可设置的值。"""
        props = dict(item_spec.properties)
        if item_spec.text:
            props["Text"] = item_spec.text
        return props

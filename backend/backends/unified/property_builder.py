# -*- coding: utf-8 -*-
"""Unified Property Builder — 静态属性映射。"""
from __future__ import annotations
from typing import Any


class UnifiedPropertyBuilder:
    """Unified 静态属性设置器。

    按白名单映射属性名到 Unified API 属性名。
    """

    def __init__(self):
        pass

    def map_properties(self, item_properties: dict[str, Any]) -> dict[str, Any]:
        """映射属性名到 Unified 属性（用 whitespace aliases）。"""
        mapped = {}
        aliases = {
            "left": "Left", "top": "Top", "x": "Left", "y": "Top",
            "width": "Width", "height": "Height",
            "visible": "Visible", "enabled": "Enabled",
            "background_color": "BackColor", "foreground_color": "ForeColor",
            "text": "Text", "font_size": "FontSize", "bold": "Bold",
            "mode": "Mode", "display_format": "OutputFormat",
            "decimal_digits": "DecimalDigits",
        }
        for k, v in item_properties.items():
            mapped[aliases.get(k, k)] = v
        return mapped

    def hex_to_argb(self, hex_color: str) -> int:
        c = (hex_color or "#000000").lstrip("#")
        if len(c) == 6:
            r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
            return (255 << 24) | (r << 16) | (g << 8) | b
        return 0xFF000000

# -*- coding: utf-8 -*-
"""Dynamic XML Builder — BindingSpec → Classic HMI 动态化 XML。

方案文档 §9.4, §10.4, §13.4 对齐。
"""
from __future__ import annotations
from xml.sax.saxutils import escape as xml_escape
from backend.domain.ir_v2 import BindingSpec
from backend.domain.enums import BindingKind


class DynamicXmlBuilder:
    """Classic HMI 动态属性 XML 生成器。

    将 BindingSpec 映射到 Discrete/Range/Linear/Flashing 等动态化 XML fragment。
    """

    # 属性名 → WinCC 动态化属性名
    PROPERTY_ALIASES = {
        "visible": "Visible",
        "background_color": "BackColor",
        "foreground_color": "ForeColor",
        "text": "Text",
        "position_x": "PositionX",
        "position_y": "PositionY",
        "width": "Width",
        "height": "Height",
        "flashing": "Flashing",
        "enabled": "Enabled",
    }

    def __init__(self):
        self._supported = {
            "visible",
            "background_color",
            "foreground_color",
            "text",
            "position_x",
            "position_y",
            "width",
            "height",
            "flashing",
            "enabled",
        }

    def build(self, binding: BindingSpec, item_type: str = "") -> str:
        prop_name = self.PROPERTY_ALIASES.get(binding.property, binding.property)
        source = xml_escape(binding.source_tag or "")

        if binding.kind == BindingKind.DIRECT_TAG:
            return self._build_direct_tag(prop_name, source)

        if binding.kind == BindingKind.DISCRETE:
            states = binding.config.get("states", [])
            return self._build_discrete(prop_name, source, states)

        if binding.kind == BindingKind.RANGE:
            ranges = binding.config.get("ranges", [])
            return self._build_range(prop_name, source, ranges)

        if binding.kind == BindingKind.LINEAR:
            return self._build_linear(prop_name, source, binding.config)

        if binding.kind == BindingKind.FLASHING:
            return self._build_flashing(prop_name, source)

        if binding.kind == BindingKind.EXPRESSION:
            return self._build_expression(prop_name, binding.config.get("expression", ""))

        return f'<!-- unsupported binding kind: {binding.kind.value} -->'

    def _build_direct_tag(self, prop_name: str, source: str) -> str:
        return (
            f'<Dynamization Property="{prop_name}" Type="Tag">\n'
            f'  <TagName>{source}</TagName>\n'
            f'</Dynamization>'
        )

    def _build_discrete(self, prop_name: str, source: str, states: list) -> str:
        lines = [
            f'<Dynamization Property="{prop_name}" Type="Discrete">',
            f'  <TagName>{source}</TagName>',
        ]
        for state in states:
            val = xml_escape(str(state.get("value", "")))
            out = xml_escape(str(state.get("output", "")))
            lines.append(f'  <State Value="{val}" Output="{out}"/>')
        lines.append(f'</Dynamization>')
        return "\n".join(lines)

    def _build_range(self, prop_name: str, source: str, ranges: list) -> str:
        lines = [
            f'<Dynamization Property="{prop_name}" Type="Range">',
            f'  <TagName>{source}</TagName>',
        ]
        for r in ranges:
            lo = xml_escape(str(r.get("low", "")))
            hi = xml_escape(str(r.get("high", "")))
            out = xml_escape(str(r.get("output", "")))
            lines.append(f'  <Range Low="{lo}" High="{hi}" Output="{out}"/>')
        lines.append(f'</Dynamization>')
        return "\n".join(lines)

    def _build_linear(self, prop_name: str, source: str, config: dict) -> str:
        out_lo = xml_escape(str(config.get("output_low", "")))
        out_hi = xml_escape(str(config.get("output_high", "")))
        return (
            f'<Dynamization Property="{prop_name}" Type="Linear">\n'
            f'  <TagName>{source}</TagName>\n'
            f'  <OutputLow>{out_lo}</OutputLow>\n'
            f'  <OutputHigh>{out_hi}</OutputHigh>\n'
            f'</Dynamization>'
        )

    def _build_flashing(self, prop_name: str, source: str) -> str:
        return (
            f'<Dynamization Property="Flashing" Type="Flashing">\n'
            f'  <TagName>{source}</TagName>\n'
            f'</Dynamization>'
        )

    def _build_expression(self, prop_name: str, expr: str) -> str:
        return (
            f'<Dynamization Property="{prop_name}" Type="Expression">\n'
            f'  <Expression>{xml_escape(expr)}</Expression>\n'
            f'</Dynamization>'
        )

    def supports_property(self, property_name: str) -> bool:
        return property_name in self._supported

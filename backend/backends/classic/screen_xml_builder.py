# -*- coding: utf-8 -*-
"""Classic XML Screen Builder — 基于黄金模板生成画面 XML。

方案文档 §9, §10 对齐。
"""
from __future__ import annotations
import uuid
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as xml_escape
from backend.domain.ir_v2 import ScreenSpec, ScreenItemSpec
from backend.domain.enums import ScreenItemType


def _geo_attrs(x: int, y: int, w: int, h: int) -> str:
    return f'<Left>{x}</Left><Top>{y}</Top><Width>{w}</Width><Height>{h}</Height>'


class ScreenXmlBuilder:
    """Classic HMI 画面 XML 生成器。

    基于目标设备黄金模板导出 fragment 构建 Screen XML。
    """

    def __init__(self):
        self._ns = "http://www.siemens.com/automation/SimaticML"

    def build_screen_header(self, screen: ScreenSpec, screen_id: str = "") -> str:
        sid = screen_id or str(uuid.uuid4())
        return (
            f'<?xml version="1.0" encoding="utf-8"?>\n'
            f'<Document xmlns="{self._ns}">\n'
            f'  <Engineering version="V18"/>\n'
            f'  <SW.Blocks>\n'
            f'    <SW.ScreenFolder>\n'
            f'      <SW.Screen ID="{sid}" Name="{xml_escape(screen.name)}" CompositionType="Screen">\n'
            f'        <AttributeList>\n'
            f'          <Name>{xml_escape(screen.name)}</Name>\n'
            f'          <Width>{screen.width}</Width>\n'
            f'          <Height>{screen.height}</Height>\n'
            f'          <BackgroundColor>{xml_escape(screen.background_color)}</BackgroundColor>\n'
            f'        </AttributeList>\n'
        )

    def build_screen_footer(self) -> str:
        return (
            f'      </SW.Screen>\n'
            f'    </SW.ScreenFolder>\n'
            f'  </SW.Blocks>\n'
            f'</Document>'
        )

    def build_screen_item(self, item: ScreenItemSpec) -> str:
        sid = str(uuid.uuid4())
        xml_tag = self._item_type_to_xml_tag(item.type)
        geo = item.geometry
        lines = [
            f'<ScreenItem ID="{sid}" Name="{xml_escape(item.id)}" Type="{xml_tag}">',
            f'  <Geometry>',
            f'    <X>{geo.x}</X><Y>{geo.y}</Y><Width>{geo.width}</Width><Height>{geo.height}</Height>',
            f'  </Geometry>',
            f'  <Properties>',
        ]
        if item.tag_binding:
            lines.append(f'    <ProcessTag>{xml_escape(item.tag_binding)}</ProcessTag>')
        if item.text:
            for lang, txt in item.text.items():
                lines.append(f'    <Text Language="{xml_escape(lang)}">{xml_escape(txt)}</Text>')
        if item.properties.get("background_color"):
            lines.append(f'    <BackColor>{xml_escape(str(item.properties["background_color"]))}</BackColor>')
        if item.properties.get("font_size"):
            lines.append(f'    <FontSize>{item.properties["font_size"]}</FontSize>')
        if item.properties.get("mode"):
            lines.append(f'    <Mode>{xml_escape(item.properties["mode"])}</Mode>')
        lines.append(f'  </Properties>')
        lines.append(f'</ScreenItem>')
        return "\n".join(lines)

    def build_screen(self, screen: ScreenSpec) -> str:
        parts = [self.build_screen_header(screen)]
        parts.append(f'        <ObjectList>')
        for item in screen.items:
            parts.append(f'          {self.build_screen_item(item)}')
        parts.append(f'        </ObjectList>')
        parts.append(self.build_screen_footer())
        return "\n".join(parts)

    @staticmethod
    def _item_type_to_xml_tag(item_type: ScreenItemType) -> str:
        mapping = {
            ScreenItemType.BUTTON: "Button",
            ScreenItemType.IO_FIELD: "IOField",
            ScreenItemType.SYMBOLIC_IO_FIELD: "SymbolicIOField",
            ScreenItemType.INDICATOR: "Circle",
            ScreenItemType.TEXT: "TextField",
            ScreenItemType.RECTANGLE: "Rectangle",
            ScreenItemType.ELLIPSE: "Ellipse",
            ScreenItemType.SWITCH: "Switch",
            ScreenItemType.SLIDER: "Slider",
            ScreenItemType.GRAPHIC_VIEW: "GraphicView",
            ScreenItemType.SCREEN_WINDOW: "ScreenWindow",
        }
        return mapping.get(item_type, "ScreenItem")

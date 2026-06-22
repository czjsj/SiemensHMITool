# -*- coding: utf-8 -*-
"""Classic XML Screen Builder — 基于黄金模板生成画面 XML。

方案文档 §9, §10 对齐。
V3.2: 增强 ProcessTag、TextList、FunctionList Event 生成。
"""
from __future__ import annotations
import uuid
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as xml_escape
from backend.domain.ir_v2 import ScreenSpec, ScreenItemSpec, EventSpec, ActionSpec
from backend.domain.enums import ScreenItemType, SemanticEvent, SemanticActionType


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
        """生成单个控件的 XML fragment。

        包含:
          - ProcessTag（IOField, SymbolicIOField）
          - TextList 引用（SymbolicIOField）
          - 多语言文本
          - 静态属性
        """
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

        # ProcessValue — IOField/SymbolicIOField 直接过程值绑定。
        # IOField 需要 Type="Tag"，SymbolicIOField 不支持显式 Type。
        if item.tag_binding:
            if item.type == ScreenItemType.IO_FIELD:
                lines.append(f'    <ProcessValue Type="Tag">{xml_escape(item.tag_binding)}</ProcessValue>')
            elif item.type == ScreenItemType.SYMBOLIC_IO_FIELD:
                lines.append(f'    <ProcessValue>{xml_escape(item.tag_binding)}</ProcessValue>')
            else:
                lines.append(f'    <ProcessTag>{xml_escape(item.tag_binding)}</ProcessTag>')

        # TextList — SymbolicIOField 必须
        if item.type == ScreenItemType.SYMBOLIC_IO_FIELD:
            text_list = item.properties.get("text_list", "")
            if text_list:
                lines.append(f'    <TextList>{xml_escape(text_list)}</TextList>')

        # 多语言文本
        if item.text:
            for lang, txt in item.text.items():
                lines.append(f'    <Text Language="{xml_escape(lang)}">{xml_escape(txt)}</Text>')

        # 静态属性
        if item.properties.get("background_color"):
            lines.append(f'    <BackColor>{xml_escape(str(item.properties["background_color"]))}</BackColor>')
        if item.properties.get("font_size"):
            lines.append(f'    <FontSize>{item.properties["font_size"]}</FontSize>')
        if item.properties.get("mode"):
            lines.append(f'    <Mode>{xml_escape(item.properties["mode"])}</Mode>')

        lines.append(f'  </Properties>')

        # V3.2: Events/Functions — Button 的 Press/Release/Click
        if item.events:
            lines.append(f'  <Events>')
            for event in item.events:
                lines.append(self._build_event_xml(event))
            lines.append(f'  </Events>')

        # Dynamic bindings — Indicator 颜色/闪烁
        if item.bindings:
            lines.append(f'  <DynamicBindings>')
            for binding in item.bindings:
                lines.append(self._build_dynamic_binding_xml(binding))
            lines.append(f'  </DynamicBindings>')

        lines.append(f'</ScreenItem>')
        return "\n".join(lines)

    def _build_event_xml(self, event: EventSpec) -> str:
        """为 Button 生成 Event XML（Press/Release/Click + FunctionList）。

        瞬时按钮生成:
          <Event Name="Press">
            <FunctionList>
              <Function Number="0" Type="SetBit">
                <TagName>变量名</TagName>
              </Function>
            </FunctionList>
          </Event>
          <Event Name="Release">
            <FunctionList>
              <Function Number="1" Type="ResetBit">
                <TagName>变量名</TagName>
              </Function>
            </FunctionList>
          </Event>
        """
        ev_name = self._event_name(event.event)
        lines = [f'    <Event Name="{ev_name}">']
        lines.append(f'      <FunctionList>')

        for idx, action in enumerate(event.actions):
            func_type = self._action_to_sys_func(action.type)
            lines.append(f'        <Function Number="{idx}" Type="{func_type}">')
            if action.tag:
                lines.append(f'          <TagName>{xml_escape(action.tag)}</TagName>')
            if action.value is not None:
                lines.append(f'          <Value>{xml_escape(str(action.value))}</Value>')
            if action.screen:
                lines.append(f'          <ScreenName>{xml_escape(action.screen)}</ScreenName>')
            lines.append(f'        </Function>')

        lines.append(f'      </FunctionList>')
        lines.append(f'    </Event>')
        return "\n".join(lines)

    def _build_dynamic_binding_xml(self, binding) -> str:
        """为 Indicator 生成动态绑定 XML（颜色范围动画）。

        <RangeAppearanceAnimation>
          <TagElementTrigger>
            <LinkList>
              <Tag TargetID="@OpenLink"><Name>变量名</Name></Tag>
            </LinkList>
          </TagElementTrigger>
          <Range LowerLimit="0" UpperLimit="0" BackColor="..."/>
          <Range LowerLimit="1" UpperLimit="1" BackColor="..."/>
        </RangeAppearanceAnimation>
        """
        from backend.domain.ir_v2 import BindingSpec
        from backend.domain.enums import BindingKind

        lines = [f'      <DynamicBinding>']
        source_tag = getattr(binding, 'source_tag', '') or ''
        kind = getattr(binding, 'kind', None)
        config = getattr(binding, 'config', {}) or {}
        lines.append(f'        <TagElementTrigger>')
        lines.append(f'          <LinkList>')
        lines.append(f'            <Tag TargetID="@OpenLink">')
        lines.append(f'              <Name>{xml_escape(source_tag)}</Name>')
        lines.append(f'            </Tag>')
        lines.append(f'          </LinkList>')
        lines.append(f'        </TagElementTrigger>')

        # 离散状态映射
        states = config.get("states", [])
        for state in states:
            val = state.get("value", 0)
            color = state.get("output", "#3A4250")
            lines.append(f'        <Range>')
            lines.append(f'          <LowerLimit>{val}</LowerLimit>')
            lines.append(f'          <UpperLimit>{val}</UpperLimit>')
            lines.append(f'          <BackColor>{xml_escape(color)}</BackColor>')
            lines.append(f'        </Range>')

        lines.append(f'      </DynamicBinding>')
        return "\n".join(lines)

    def build_screen(self, screen: ScreenSpec) -> str:
        """生成完整画面 XML。"""
        parts = [self.build_screen_header(screen)]
        parts.append(f'        <ObjectList>')
        for item in screen.items:
            parts.append(f'          {self.build_screen_item(item)}')
        parts.append(f'        </ObjectList>')
        parts.append(self.build_screen_footer())
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # 静态映射方法
    # ------------------------------------------------------------------

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

    @staticmethod
    def _event_name(event: SemanticEvent) -> str:
        mapping = {
            SemanticEvent.PRESS: "Press",
            SemanticEvent.RELEASE: "Release",
            SemanticEvent.CLICK: "Click",
            SemanticEvent.CHANGE: "Change",
            SemanticEvent.LOADED: "Loaded",
            SemanticEvent.UNLOADED: "Unloaded",
            SemanticEvent.ACTIVATE: "Activate",
            SemanticEvent.DEACTIVATE: "Deactivate",
        }
        return mapping.get(event, "Click")

    @staticmethod
    def _action_to_sys_func(action: SemanticActionType) -> str:
        mapping = {
            SemanticActionType.SET_BIT: "SetBit",
            SemanticActionType.RESET_BIT: "ResetBit",
            SemanticActionType.TOGGLE_BIT: "InvertBit",
            SemanticActionType.SET_VALUE: "SetValue",
            SemanticActionType.INCREMENT: "IncreaseValue",
            SemanticActionType.DECREMENT: "DecreaseValue",
            SemanticActionType.ACTIVATE_SCREEN: "ActivateScreen",
            SemanticActionType.OPEN_POPUP: "OpenPopup",
            SemanticActionType.CLOSE_POPUP: "ClosePopup",
            SemanticActionType.ACKNOWLEDGE_ALARM: "AcknowledgeAlarm",
        }
        return mapping.get(action, "SetValue")

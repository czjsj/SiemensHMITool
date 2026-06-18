# -*- coding: utf-8 -*-
"""测试模板 XML 改写模块。"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.template_xml_generator import generate_from_template_xml


# 一个最小的模拟 WinCC Comfort 模板 XML
MINIMAL_TEMPLATE_XML = r'''<?xml version="1.0" encoding="utf-8"?>
<Document xmlns="http://www.siemens.com/automation/SimaticML">
  <Engineering version="V18" />
  <SW.Blocks>
    <SW.ScreenFolder>
      <Screen ID="{00000000-0000-0000-0000-000000000001}" Name="Template_Screen" CompositionType="Screen">
        <AttributeList>
          <Name>Template_Screen</Name>
          <DisplayName>Template Screen</DisplayName>
          <Width>1280</Width>
          <Height>800</Height>
        </AttributeList>
        <ObjectList>
          <ScreenItem ID="{00000000-0000-0000-0000-000000000002}" Name="TXT_Template" Type="TextField">
            <Geometry>
              <X>100</X>
              <Y>50</Y>
              <Width>200</Width>
              <Height>40</Height>
            </Geometry>
            <Properties>
              <Text>Template Text</Text>
              <FontSize>18</FontSize>
            </Properties>
          </ScreenItem>
          <ScreenItem ID="{00000000-0000-0000-0000-000000000003}" Name="BTN_Template" Type="Button">
            <Geometry>
              <X>100</X>
              <Y>200</Y>
              <Width>120</Width>
              <Height>50</Height>
            </Geometry>
            <Properties>
              <Text>Template Button</Text>
              <BackColor>43,182,115</BackColor>
            </Properties>
            <Events>
              <Event Name="Press">
                <VBSFunction>Sub_Template</VBSFunction>
              </Event>
            </Events>
          </ScreenItem>
          <ScreenItem ID="{00000000-0000-0000-0000-000000000004}" Name="IO_Template" Type="IOField">
            <Geometry>
              <X>100</X>
              <Y>320</Y>
              <Width>160</Width>
              <Height>44</Height>
            </Geometry>
            <Properties>
              <Mode>Output</Mode>
              <OutputFormat>Decimal</OutputFormat>
            </Properties>
            <Connection>
              <ProcessTag>Tag_Template</ProcessTag>
            </Connection>
          </ScreenItem>
        </ObjectList>
      </Screen>
    </SW.ScreenFolder>
  </SW.Blocks>
</Document>'''


def make_ir(screen_name="My_Screen", objects=None):
    """构建最小可用的 IR dict。"""
    return {
        "meta": {
            "screen_name": screen_name,
            "title": "My Screen",
            "hmi_type": "Comfort",
            "resolution": "1280x800",
        },
        "objects": objects or [],
        "_screen_size": {"width": 1280, "height": 800},
    }


class TestTemplateXmlGenerator:
    """模板 XML 生成器测试套件。"""

    def test_can_modify_screen_name(self):
        """能修改画面名称。"""
        ir = make_ir("Motor_Control")
        new_xml, warnings = generate_from_template_xml(ir, MINIMAL_TEMPLATE_XML)
        assert "Motor_Control" in new_xml
        assert "<Name>Motor_Control</Name>" in new_xml

    def test_can_modify_text(self):
        """能修改 Text 对象的文本。"""
        ir = make_ir("T1", [
            {"id": "TXT_Title", "type": "Text", "x": 100, "y": 50, "width": 200, "height": 40, "text": "新标题", "template_ref": "TXT_Template"},
        ])
        new_xml, warnings = generate_from_template_xml(ir, MINIMAL_TEMPLATE_XML)
        assert "新标题" in new_xml

    def test_can_modify_coordinates(self):
        """能修改坐标属性。"""
        ir = make_ir("T1", [
            {"id": "BTN_Go", "type": "Button", "x": 300, "y": 400, "width": 150, "height": 60, "text": "执行", "template_ref": "BTN_Template"},
        ])
        new_xml, warnings = generate_from_template_xml(ir, MINIMAL_TEMPLATE_XML)
        assert "<X>300</X>" in new_xml
        assert "<Y>400</Y>" in new_xml
        assert "<Width>150</Width>" in new_xml
        assert "<Height>60</Height>" in new_xml

    def test_can_modify_process_tag(self):
        """能修改变量连接。"""
        ir = make_ir("T1", [
            {"id": "IO_Speed", "type": "IOField", "x": 100, "y": 320, "width": 160, "height": 44, "process_tag": "Motor_Speed", "template_ref": "IO_Template"},
        ])
        new_xml, warnings = generate_from_template_xml(ir, MINIMAL_TEMPLATE_XML)
        assert "Motor_Speed" in new_xml

    def test_unmatched_object_returns_warning(self):
        """找不到模板控件时返回 warning（使用模板中没有的 Indicator 类型）。"""
        ir = make_ir("T1", [
            {"id": "LMP_NoMatch", "type": "Indicator", "x": 0, "y": 0, "radius": 22, "process_tag": "X", "template_ref": "NonExistentIndicator"},
        ])
        new_xml, warnings = generate_from_template_xml(ir, MINIMAL_TEMPLATE_XML)
        assert len(warnings) > 0
        assert any("未找到" in w for w in warnings)

    def test_preserves_namespace(self):
        """不改写命名空间。"""
        ir = make_ir("T1", [
            {"id": "TXT_A", "type": "Text", "x": 100, "y": 50, "text": "A", "template_ref": "TXT_Template"},
        ])
        new_xml, warnings = generate_from_template_xml(ir, MINIMAL_TEMPLATE_XML)
        assert "xmlns=\"http://www.siemens.com/automation/SimaticML\"" in new_xml or "xmlns=" in new_xml

    def test_preserves_original_structure(self):
        """保持原始结构，包含 SW.Blocks / SW.ScreenFolder。"""
        ir = make_ir("T1", [
            {"id": "TXT_A", "type": "Text", "x": 100, "y": 50, "text": "A", "template_ref": "TXT_Template"},
        ])
        new_xml, warnings = generate_from_template_xml(ir, MINIMAL_TEMPLATE_XML)
        assert "SW.Blocks" in new_xml
        assert "SW.ScreenFolder" in new_xml
        assert "ObjectList" in new_xml

    def test_duplicate_template_refs_work(self):
        """多个对象引用同一模板控件不崩溃。"""
        ir = make_ir("T1", [
            {"id": "TXT_A", "type": "Text", "x": 100, "y": 50, "text": "A", "template_ref": "TXT_Template"},
            {"id": "BTN_X", "type": "Button", "x": 200, "y": 200, "text": "X", "template_ref": "BTN_Template"},
        ])
        new_xml, warnings = generate_from_template_xml(ir, MINIMAL_TEMPLATE_XML)

    def test_empty_objects_no_crash(self):
        """空对象列表不崩溃。"""
        ir = make_ir("Empty")
        new_xml, warnings = generate_from_template_xml(ir, MINIMAL_TEMPLATE_XML)
        assert "Empty" in new_xml

    def test_broken_xml_returns_original(self):
        """损坏的 XML 返回原始字符串并带 warning。"""
        ir = make_ir("T1")
        new_xml, warnings = generate_from_template_xml(ir, "<not>valid<xml>>")
        assert warnings
        assert any("解析失败" in w for w in warnings)

    def test_match_by_prefix(self):
        """按名称前缀匹配模板控件。"""
        ir = make_ir("T1", [
            {"id": "TXT_NewText", "type": "Text", "x": 100, "y": 50, "width": 200, "height": 40, "text": "前缀匹配"},
        ])
        new_xml, warnings = generate_from_template_xml(ir, MINIMAL_TEMPLATE_XML)
        assert "前缀匹配" in new_xml

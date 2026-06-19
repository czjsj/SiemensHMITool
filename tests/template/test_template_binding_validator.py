# -*- coding: utf-8 -*-
"""测试模板绑定校验器 — 导入前 XML 检查。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from backend.template.template_binding_validator import validate_generated_screen_xml


class TestTemplateBindingValidator:
    """测试 pre-import XML 校验。"""

    def test_empty_xml_fails(self):
        """空 XML 无法解析。"""
        diags = validate_generated_screen_xml("", [], [], [])
        errors = [d for d in diags if d["severity"] == "error"]
        assert len(errors) >= 1

    def test_placeholder_remaining_blocked(self):
        """有模板变量残留时阻断。"""
        xml = """
        <Document xmlns="http://www.siemens.com/automation/SimaticML">
          <SW.Screen Name="Test">
            <AttributeList><Name>Test</Name><Width>1280</Width><Height>800</Height></AttributeList>
            <ObjectList>
              <Hmi.Screen.Button ID="1">
                <AttributeList><ObjectName>BTN_Test</ObjectName><ProcessTag>Template_BTN_Tag</ProcessTag></AttributeList>
              </Hmi.Screen.Button>
            </ObjectList>
          </SW.Screen>
        </Document>
        """
        diags = validate_generated_screen_xml(
            xml,
            expected_tags=["BTN_Test"],
            forbidden_placeholder_tags=["Template_BTN_Tag"],
            expected_items=["BTN_Test"],
        )
        errors = [d for d in diags if d["severity"] == "error"]
        assert len(errors) >= 1
        assert any("Template_BTN_Tag" in d["message"] for d in errors)

    def test_normal_xml_passes(self):
        """正常 XML 可以通过。"""
        xml = """
        <Document xmlns="http://www.siemens.com/automation/SimaticML">
          <SW.Screen Name="Test">
            <AttributeList><Name>Test</Name><Width>1280</Width><Height>800</Height></AttributeList>
            <ObjectList>
              <Hmi.Screen.Button ID="1">
                <AttributeList><ObjectName>BTN_Start</ObjectName><ProcessTag>BTN_Motor_Start</ProcessTag></AttributeList>
              </Hmi.Screen.Button>
            </ObjectList>
          </SW.Screen>
        </Document>
        """
        diags = validate_generated_screen_xml(
            xml,
            expected_tags=["BTN_Motor_Start"],
            forbidden_placeholder_tags=["Template_BTN_Tag"],
            expected_items=["BTN_Start"],
        )
        errors = [d for d in diags if d["severity"] == "error"]
        assert len(errors) == 0, f"Unexpected errors: {[d['message'] for d in errors]}"

    def test_duplicate_control_names_blocked(self):
        """控件名重复时阻断。"""
        xml = """
        <Document xmlns="http://www.siemens.com/automation/SimaticML">
          <SW.Screen Name="Test">
            <AttributeList><Name>Test</Name><Width>1280</Width><Height>800</Height></AttributeList>
            <ObjectList>
              <Hmi.Screen.Button ID="1">
                <AttributeList><ObjectName>BTN_Dup</ObjectName></AttributeList>
              </Hmi.Screen.Button>
              <Hmi.Screen.Button ID="2">
                <AttributeList><ObjectName>BTN_Dup</ObjectName></AttributeList>
              </Hmi.Screen.Button>
            </ObjectList>
          </SW.Screen>
        </Document>
        """
        diags = validate_generated_screen_xml(xml, [], [], ["BTN_Dup"])
        errors = [d for d in diags if d["severity"] == "error"]
        assert len(errors) >= 1

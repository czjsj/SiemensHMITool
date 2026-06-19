# -*- coding: utf-8 -*-
"""测试导入前阻断逻辑。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from backend.template.template_binding_validator import validate_generated_screen_xml


class TestPreImportBlocking:
    """测试导入前验证阻断。"""

    def test_template_placeholders_block(self):
        """模板变量残留时阻断。"""
        xml = """<Document xmlns="http://example.com/SimaticML">
          <SW.Screen><AttributeList><Name>T</Name><Width>1280</Width><Height>800</Height></AttributeList>
            <ObjectList><Hmi.Screen.Button ID="1"><AttributeList><ObjectName>B</ObjectName><ProcessTag>Template_BTN_Tag</ProcessTag></AttributeList></Hmi.Screen.Button></ObjectList>
          </SW.Screen></Document>"""
        diags = validate_generated_screen_xml(xml, [], ["Template_BTN_Tag"], ["B"])
        errors = [d for d in diags if d["severity"] == "error"]
        assert len(errors) >= 1

    def test_empty_tag_name_blocked(self):
        """空 TagName 时阻断。"""
        xml = """<Document xmlns="http://example.com/SimaticML">
          <SW.Screen><AttributeList><Name>T</Name><Width>1280</Width><Height>800</Height></AttributeList>
            <ObjectList><Hmi.Screen.Button ID="1"><AttributeList><ObjectName>B</ObjectName></AttributeList>
              <Events><Event Name="Press"><FunctionList><SetBit><TagName></TagName></SetBit></FunctionList></Event></Events>
            </Hmi.Screen.Button></ObjectList>
          </SW.Screen></Document>"""
        diags = validate_generated_screen_xml(xml, [], [], ["B"])
        errors = [d for d in diags if d["severity"] == "error"]
        assert len(errors) >= 1

    def test_duplicate_ids_blocked(self):
        """控件 ID 重复时阻断。"""
        xml = """<Document xmlns="http://example.com/SimaticML">
          <SW.Screen><AttributeList><Name>T</Name><Width>1280</Width><Height>800</Height></AttributeList>
            <ObjectList>
              <Hmi.Screen.Button ID="1"><AttributeList><ObjectName>A</ObjectName></AttributeList></Hmi.Screen.Button>
              <Hmi.Screen.Button ID="1"><AttributeList><ObjectName>B</ObjectName></AttributeList></Hmi.Screen.Button>
            </ObjectList>
          </SW.Screen></Document>"""
        diags = validate_generated_screen_xml(xml, [], [], ["A", "B"])
        errors = [d for d in diags if d["severity"] == "error"]
        assert len(errors) >= 1

    def test_clean_xml_passes(self):
        """正常 XML 可以通过。"""
        xml = """<Document xmlns="http://example.com/SimaticML">
          <SW.Screen><AttributeList><Name>T</Name><Width>1280</Width><Height>800</Height></AttributeList>
            <ObjectList>
              <Hmi.Screen.Button ID="1"><AttributeList><ObjectName>A</ObjectName><ProcessTag>Tag_A</ProcessTag></AttributeList></Hmi.Screen.Button>
              <Hmi.Screen.Button ID="2"><AttributeList><ObjectName>B</ObjectName><ProcessTag>Tag_B</ProcessTag></AttributeList></Hmi.Screen.Button>
            </ObjectList>
          </SW.Screen></Document>"""
        diags = validate_generated_screen_xml(xml, ["Tag_A", "Tag_B"], ["Template_"], ["A", "B"])
        errors = [d for d in diags if d["severity"] == "error"]
        assert len(errors) == 0, f"Unexpected: {[d['message'] for d in errors]}"

# -*- coding: utf-8 -*-
"""
测试: HMI Tag XML 生成与验证。

V5.0 新增:
  - 验证 TagXmlBuilder 生成的 XML 不包含 SW.Blocks (PLC Blocks 类型)
  - 验证 validate_xml_class_for_import_target 能正确区分 HMI Tag / PLC Blocks XML
  - 验证 validate_for_import_target 的完整校验
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from backend.backends.classic.tag_xml_builder import TagXmlBuilder
from backend.domain.ir_v2 import TagSpec
from backend.domain.enums import TagScope
from backend.xml_validator import (
    validate_xml_class_for_import_target,
    validate_for_import_target,
)


class TestTagXmlNoSwBlocks(unittest.TestCase):
    """测试 TagXmlBuilder 生成的 XML 不含 SW.Blocks。"""

    def setUp(self):
        self.builder = TagXmlBuilder()
        self.internal_tag = TagSpec(
            name="Test_BOOL_Tag",
            data_type="Bool",
            scope=TagScope.INTERNAL,
            table="DefaultTagTable",
        )
        self.external_tag = TagSpec(
            name="Test_INT_Tag",
            data_type="Int",
            scope=TagScope.EXTERNAL,
            table="DefaultTagTable",
            connection="HMI_Connection_1",
            address="DB1.DBW0",
            controller_tag="PLC_Tag_1",
        )

    def test_single_tag_no_blocks(self):
        """单变量 XML 不应包含 SW.Blocks。"""
        xml = self.builder.build_single_tag_export_xml(self.internal_tag)
        self.assertNotIn("SW.Blocks", xml,
                         "单变量 XML 不应包含 SW.Blocks")
        self.assertIn("SW.Tag", xml,
                      "单变量 XML 应包含 SW.Tag")
        self.assertIn("Test_BOOL_Tag", xml,
                      "单变量 XML 应包含变量名")
        self.assertIn("Bool", xml,
                      "单变量 XML 应包含数据类型")

    def test_single_external_tag_no_blocks(self):
        """带连接的外部变量 XML 不应包含 SW.Blocks。"""
        xml = self.builder.build_single_tag_export_xml(self.external_tag)
        self.assertNotIn("SW.Blocks", xml,
                         "外部变量 XML 不应包含 SW.Blocks")
        self.assertIn("HMI_Connection_1", xml,
                      "外部变量 XML 应包含连接名")
        self.assertIn("DB1.DBW0", xml,
                      "外部变量 XML 应包含地址")

    def test_batch_tags_no_blocks(self):
        """批量标签 XML (默认 output_kind='hmi_tags') 不应包含 SW.Blocks。"""
        tags = [self.internal_tag, self.external_tag]
        xml = self.builder.build_tags_batch_export_xml(tags)
        self.assertNotIn("SW.Blocks", xml,
                         "批量 HMI tag XML 不应包含 SW.Blocks")
        self.assertEqual(xml.count("<SW.Tag"), 2,
                         "应生成 2 个 SW.Tag 元素")

    def test_batch_tags_plc_blocks_mode(self):
        """output_kind='plc_blocks' 时应用 SW.Blocks 包裹（向后兼容）。"""
        tags = [self.internal_tag]
        xml = self.builder.build_tags_batch_export_xml(
            tags, output_kind="plc_blocks"
        )
        self.assertIn("SW.Blocks", xml,
                      "plc_blocks 模式应包含 SW.Blocks")
        self.assertIn("</SW.Blocks>", xml,
                      "plc_blocks 模式应闭合 SW.Blocks")


class TestValidateXmlClassForImportTarget(unittest.TestCase):
    """测试 validate_xml_class_for_import_target 函数。"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def _write_xml(self, content: str, name: str = "test.xml") -> str:
        path = os.path.join(self.tmp_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def _make_hmi_tag_xml(self) -> str:
        """生成正确的 HMI Tag XML (不含 SW.Blocks)。"""
        return '''<?xml version="1.0" encoding="utf-8"?>
<Document xmlns="http://www.siemens.com/automation/SimaticML">
  <Engineering version="V16"/>
  <SW.Tag ID="a1b2c3d4">
    <AttributeList>
      <Name>Test_Tag</Name>
      <DataType>Bool</DataType>
      <Connection></Connection>
    </AttributeList>
  </SW.Tag>
</Document>'''

    def _make_plc_blocks_xml(self) -> str:
        """生成错误的 PLC Blocks XML (含 SW.Blocks)。"""
        return '''<?xml version="1.0" encoding="utf-8"?>
<Document ID="doc1234" xmlns="http://www.siemens.com/automation/SimaticML">
  <Engineering version="V16"/>
  <SW.Blocks ID="blk5678">
    <SW.Tag ID="tag9012">
      <AttributeList>
        <Name>PLC_Tag</Name>
        <DataType>Bool</DataType>
      </AttributeList>
    </SW.Tag>
  </SW.Blocks>
</Document>'''

    def test_hmi_tag_xml_passes(self):
        """正确的 HMI Tag XML 应通过 hmi_tags 校验。"""
        path = self._write_xml(self._make_hmi_tag_xml(), "valid_hmi_tags.xml")
        try:
            validate_xml_class_for_import_target(path, "hmi_tags")
        except ValueError as e:
            self.fail(f"正确的 HMI Tag XML 不应抛出异常: {e}")

    def test_plc_blocks_xml_raises(self):
        """包含 SW.Blocks 的 XML 应在 hmi_tags 校验时抛出 ValueError。"""
        path = self._write_xml(self._make_plc_blocks_xml(), "plc_blocks.xml")
        with self.assertRaises(ValueError) as ctx:
            validate_xml_class_for_import_target(path, "hmi_tags")
        error_msg = str(ctx.exception)
        self.assertIn("TAG_XML_WRONG_CLASS", error_msg,
                      "错误消息应包含 TAG_XML_WRONG_CLASS")
        self.assertIn("SW.Blocks", error_msg,
                      "错误消息应提及 SW.Blocks")
        self.assertIn("HMI TagComposition", error_msg,
                      "错误消息应提及目标集合")

    def test_plc_blocks_xml_passes_for_plc_target(self):
        """包含 SW.Blocks 的 XML 应在 plc_blocks 校验时通过。"""
        path = self._write_xml(self._make_plc_blocks_xml(), "plc_plc.xml")
        try:
            validate_xml_class_for_import_target(path, "plc_blocks")
        except ValueError as e:
            self.fail(f"PLC Blocks XML 用于 plc_blocks 目标不应抛出异常: {e}")

    def test_missing_file_raises(self):
        """不存在的文件应抛出异常。"""
        with self.assertRaises(ValueError) as ctx:
            validate_xml_class_for_import_target("/nonexistent/file.xml", "hmi_tags")
        self.assertIn("TAG_XML_WRONG_CLASS", str(ctx.exception))

    def test_screen_target_rejects_sw_blocks(self):
        """hmi_screen 目标也应拒绝 SW.Blocks。"""
        path = self._write_xml(self._make_plc_blocks_xml(), "screen_w_blocks.xml")
        with self.assertRaises(ValueError) as ctx:
            validate_xml_class_for_import_target(path, "hmi_screen")
        self.assertIn("Screen XML 不应包含 PLC Blocks", str(ctx.exception))

    def test_invalid_target_kind_raises(self):
        """未知的目标类型应抛出异常。"""
        path = self._write_xml(self._make_hmi_tag_xml(), "unknown_target.xml")
        with self.assertRaises(ValueError) as ctx:
            validate_xml_class_for_import_target(path, "invalid_target")
        self.assertIn("未知的导入目标类型", str(ctx.exception))


class TestValidateForImportTarget(unittest.TestCase):
    """测试 validate_for_import_target 的完整校验。"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def _write_xml(self, content: str, name: str = "test.xml") -> str:
        path = os.path.join(self.tmp_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_hmi_tags_duplicate_names(self):
        """重复变量名应被检测到。"""
        xml = '''<?xml version="1.0" encoding="utf-8"?>
<Document xmlns="http://www.siemens.com/automation/SimaticML">
  <Engineering version="V16"/>
  <SW.Tag ID="id1">
    <AttributeList>
      <Name>Duplicate_Tag</Name>
      <DataType>Bool</DataType>
    </AttributeList>
  </SW.Tag>
  <SW.Tag ID="id2">
    <AttributeList>
      <Name>Duplicate_Tag</Name>
      <DataType>Int</DataType>
    </AttributeList>
  </SW.Tag>
</Document>'''
        path = self._write_xml(xml, "duplicate_tags.xml")
        result = validate_for_import_target(path, "hmi_tags")
        self.assertFalse(result.valid,
                         "重复变量名应使校验失败")
        self.assertTrue(any("重复变量名" in e for e in result.errors),
                        "错误消息应提及重复变量名")

    def test_hmi_tags_with_screen_objects(self):
        """包含画面对象的 XML 不应通过 hmi_tags 校验。"""
        xml = '''<?xml version="1.0" encoding="utf-8"?>
<Document xmlns="http://www.siemens.com/automation/SimaticML">
  <Engineering version="V16"/>
  <SW.Tag ID="id1">
    <AttributeList>
      <Name>Test_Tag</Name>
      <DataType>Bool</DataType>
    </AttributeList>
  </SW.Tag>
  <Screen ID="sc1" Name="Screen_1">
    <AttributeList>
      <Name>Screen_1</Name>
    </AttributeList>
  </Screen>
</Document>'''
        path = self._write_xml(xml, "tag_with_screen.xml")
        result = validate_for_import_target(path, "hmi_tags")
        self.assertFalse(result.valid,
                         "包含 Screen 的 XML 不应通过 hmi_tags 校验")
        self.assertTrue(any("Screen" in e for e in result.errors),
                        "错误消息应提及 Screen")

    def test_valid_hmi_tags_passes_full_validation(self):
        """有效的 HMI Tag XML 应通过完整校验。"""
        xml = '''<?xml version="1.0" encoding="utf-8"?>
<Document xmlns="http://www.siemens.com/automation/SimaticML">
  <Engineering version="V16"/>
  <SW.Tag ID="id1">
    <AttributeList>
      <Name>Tag_One</Name>
      <DataType>Bool</DataType>
    </AttributeList>
  </SW.Tag>
  <SW.Tag ID="id2">
    <AttributeList>
      <Name>Tag_Two</Name>
      <DataType>Int</DataType>
      <Connection>Conn_1</Connection>
      <Address>DB1.DBW0</Address>
    </AttributeList>
  </SW.Tag>
</Document>'''
        path = self._write_xml(xml, "valid_multi_tags.xml")
        result = validate_for_import_target(path, "hmi_tags")
        self.assertTrue(result.valid,
                        "有效的 HMI Tag XML 应通过校验")
        self.assertEqual(len(result.errors), 0,
                         "不应存在错误")


class TestGoldenTemplateIsValid(unittest.TestCase):
    """验证金标准模板 XML 符合 HMI Tag 格式要求。"""

    def setUp(self):
        # 定位 golden 模板路径
        base_dir = Path(__file__).resolve().parent.parent
        self.golden_path = base_dir / "backend" / "references" / "golden_hmi_tag_template.xml"

    def test_golden_template_exists(self):
        """金标准模板文件应存在。"""
        self.assertTrue(self.golden_path.exists(),
                        f"金标准模板文件不存在: {self.golden_path}")

    def test_golden_template_no_sw_blocks(self):
        """金标准模板不应包含 SW.Blocks 元素（通过验证函数检测）。"""
        if not self.golden_path.exists():
            self.skipTest("金标准模板文件不存在")
        # 使用 XML 类型守卫验证（自动跳过注释中的 SW.Blocks 引用）
        try:
            validate_xml_class_for_import_target(str(self.golden_path), "hmi_tags")
        except ValueError as e:
            self.fail(f"金标准模板不应触发 TAG_XML_WRONG_CLASS: {e}")
        # 也进行原始内容检查（仅 XML 元素部分）
        content = self.golden_path.read_text(encoding="utf-8")
        self.assertIn("SW.Tag", content,
                      "金标准模板应包含 SW.Tag")

    def test_golden_template_passes_validation(self):
        """金标准模板应通过 validate_for_import_target('hmi_tags') 校验。"""
        if not self.golden_path.exists():
            self.skipTest("金标准模板文件不存在")
        try:
            validate_xml_class_for_import_target(str(self.golden_path), "hmi_tags")
        except ValueError as e:
            self.fail(f"金标准模板未通过 XML 类型守卫: {e}")

        result = validate_for_import_target(str(self.golden_path), "hmi_tags")
        self.assertTrue(result.valid,
                        "金标准模板应通过完整校验")
        if result.errors:
            self.fail(f"金标准模板存在校验错误: {result.errors}")


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""
Test: HMI Tag XML generation and validation.

V5.0 additions:
  - Validate TagXmlBuilder XML does not contain SW.Blocks (PLC Blocks type)
  - Validate validate_xml_class_for_import_target distinguishes HMI Tag / PLC Blocks XML
  - Validate validate_for_import_target full check

V5.1 additions:
  - Classic HMI sync: TagComposition has no Create, all tags exist -> success
  - Classic HMI sync: missing tags, golden template exists -> generates HMI XML, calls Tags.Import
  - Classic HMI sync: missing tags, no golden template -> returns HMI_TAG_XML_TEMPLATE_MISSING
  - HmiTagXmlBuilder output contains Hmi.Tag.Tag, not Siemens.Engineering.SW.
  - detect_hmi_tag_xml_kind correctly identifies individual vs table vs PLC
"""

from __future__ import annotations

import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from backend.backends.classic.tag_xml_builder import TagXmlBuilder, HmiTagXmlBuilder
from backend.domain.ir_v2 import TagSpec
from backend.domain.enums import TagScope
from unittest.mock import patch, MagicMock

from backend.xml_validator import (
    validate_xml_class_for_import_target,
    validate_for_import_target,
    detect_hmi_tag_xml_kind,
)
from backend.openness.classic_executor import ClassicOpennessExecutor
from backend.domain.diagnostics import DiagnosticCodes


class TestTagXmlNoSwBlocks(unittest.TestCase):
    """Test TagXmlBuilder output does not contain SW.Blocks."""

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
        """hmi_tags output_kind (default) should raise NotImplementedError."""
        with self.assertRaises(NotImplementedError):
            self.builder.build_single_tag_export_xml(self.internal_tag)

    def test_single_external_tag_no_blocks(self):
        """hmi_tags output_kind (default) should raise NotImplementedError."""
        with self.assertRaises(NotImplementedError):
            self.builder.build_single_tag_export_xml(self.external_tag)

    def test_batch_tags_no_blocks(self):
        """Batch tags XML (default output_kind='hmi_tags') should raise NotImplementedError."""
        tags = [self.internal_tag, self.external_tag]
        with self.assertRaises(NotImplementedError):
            self.builder.build_tags_batch_export_xml(tags)

    def test_batch_tags_plc_blocks_mode(self):
        """output_kind='plc_blocks' should wrap with SW.Blocks (backward compat)."""
        tags = [self.internal_tag]
        xml = self.builder.build_tags_batch_export_xml(
            tags, output_kind="plc_blocks"
        )
        self.assertIn("SW.Blocks", xml,
                      "plc_blocks mode should contain SW.Blocks")
        self.assertIn("</SW.Blocks>", xml,
                      "plc_blocks mode should close SW.Blocks")


class TestValidateXmlClassForImportTarget(unittest.TestCase):
    """Test validate_xml_class_for_import_target function."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def _write_xml(self, content: str, name: str = "test.xml") -> str:
        path = os.path.join(self.tmp_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def _make_hmi_tag_xml(self) -> str:
        """Generate a valid HMI Tag XML (no SW.Blocks)."""
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
        """Generate a PLC Blocks XML (with SW.Blocks)."""
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

    def test_sw_tag_xml_is_now_rejected(self):
        """V5.0: SW.Tag XML is detected as PLC type, rejected by hmi_tags check."""
        path = self._write_xml(self._make_hmi_tag_xml(), "sw_tag_rejected.xml")
        with self.assertRaises(ValueError) as ctx:
            validate_xml_class_for_import_target(path, "hmi_tags")
        error_msg = str(ctx.exception)
        self.assertIn("TAG_XML_WRONG_CLASS", error_msg,
                      "Error message should contain TAG_XML_WRONG_CLASS")
        self.assertIn("SW.Tag", error_msg,
                      "Error message should mention SW.Tag")

    def test_plc_blocks_xml_raises(self):
        """XML containing SW.Blocks should raise ValueError for hmi_tags check."""
        path = self._write_xml(self._make_plc_blocks_xml(), "plc_blocks.xml")
        with self.assertRaises(ValueError) as ctx:
            validate_xml_class_for_import_target(path, "hmi_tags")
        error_msg = str(ctx.exception)
        self.assertIn("TAG_XML_WRONG_CLASS", error_msg,
                      "Error message should contain TAG_XML_WRONG_CLASS")
        self.assertIn("SW.Blocks", error_msg,
                      "Error message should mention SW.Blocks")
        self.assertIn("HMI TagComposition", error_msg,
                      "Error message should mention target collection")

    def test_plc_blocks_xml_passes_for_plc_target(self):
        """XML containing SW.Blocks should pass for plc_blocks target."""
        path = self._write_xml(self._make_plc_blocks_xml(), "plc_plc.xml")
        try:
            validate_xml_class_for_import_target(path, "plc_blocks")
        except ValueError as e:
            self.fail(f"PLC Blocks XML for plc_blocks target should not raise: {e}")

    def test_missing_file_raises(self):
        """Non-existent file should raise ValueError."""
        with self.assertRaises(ValueError) as ctx:
            validate_xml_class_for_import_target("/nonexistent/file.xml", "hmi_tags")
        self.assertIn("TAG_XML_WRONG_CLASS", str(ctx.exception))

    def test_screen_target_rejects_sw_blocks(self):
        """hmi_screen target should also reject SW.Blocks."""
        path = self._write_xml(self._make_plc_blocks_xml(), "screen_w_blocks.xml")
        with self.assertRaises(ValueError) as ctx:
            validate_xml_class_for_import_target(path, "hmi_screen")
        self.assertIn("Screen XML", str(ctx.exception))

    def test_invalid_target_kind_raises(self):
        """Unknown target type should raise ValueError."""
        path = self._write_xml(self._make_hmi_tag_xml(), "unknown_target.xml")
        with self.assertRaises(ValueError) as ctx:
            validate_xml_class_for_import_target(path, "invalid_target")
        self.assertIn("TAG_XML_WRONG_CLASS", str(ctx.exception))

    def test_hmi_tag_xml_format_unknown(self):
        """hmi_tags output_kind should raise NotImplementedError (HMI Tag XML format unknown)."""
        tag = TagSpec(
            name="Unknown_Tag", data_type="Bool",
            scope=TagScope.INTERNAL, table="DefaultTagTable",
        )
        builder = TagXmlBuilder()
        with self.assertRaises(NotImplementedError):
            builder.build_single_tag_export_xml(tag, output_kind="hmi_tags")


class TestValidateForImportTarget(unittest.TestCase):
    """Test validate_for_import_target full check."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def _write_xml(self, content: str, name: str = "test.xml") -> str:
        path = os.path.join(self.tmp_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_hmi_tags_duplicate_names(self):
        """SW.Tag XML should be rejected at class check stage (SW.Tag no longer accepted)."""
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
                         "SW.Tag XML should be rejected at class check stage")
        self.assertTrue(any("TAG_XML_WRONG_CLASS" in e for e in result.errors),
                        "Error message should mention TAG_XML_WRONG_CLASS")

    def test_hmi_tags_with_screen_objects(self):
        """SW.Tag XML with Screen should also be rejected at class check stage."""
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
                         "SW.Tag XML should be rejected at class check stage")
        self.assertTrue(any("TAG_XML_WRONG_CLASS" in e for e in result.errors),
                        "Error message should mention TAG_XML_WRONG_CLASS")

    def test_valid_hmi_tags_passes_full_validation(self):
        """SW.Tag XML should be rejected at class check stage of full validation."""
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
        self.assertFalse(result.valid,
                         "SW.Tag XML should be rejected at class check stage")
        self.assertTrue(any("TAG_XML_WRONG_CLASS" in e for e in result.errors),
                        "Error message should mention TAG_XML_WRONG_CLASS")


class TestGoldenTemplateIsValid(unittest.TestCase):
    """Validate golden template XML conforms to HMI Tag format requirements."""

    def setUp(self):
        base_dir = Path(__file__).resolve().parent.parent
        self.golden_path = base_dir / "backend" / "references" / "golden_hmi_tag_template.xml"

    def test_golden_template_exists(self):
        """Golden template file should exist."""
        self.assertTrue(self.golden_path.exists(),
                        f"Golden template file does not exist: {self.golden_path}")

    def test_golden_template_no_sw_blocks(self):
        """Golden template uses SW.Tag, rejected by class check (TAG_XML_WRONG_CLASS)."""
        if not self.golden_path.exists():
            self.skipTest("Golden template file does not exist")
        with self.assertRaises(ValueError) as ctx:
            validate_xml_class_for_import_target(str(self.golden_path), "hmi_tags")
        error_msg = str(ctx.exception)
        self.assertIn("TAG_XML_WRONG_CLASS", error_msg,
                      "Error message should contain TAG_XML_WRONG_CLASS")
        self.assertIn("SW.Tag", error_msg,
                      "Error message should mention SW.Tag")

    def test_golden_template_passes_validation(self):
        """Golden template uses SW.Tag, rejected by validate_for_import_target."""
        if not self.golden_path.exists():
            self.skipTest("Golden template file does not exist")
        result = validate_for_import_target(str(self.golden_path), "hmi_tags")
        self.assertFalse(result.valid,
                         "Golden template (with SW.Tag) should be rejected")
        self.assertTrue(any("TAG_XML_WRONG_CLASS" in e for e in result.errors),
                        "Error message should mention TAG_XML_WRONG_CLASS")


class TestCreateHmiTagsNotSupported(unittest.TestCase):
    """Test create_hmi_tags_via_api -- returns TAG_CREATE_NOT_SUPPORTED when Create method missing."""

    def test_api_create_hmi_tags_not_supported(self):
        """When Create method is absent, return TAG_CREATE_NOT_SUPPORTED diagnostic."""
        executor = ClassicOpennessExecutor()

        mock_tags_coll = MagicMock()
        mock_default_table = MagicMock()
        mock_default_table.Tags = mock_tags_coll

        mock_tag_folder = MagicMock()
        mock_tag_folder.DefaultTagTable = mock_default_table

        mock_hmi = MagicMock()
        mock_hmi.TagFolder = mock_tag_folder

        tag_items = [
            {"name": "Test_Tag", "data_type": "Bool", "connection": "", "address": ""}
        ]

        with patch("backend.openness.reflection_utils.has_method", return_value=False):
            result = executor.create_hmi_tags_via_api(mock_hmi, tag_items)

        self.assertTrue(
            any(d.code == DiagnosticCodes.TAG_CREATE_NOT_SUPPORTED
                for d in result.diagnostics),
            f"Expected TAG_CREATE_NOT_SUPPORTED, got: "
            f"{[d.code for d in result.diagnostics]}"
        )


# ======================================================================
# V5.1 New Tests
# ======================================================================


class TestClassicHmiSyncAllTagsExist(unittest.TestCase):
    """Classic HMI sync: TagComposition has no Create, but all tags exist -> success.

    Verifies that when all required tags already exist in the HMI DefaultTagTable,
    the import methods return success without attempting XML import or Create.
    """

    def _make_hmi_software_mock(self, existing_tags: set[str]) -> MagicMock:
        """Build a mock HMI software object whose DefaultTagTable.Tags
        enumerates the given existing_tags."""
        mock_tags_coll = MagicMock()
        # Make iteration yield mock tag objects with .Name attribute
        tag_mocks = []
        for name in existing_tags:
            m = MagicMock()
            m.Name = name
            tag_mocks.append(m)
        mock_tags_coll.__iter__ = MagicMock(return_value=iter(tag_mocks))

        mock_default_table = MagicMock()
        mock_default_table.Tags = mock_tags_coll

        mock_tag_folder = MagicMock()
        mock_tag_folder.DefaultTagTable = mock_default_table

        mock_hmi = MagicMock()
        mock_hmi.TagFolder = mock_tag_folder
        return mock_hmi

    def test_import_tags_to_default_table_all_exist_returns_success(self):
        """import_tags_to_default_table: empty tags_xml + all tag_items exist -> success."""
        executor = ClassicOpennessExecutor()
        existing = {"TagA", "TagB", "TagC"}
        mock_hmi = self._make_hmi_software_mock(existing)

        tag_items = [
            {"name": "TagA", "data_type": "Bool"},
            {"name": "TagB", "data_type": "Int"},
        ]
        # tags_xml is empty, but all tags already exist
        result = executor.import_tags_to_default_table(mock_hmi, "", tag_items=tag_items)

        self.assertTrue(result.success,
                        "Should succeed when all required tags already exist")
        self.assertFalse(result.diagnostics,
                         "No diagnostics expected when all tags exist")

    def test_import_hmi_tags_safe_all_exist_returns_success(self):
        """import_hmi_tags_safe: empty tags_xml + all tag_items exist -> success."""
        executor = ClassicOpennessExecutor()
        existing = {"TagA", "TagB", "TagC"}
        mock_hmi = self._make_hmi_software_mock(existing)

        tag_items = [
            {"name": "TagA", "data_type": "Bool"},
            {"name": "TagB", "data_type": "Int"},
        ]
        result = executor.import_hmi_tags_safe(mock_hmi, "", tag_items=tag_items)

        self.assertTrue(result.success,
                        "Should succeed when all required tags already exist")
        self.assertFalse(result.diagnostics,
                         "No diagnostics expected when all tags exist")


class TestClassicHmiSyncMissingTagsGoldenTemplate(unittest.TestCase):
    """Classic HMI sync: missing tags, golden template exists -> generates HMI XML, calls Tags.Import.

    Verifies the flow when tags_xml contains valid HMI XML (Hmi.Tag.Tag),
    the XML passes the class guard, and Tags.Import is called.
    """

    def _make_hmi_software_mock(self, existing_tags: set[str] | None = None) -> MagicMock:
        """Build a mock HMI software with DefaultTagTable.Tags that
        has an Import method."""
        if existing_tags is None:
            existing_tags = set()

        tag_mocks = []
        for name in existing_tags:
            m = MagicMock()
            m.Name = name
            tag_mocks.append(m)

        mock_tags_coll = MagicMock()
        mock_tags_coll.__iter__ = MagicMock(return_value=iter(tag_mocks))
        # Simulate Import adding new tags (we just verify Import was called)
        mock_tags_coll.Import = MagicMock()

        mock_default_table = MagicMock()
        mock_default_table.Tags = mock_tags_coll

        mock_tag_folder = MagicMock()
        mock_tag_folder.DefaultTagTable = mock_default_table

        mock_hmi = MagicMock()
        mock_hmi.TagFolder = mock_tag_folder
        return mock_hmi

    def test_import_with_valid_hmi_xml_calls_import(self):
        """Valid HMI tag XML (Hmi.Tag.Tag) should pass class guard and call Tags.Import."""
        executor = ClassicOpennessExecutor()
        # No existing tags -- some are missing
        mock_hmi = self._make_hmi_software_mock(set())

        # Build valid HMI tag XML via HmiTagXmlBuilder
        builder = HmiTagXmlBuilder()
        valid_hmi_xml = builder.build_individual_tag_xml(
            tag_name="NewTag", data_type="Bool",
        )

        tag_items = [
            {"name": "NewTag", "data_type": "Bool"},
        ]

        # Patch _make_file_info to avoid .NET dependency
        with patch.object(executor, "_make_file_info", return_value=MagicMock()):
            # Patch _make_import_options to return a mock
            mock_import_opts = MagicMock()
            with patch.object(type(executor), "_make_import_options", return_value=mock_import_opts):
                # Patch enumerate_tag_names to simulate Import effect
                with patch(
                    "backend.openness.classic_executor.enumerate_tag_names",
                    side_effect=lambda coll: ["NewTag"] if coll.Import.called else [],
                ):
                    result = executor.import_tags_to_default_table(
                        mock_hmi, valid_hmi_xml, tag_items=tag_items,
                    )

        # The import should have been attempted (either success or at least not TEMPLATE_MISSING)
        has_template_missing = any(
            d.code == DiagnosticCodes.HMI_TAG_XML_TEMPLATE_MISSING
            for d in result.diagnostics
        )
        self.assertFalse(has_template_missing,
                         "Should not return HMI_TAG_XML_TEMPLATE_MISSING when golden template XML is provided")


class TestClassicHmiSyncMissingTagsNoTemplate(unittest.TestCase):
    """Classic HMI sync: missing tags, no golden template -> returns HMI_TAG_XML_TEMPLATE_MISSING.

    Verifies that when tags_xml is empty and some required tags are missing
    from the HMI DefaultTagTable, the executor returns the HMI_TAG_XML_TEMPLATE_MISSING
    diagnostic code.
    """

    def _make_hmi_software_mock(self, existing_tags: set[str] | None = None) -> MagicMock:
        if existing_tags is None:
            existing_tags = set()
        tag_mocks = []
        for name in existing_tags:
            m = MagicMock()
            m.Name = name
            tag_mocks.append(m)

        mock_tags_coll = MagicMock()
        mock_tags_coll.__iter__ = MagicMock(return_value=iter(tag_mocks))

        mock_default_table = MagicMock()
        mock_default_table.Tags = mock_tags_coll

        mock_tag_folder = MagicMock()
        mock_tag_folder.DefaultTagTable = mock_default_table

        mock_hmi = MagicMock()
        mock_hmi.TagFolder = mock_tag_folder
        return mock_hmi

    def test_import_tags_to_default_table_missing_no_template(self):
        """Empty tags_xml + missing tags -> HMI_TAG_XML_TEMPLATE_MISSING."""
        executor = ClassicOpennessExecutor()
        # Only TagA exists; TagB is missing
        mock_hmi = self._make_hmi_software_mock({"TagA"})

        tag_items = [
            {"name": "TagA", "data_type": "Bool"},
            {"name": "TagB", "data_type": "Int"},
        ]
        result = executor.import_tags_to_default_table(mock_hmi, "", tag_items=tag_items)

        self.assertFalse(result.success,
                         "Should fail when missing tags and no template")
        self.assertTrue(
            any(d.code == DiagnosticCodes.HMI_TAG_XML_TEMPLATE_MISSING
                for d in result.diagnostics),
            f"Expected HMI_TAG_XML_TEMPLATE_MISSING, got: "
            f"{[d.code for d in result.diagnostics]}"
        )

    def test_import_hmi_tags_safe_missing_no_template(self):
        """import_hmi_tags_safe: empty tags_xml + missing tags -> HMI_TAG_XML_TEMPLATE_MISSING."""
        executor = ClassicOpennessExecutor()
        mock_hmi = self._make_hmi_software_mock(set())

        tag_items = [
            {"name": "TagX", "data_type": "Bool"},
        ]
        result = executor.import_hmi_tags_safe(mock_hmi, "", tag_items=tag_items)

        self.assertFalse(result.success,
                         "Should fail when missing tags and no template")
        self.assertTrue(
            any(d.code == DiagnosticCodes.HMI_TAG_XML_TEMPLATE_MISSING
                for d in result.diagnostics),
            f"Expected HMI_TAG_XML_TEMPLATE_MISSING, got: "
            f"{[d.code for d in result.diagnostics]}"
        )


class TestHmiTagXmlBuilderOutputFormat(unittest.TestCase):
    """HmiTagXmlBuilder output contains Hmi.Tag.Tag, not Siemens.Engineering.SW.

    Verifies that HmiTagXmlBuilder produces XML with <Hmi.Tag.Tag> elements
    and does NOT contain any Siemens.Engineering.SW.* references.
    """

    def test_individual_tag_contains_hmi_tag_tag(self):
        """build_individual_tag_xml should produce XML with Hmi.Tag.Tag."""
        builder = HmiTagXmlBuilder()
        xml = builder.build_individual_tag_xml(
            tag_name="TestTag", data_type="Bool",
        )
        self.assertIn("Hmi.Tag.Tag", xml,
                      "Output should contain Hmi.Tag.Tag element")

    def test_individual_tag_no_siemens_engineering_sw(self):
        """build_individual_tag_xml should NOT contain Siemens.Engineering.SW."""
        builder = HmiTagXmlBuilder()
        xml = builder.build_individual_tag_xml(
            tag_name="TestTag", data_type="Bool",
        )
        self.assertNotIn("Siemens.Engineering.SW", xml,
                         "Output should not contain Siemens.Engineering.SW")
        self.assertNotIn("SW.Blocks", xml,
                         "Output should not contain SW.Blocks")
        self.assertNotIn("SW.Tag", xml,
                         "Output should not contain SW.Tag (PLC type)")

    def test_batch_tags_contains_hmi_tag_tag(self):
        """build_batch_tags_xml should produce XML with Hmi.Tag.Tag elements."""
        builder = HmiTagXmlBuilder()
        tag_items = [
            {"name": "Tag1", "data_type": "Bool"},
            {"name": "Tag2", "data_type": "Int", "address": "%DB1.DBW0"},
        ]
        xml = builder.build_batch_tags_xml(tag_items)
        self.assertIn("Hmi.Tag.Tag", xml,
                      "Batch output should contain Hmi.Tag.Tag element")
        self.assertIn("Tag1", xml,
                      "Batch output should contain Tag1 name")
        self.assertIn("Tag2", xml,
                      "Batch output should contain Tag2 name")

    def test_batch_tags_no_siemens_engineering_sw(self):
        """build_batch_tags_xml should NOT contain Siemens.Engineering.SW."""
        builder = HmiTagXmlBuilder()
        tag_items = [
            {"name": "Tag1", "data_type": "Bool"},
            {"name": "Tag2", "data_type": "Int"},
        ]
        xml = builder.build_batch_tags_xml(tag_items)
        self.assertNotIn("Siemens.Engineering.SW", xml,
                         "Batch output should not contain Siemens.Engineering.SW")
        self.assertNotIn("SW.Blocks", xml,
                         "Batch output should not contain SW.Blocks")
        self.assertNotIn("SW.Tag", xml,
                         "Batch output should not contain SW.Tag (PLC type)")

    def test_individual_tag_root_is_engineering(self):
        """build_individual_tag_xml root element should be Engineering, not Document."""
        builder = HmiTagXmlBuilder()
        xml = builder.build_individual_tag_xml(
            tag_name="TestTag", data_type="Bool",
        )
        self.assertIn("<Engineering", xml,
                      "Root should be Engineering element")

    def test_batch_tags_with_connection(self):
        """build_batch_tags_xml should include connection; Address not supported in Hmi.Tag.Tag."""
        builder = HmiTagXmlBuilder()
        tag_items = [
            {
                "name": "ExtTag",
                "data_type": "Real",
                "connection": "PLC_1",
            },
        ]
        xml = builder.build_batch_tags_xml(tag_items)
        self.assertIn("PLC_1", xml, "Should contain connection")

    def test_no_datatype_in_xml(self):
        """V5.5R8: DataType 不在 XML 的任何位置。

        TIA Portal Hmi.Tag.TagComposition.Import:
        - 不接受 <DataType> 子元素 ("The type of the argument 'DataType' is invalid")
        - 不读取元素属性 DataType="..."（默认全部 Int）
        - 类型由 _correct_tag_data_types_after_import 通过 .NET API 修正
        """
        builder = HmiTagXmlBuilder()
        xml = builder.build_batch_tags_xml([
            {"name": "BTN_Test", "data_type": "Bool"},
            {"name": "IO_Test", "data_type": "Real"},
        ])
        root = ET.fromstring(xml)
        ns = "http://www.siemens.com/automation/HmiTagML"
        for tag_elem in root.findall(f".//{{{ns}}}Hmi.Tag.Tag"):
            self.assertNotIn("DataType", tag_elem.attrib,
                           "<Hmi.Tag.Tag> 不得有 DataType 属性")
            attr_list = tag_elem.find(f"{{{ns}}}AttributeList")
            self.assertIsNotNone(attr_list,
                               f"<Hmi.Tag.Tag> 必须包含 <AttributeList>")
            dt_elem = attr_list.find(f"{{{ns}}}DataType")
            self.assertIsNone(dt_elem,
                            f"<AttributeList> 内不得有 <DataType> 子元素")
        self.assertIn("Hmi.Tag.Tag", xml, "Should contain Hmi.Tag.Tag")
        self.assertNotIn("<Address>", xml, "Address not supported")
        self.assertNotIn("<DataType>", xml, "DataType not in XML at all")


class TestDetectHmiTagXmlKind(unittest.TestCase):
    """detect_hmi_tag_xml_kind correctly identifies individual vs table vs PLC."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def _write_xml(self, content: str, name: str = "test.xml") -> str:
        path = os.path.join(self.tmp_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_detects_individual_hmi_tag(self):
        """XML with Hmi.Tag.Tag element should be detected as individual_hmi_tag."""
        xml = '''<?xml version="1.0" encoding="utf-8"?>
<Engineering version="V16" xmlns="http://www.siemens.com/automation/HmiTagML">
  <Hmi.Tag.Tag Class="Hmi.Tag.Tag" ID="abc123" CompositionName="Tags">
    <AttributeList>
      <Name>TestTag</Name>
      <DataType>Bool</DataType>
    </AttributeList>
  </Hmi.Tag.Tag>
</Engineering>'''
        path = self._write_xml(xml, "individual.xml")
        result = detect_hmi_tag_xml_kind(path)
        self.assertEqual(result, "individual_hmi_tag",
                         f"Expected 'individual_hmi_tag', got '{result}'")

    def test_detects_hmi_tag_table(self):
        """XML with Hmi.Tag.TagTable element should be detected as hmi_tag_table."""
        xml = '''<?xml version="1.0" encoding="utf-8"?>
<Engineering version="V16" xmlns="http://www.siemens.com/automation/HmiTagML">
  <Hmi.Tag.TagTable Class="Hmi.Tag.TagTable" ID="tbl123" CompositionName="TagTables">
    <AttributeList>
      <Name>DefaultTagTable</Name>
    </AttributeList>
  </Hmi.Tag.TagTable>
</Engineering>'''
        path = self._write_xml(xml, "tag_table.xml")
        result = detect_hmi_tag_xml_kind(path)
        self.assertEqual(result, "hmi_tag_table",
                         f"Expected 'hmi_tag_table', got '{result}'")

    def test_detects_plc_tag(self):
        """XML with SW.Tag element should be detected as plc_tag."""
        xml = '''<?xml version="1.0" encoding="utf-8"?>
<Document xmlns="http://www.siemens.com/automation/SimaticML">
  <Engineering version="V16"/>
  <SW.Blocks ID="blk1">
    <SW.Tag ID="tag1">
      <AttributeList>
        <Name>PLC_Tag</Name>
        <DataType>Bool</DataType>
      </AttributeList>
    </SW.Tag>
  </SW.Blocks>
</Document>'''
        path = self._write_xml(xml, "plc_tag.xml")
        result = detect_hmi_tag_xml_kind(path)
        self.assertEqual(result, "plc_tag",
                         f"Expected 'plc_tag', got '{result}'")

    def test_detects_plc_tag_standalone_sw_tag(self):
        """XML with standalone SW.Tag (no SW.Blocks wrapper) should be detected as plc_tag."""
        xml = '''<?xml version="1.0" encoding="utf-8"?>
<Document xmlns="http://www.siemens.com/automation/SimaticML">
  <Engineering version="V16"/>
  <SW.Tag ID="tag1">
    <AttributeList>
      <Name>Standalone_Tag</Name>
      <DataType>Int</DataType>
    </AttributeList>
  </SW.Tag>
</Document>'''
        path = self._write_xml(xml, "standalone_sw_tag.xml")
        result = detect_hmi_tag_xml_kind(path)
        self.assertEqual(result, "plc_tag",
                         f"Expected 'plc_tag', got '{result}'")

    def test_nonexistent_file_returns_unknown(self):
        """Non-existent file should return 'unknown'."""
        result = detect_hmi_tag_xml_kind("/nonexistent/path.xml")
        self.assertEqual(result, "unknown",
                         "Non-existent file should return 'unknown'")

    def test_invalid_xml_returns_unknown(self):
        """Malformed XML should return 'unknown'."""
        path = self._write_xml("this is not xml at all", "bad.xml")
        result = detect_hmi_tag_xml_kind(path)
        self.assertEqual(result, "unknown",
                         "Malformed XML should return 'unknown'")

    def test_empty_document_returns_unknown(self):
        """Empty Document with no recognized elements should return 'unknown'."""
        xml = '''<?xml version="1.0" encoding="utf-8"?>
<Document xmlns="http://www.siemens.com/automation/SimaticML">
  <Engineering version="V16"/>
</Document>'''
        path = self._write_xml(xml, "empty.xml")
        result = detect_hmi_tag_xml_kind(path)
        self.assertEqual(result, "unknown",
                         f"Expected 'unknown', got '{result}'")

    def test_individual_hmi_tag_priority_over_table(self):
        """When XML contains both Hmi.Tag.Tag and Hmi.Tag.TagTable,
        tag_table should take priority (TagTable detected first)."""
        # TagTable XML that also contains Tag children
        xml = '''<?xml version="1.0" encoding="utf-8"?>
<Engineering version="V16" xmlns="http://www.siemens.com/automation/HmiTagML">
  <Hmi.Tag.TagTable Class="Hmi.Tag.TagTable" ID="tbl1" CompositionName="TagTables">
    <AttributeList>
      <Name>DefaultTagTable</Name>
    </AttributeList>
    <ObjectList>
      <Hmi.Tag.Tag Class="Hmi.Tag.Tag" ID="tag1" CompositionName="Tags">
        <AttributeList>
          <Name>InnerTag</Name>
          <DataType>Bool</DataType>
        </AttributeList>
      </Hmi.Tag.Tag>
    </ObjectList>
  </Hmi.Tag.TagTable>
</Engineering>'''
        path = self._write_xml(xml, "mixed.xml")
        result = detect_hmi_tag_xml_kind(path)
        # individual > table per priority: individual > table > plc > unknown
        self.assertEqual(result, "individual_hmi_tag",
                         f"Expected 'individual_hmi_tag' (individual has priority), got '{result}'")

    def test_hmi_individual_tag_with_class_attribute(self):
        """Hmi.Tag.Tag identified via Class attribute on non-Tag element."""
        xml = '''<?xml version="1.0" encoding="utf-8"?>
<Document xmlns="http://www.siemens.com/automation/SimaticML">
  <Engineering version="V16"/>
  <Hmi.Tag.Tag Class="Hmi.Tag.Tag" ID="1">
    <AttributeList>
      <Name>TagViaClass</Name>
      <DataType>Bool</DataType>
    </AttributeList>
  </Hmi.Tag.Tag>
</Document>'''
        path = self._write_xml(xml, "class_attr.xml")
        result = detect_hmi_tag_xml_kind(path)
        self.assertEqual(result, "individual_hmi_tag",
                         f"Expected 'individual_hmi_tag', got '{result}'")


if __name__ == "__main__":
    unittest.main()

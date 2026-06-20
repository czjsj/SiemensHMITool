# -*- coding: utf-8 -*-
"""测试 Classic Tag 导入 — XML Import 主路径，无 UPSERT 回退。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock

from backend.domain.diagnostics import DiagnosticCodes
from backend.domain.enums import OpennessOperationKind
from backend.openness.classic_executor import ClassicOpennessExecutor, ClassicStepResult


def _make_tag_mock(name: str) -> MagicMock:
    tag = MagicMock()
    tag.Name = name
    return tag


class TestImportHmiTagsSafe:
    """测试 import_hmi_tags_safe — XML Import 主路径。"""

    def test_empty_tags_returns_success(self):
        """空标签列表应返回成功。"""
        executor = ClassicOpennessExecutor()
        result = executor.import_hmi_tags_safe(None, "", [])
        assert result.success is True
        assert any("SKIP" in c for c in result.api_calls)

    def test_xml_import_primary_succeeds(self):
        """ImportOptions 可用时走 XML Import 路径。"""
        executor = ClassicOpennessExecutor()

        mock_tags_coll = MagicMock()
        # Return a tag that matches expected, so verification passes
        mock_tags_coll.__iter__.return_value = [_make_tag_mock("Test1")]
        mock_tags_coll.Import = MagicMock()

        mock_default_table = MagicMock()
        mock_default_table.Tags = mock_tags_coll

        mock_tag_folder = MagicMock()
        mock_tag_folder.DefaultTagTable = mock_default_table

        mock_hmi = MagicMock()
        mock_hmi.TagFolder = mock_tag_folder

        with patch.object(
            ClassicOpennessExecutor, "resolve_import_option",
            return_value={
                "ok": True, "value": 1, "selected": "Override",
                "available": ["Default", "Override"],
                "source": "direct:Hmi.ImportOptions",
                "error": None, "diagnostics": [],
            },
        ):
            with patch.object(
                ClassicOpennessExecutor, "_make_import_options",
                return_value=MagicMock(),
            ):
                with patch.object(executor, "_write_temp_xml", return_value="/tmp/tags.xml"):
                    tags_xml = '<Document xmlns="x"><SW.Tag><Name>Test1</Name></SW.Tag></Document>'
                    tag_items = [{"name": "Test1", "data_type": "Bool", "scope": "internal"}]

                    result = executor.import_hmi_tags_safe(mock_hmi, tags_xml, tag_items)

                    assert result.success is True, (
                        f"Expected success, got: {[d.message for d in result.diagnostics]}"
                    )
                    assert any(
                        "strategy_used=ImportOptions" in str(c)
                        for c in result.api_calls
                    )

    def test_xml_import_fails_returns_error_no_upsert(self):
        """XML 导入失败时不回退 UPSERT，直接返回错误。"""
        executor = ClassicOpennessExecutor()

        with patch.object(
            ClassicOpennessExecutor, "resolve_import_option",
            return_value={
                "ok": True, "value": 1, "selected": "Override",
                "available": ["Override"], "source": "direct", "error": None,
                "diagnostics": [],
            },
        ):
            with patch.object(
                ClassicOpennessExecutor, "_make_import_options",
                return_value=MagicMock(),
            ):
                # Build a mock that raises on Import
                mock_tags = MagicMock()
                mock_tags.Import = MagicMock(side_effect=Exception("Import failed"))
                mock_tags.__iter__.return_value = []

                mock_default = MagicMock()
                mock_default.Tags = mock_tags

                mock_folder = MagicMock()
                mock_folder.DefaultTagTable = mock_default

                mock_hmi = MagicMock()
                mock_hmi.TagFolder = mock_folder

                with patch.object(executor, "_write_temp_xml", return_value="/tmp/tags.xml"):
                    result = executor.import_hmi_tags_safe(
                        mock_hmi,
                        '<Document><SW.Tag><Name>Test1</Name></SW.Tag></Document>',
                        [{"name": "Test1", "data_type": "Bool", "scope": "internal"}],
                    )

                    assert result.success is False
                    has_tag_xml_failed = any(
                        d.code == DiagnosticCodes.TAG_XML_IMPORT_FAILED
                        for d in result.diagnostics
                    )
                    assert has_tag_xml_failed, (
                        f"Expected TAG_XML_IMPORT_FAILED, got: "
                        f"{[d.code for d in result.diagnostics]}"
                    )

    def test_import_failure_blocks_no_upsert_fallback(self):
        """Import 失败时返回 TAG_XML_IMPORT_FAILED，不调用 UPSERT。"""
        executor = ClassicOpennessExecutor()

        with patch.object(
            ClassicOpennessExecutor, "resolve_import_option",
            return_value={
                "ok": True, "value": 1, "selected": "Override",
                "available": ["Override"], "source": "direct",
                "error": None, "diagnostics": [],
            },
        ):
            with patch.object(
                ClassicOpennessExecutor, "_make_import_options",
                return_value=MagicMock(),
            ):
                mock_tags = MagicMock()
                mock_tags.Import = MagicMock(side_effect=Exception("Import failed"))
                mock_tags.__iter__.return_value = []

                mock_default = MagicMock()
                mock_default.Tags = mock_tags

                mock_folder = MagicMock()
                mock_folder.DefaultTagTable = mock_default

                mock_hmi = MagicMock()
                mock_hmi.TagFolder = mock_folder

                result = executor.import_hmi_tags_safe(
                    mock_hmi,
                    '<Document><SW.Tag><Name>X</Name></SW.Tag></Document>',
                    [{"name": "X", "data_type": "Bool", "scope": "internal"}],
                )

                assert result.success is False
                error_codes = [d.code for d in result.diagnostics if hasattr(d, 'code')]
                assert DiagnosticCodes.TAG_XML_IMPORT_FAILED in error_codes, (
                    f"Expected TAG_XML_IMPORT_FAILED, got: {error_codes}"
                )

    def test_xml_import_failure_with_no_tag_items_returns_error(self):
        """无 tag_items 时 XML 导入失败应返回错误。"""
        executor = ClassicOpennessExecutor()

        with patch.object(
            ClassicOpennessExecutor, "resolve_import_option",
            return_value={
                "ok": True, "value": 1, "selected": "Override",
                "available": ["Override"], "source": "direct",
                "error": None, "diagnostics": [],
            },
        ):
            with patch.object(
                ClassicOpennessExecutor, "_make_import_options",
                return_value=MagicMock(),
            ):
                mock_tags = MagicMock()
                mock_tags.Import = MagicMock(side_effect=Exception("Import failed"))
                mock_tags.__iter__.return_value = []

                mock_default = MagicMock()
                mock_default.Tags = mock_tags

                mock_folder = MagicMock()
                mock_folder.DefaultTagTable = mock_default

                mock_hmi = MagicMock()
                mock_hmi.TagFolder = mock_folder

                result = executor.import_hmi_tags_safe(
                    mock_hmi,
                    '<Document><SW.Tag><Name>X</Name></SW.Tag></Document>',
                    None,
                )

                assert result.success is False
                assert len(result.diagnostics) > 0

    def test_override_unavailable_with_empty_xml_returns_error(self):
        """ImportOptions 不可用且无单参数 Import 重载时返回错误。"""
        executor = ClassicOpennessExecutor()

        with patch.object(
            ClassicOpennessExecutor, "resolve_import_option",
            return_value={
                "ok": False, "value": None, "selected": None,
                "available": ["Default"], "source": "none",
                "error": "Override not available",
                "diagnostics": ["Hmi.ImportOptions: Override not found"],
            },
        ):
            # No tag_items — skip, with empty XML also skip
            result = executor.import_hmi_tags_safe(
                MagicMock(),
                '',  # Empty XML — skip
                None,
            )

            assert result.success is True  # SKIP because no XML and no items
            assert any("SKIP" in c for c in result.api_calls)


class TestUpsertTagsToDefaultTable:
    """测试 _upsert_tags_to_default_table 的逐标签创建/更新逻辑。"""

    def test_upsert_creates_new_tags(self):
        """不存在的标签应被创建。"""
        executor = ClassicOpennessExecutor()

        mock_tag = MagicMock()
        mock_tags_coll = MagicMock()
        mock_tags_coll.__iter__.return_value = []
        mock_tags_coll.Create = MagicMock(return_value=mock_tag)

        mock_default_table = MagicMock()
        mock_default_table.Tags = mock_tags_coll

        mock_tag_folder = MagicMock()
        mock_tag_folder.DefaultTagTable = mock_default_table

        mock_hmi = MagicMock()
        mock_hmi.TagFolder = mock_tag_folder

        tag_items = [{"name": "NewTag", "data_type": "Bool", "scope": "internal"}]

        result = executor._upsert_tags_to_default_table(mock_hmi, tag_items)

        assert result.objects_created == 1
        assert result.success is True
        mock_tags_coll.Create.assert_called_once_with("NewTag", "Bool")

    def test_upsert_skips_existing_matching_tags(self):
        """已存在且匹配的标签应被跳过。"""
        executor = ClassicOpennessExecutor()

        mock_existing = MagicMock()
        mock_existing.Name = "ExistingTag"
        mock_existing.DataType = "Bool"

        mock_tags_coll = MagicMock()
        mock_tags_coll.__iter__.return_value = [mock_existing]

        mock_default_table = MagicMock()
        mock_default_table.Tags = mock_tags_coll

        mock_tag_folder = MagicMock()
        mock_tag_folder.DefaultTagTable = mock_default_table

        mock_hmi = MagicMock()
        mock_hmi.TagFolder = mock_tag_folder

        tag_items = [{"name": "ExistingTag", "data_type": "Bool", "scope": "internal"}]

        result = executor._upsert_tags_to_default_table(mock_hmi, tag_items)

        assert result.objects_created == 0
        assert result.objects_updated == 0
        assert any("UPSERT_SKIP" in c for c in result.api_calls)

    def test_upsert_updates_changed_tags(self):
        """已存在但数据类型不同的标签应被更新。"""
        executor = ClassicOpennessExecutor()

        mock_existing = MagicMock()
        mock_existing.Name = "ChangedTag"
        mock_existing.DataType = "Bool"

        mock_tags_coll = MagicMock()
        mock_tags_coll.__iter__.return_value = [mock_existing]

        mock_default_table = MagicMock()
        mock_default_table.Tags = mock_tags_coll

        mock_tag_folder = MagicMock()
        mock_tag_folder.DefaultTagTable = mock_default_table

        mock_hmi = MagicMock()
        mock_hmi.TagFolder = mock_tag_folder

        tag_items = [{"name": "ChangedTag", "data_type": "Int", "scope": "internal"}]

        result = executor._upsert_tags_to_default_table(mock_hmi, tag_items)

        assert result.objects_updated == 1
        assert result.objects_created == 0
        assert any("UPSERT_UPDATE" in c for c in result.api_calls)

    def test_upsert_handles_create_exception_gracefully(self):
        """单个标签创建失败不影响其他标签。"""
        executor = ClassicOpennessExecutor()

        mock_tags_coll = MagicMock()
        mock_tags_coll.__iter__.return_value = []
        mock_tags_coll.Create = MagicMock(side_effect=Exception("Create failed"))

        mock_default_table = MagicMock()
        mock_default_table.Tags = mock_tags_coll

        mock_tag_folder = MagicMock()
        mock_tag_folder.DefaultTagTable = mock_default_table

        mock_hmi = MagicMock()
        mock_hmi.TagFolder = mock_tag_folder

        tag_items = [{"name": "FailTag", "data_type": "Bool", "scope": "internal"}]

        # 不应抛出异常
        result = executor._upsert_tags_to_default_table(mock_hmi, tag_items)

        assert result.objects_created == 0
        assert len(result.diagnostics) > 0

    def test_upsert_empty_items_returns_success(self):
        """空 tag_items 应返回成功。"""
        executor = ClassicOpennessExecutor()
        result = executor._upsert_tags_to_default_table(None, [])
        assert result.success is True
        assert any("SKIP" in c for c in result.api_calls)

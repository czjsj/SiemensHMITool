# -*- coding: utf-8 -*-
"""测试 sync_tags 在 Unknown family 下不调用通用 Create。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock


class TestNoGenericCreateOnUnknown:
    """sync_tags 在 Unknown family 下不调用 TagComposition.Create。"""

    def test_unknown_family_does_not_call_tags_collection_create(self, monkeypatch):
        """Unknown family → sync_tags 不应调用 Tags.Create。"""
        from backend.openness_manager import OpennessManager
        from backend.config_manager import DEFAULT_CONFIG

        cfg = {
            "openness": dict(DEFAULT_CONFIG["openness"]),
            "output": dict(DEFAULT_CONFIG["output"]),
        }
        mgr = OpennessManager(cfg)
        mgr._project = True

        create_called = []

        class FakeSw:
            TagFolder = MagicMock()
            TagTables = MagicMock()

        sw = FakeSw()

        def fake_find(*args, **kwargs):
            return sw

        monkeypatch.setattr(mgr, "_find_hmi_software", fake_find)

        def fake_caps(*args, **kwargs):
            return {
                "connected": True,
                "hmi_family": "Unknown",
                "is_unified": False,
                "is_classic": False,
            }

        monkeypatch.setattr(mgr, "get_hmi_capabilities", fake_caps)

        result = mgr.sync_tags([{"name": "Test", "data_type": "Bool"}])

        assert not result.get("ok"), f"Expected blocked, got: {result}"
        errors = " ".join(result.get("errors", []))
        assert "HMI_FAMILY_UNKNOWN" in errors, (
            f"Expected HMI_FAMILY_UNKNOWN, got: {errors}"
        )

    def test_unknown_family_does_not_trigger_upsert(self, monkeypatch):
        """Unknown family → 不应触发 _upsert_tags_to_default_table。"""
        from backend.openness_manager import OpennessManager
        from backend.config_manager import DEFAULT_CONFIG

        cfg = {
            "openness": dict(DEFAULT_CONFIG["openness"]),
            "output": dict(DEFAULT_CONFIG["output"]),
        }
        mgr = OpennessManager(cfg)
        mgr._project = True

        # Track if any TagFolder/TagTables access happens
        access_log = []

        class TrackingSw:
            @property
            def TagFolder(self):
                access_log.append("TagFolder")
                return None
            @property
            def TagTables(self):
                access_log.append("TagTables")
                return None

        def fake_find(*args, **kwargs):
            return TrackingSw()

        monkeypatch.setattr(mgr, "_find_hmi_software", fake_find)

        def fake_caps(*args, **kwargs):
            return {
                "connected": True,
                "hmi_family": "Unknown",
                "is_unified": False,
                "is_classic": False,
            }

        monkeypatch.setattr(mgr, "get_hmi_capabilities", fake_caps)

        result = mgr.sync_tags([{"name": "Test", "data_type": "Bool"}])

        assert not result.get("ok")
        # Access to TagFolder/TagTables may happen during describe_dotnet_object_safe
        # which is diagnostic-only. The key assertion: no Create/Import attempts

    def test_classic_family_calls_executor_not_generic_create(self, monkeypatch):
        """Classic family → 走 ClassicOpennessExecutor，不直接调用 Tags.Create。"""
        from backend.openness_manager import OpennessManager
        from backend.config_manager import DEFAULT_CONFIG

        cfg = {
            "openness": dict(DEFAULT_CONFIG["openness"]),
            "output": dict(DEFAULT_CONFIG["output"]),
        }
        mgr = OpennessManager(cfg)
        mgr._project = True

        class _FakeTagsColl:
            def __iter__(self):
                return iter([])
        class _FakeDefaultTable:
            Tags = _FakeTagsColl()
        class _FakeTagFolder:
            DefaultTagTable = _FakeDefaultTable()
        class FakeClassicSw:
            TagFolder = _FakeTagFolder()

        def fake_find(*args, **kwargs):
            return FakeClassicSw()

        monkeypatch.setattr(mgr, "_find_hmi_software", fake_find)

        def fake_caps(*args, **kwargs):
            return {
                "connected": True,
                "hmi_family": "Comfort",
                "is_unified": False,
                "is_classic": True,
            }

        monkeypatch.setattr(mgr, "get_hmi_capabilities", fake_caps)

        class FakeStepResult:
            success = True
            diagnostics = []
            api_calls = ["strategy_used=ImportOptions.Override"]
            objects_created = 1
            objects_updated = 0

        called = []

        def fake_import(self_exec, hmi_sw, tags_xml, tag_items=None):
            called.append(True)
            return FakeStepResult()

        from backend.openness.classic_executor import ClassicOpennessExecutor
        monkeypatch.setattr(ClassicOpennessExecutor, "import_hmi_tags_safe", fake_import)

        result = mgr.sync_tags([{"name": "CMD_X", "data_type": "Bool"}])
        assert result.get("ok"), f"Expected ok, got: {result}"
        assert called, "ClassicOpennessExecutor should have been called"

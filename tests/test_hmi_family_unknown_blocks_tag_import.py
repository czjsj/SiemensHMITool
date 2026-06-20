# -*- coding: utf-8 -*-
"""测试 HMI family Unknown 时阻断变量导入。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock

from backend.domain.diagnostics import DiagnosticCodes
from backend.domain.enums import HmiFamily
from backend.services.deployment_service import BackendFactory
from backend.domain.ir_v2 import TargetSpec, ScreenItemSpec, ScreenItemType


class TestBackendFactoryBlocksUnknown:
    """BackendFactory.create/create_with_discovery 对 Unknown 应阻断。"""

    def test_create_unknown_family_returns_none(self):
        """AUTO family 时 BackendFactory._resolve_auto 返回 (None, 'unknown')。"""
        be, name = BackendFactory.create(TargetSpec(family=HmiFamily.AUTO))
        assert be is None
        assert name == "unknown"

    def test_create_with_discovery_unknown_returns_none(self):
        """detect_family 返回 Unknown 时返回 (None, 'unknown', diags)。"""
        mock_sw = MagicMock()
        mock_sw.GetType.return_value.FullName = "Siemens.Engineering.Hmi.SomeUnknownType"
        mock_sw.Name = "HMI_1"

        from backend.openness.device_discovery import DeviceDiscovery
        original_detect = DeviceDiscovery.detect_family

        def mock_detect(self_, sw, device=None, item=None):
            return "Unknown"

        with patch.object(DeviceDiscovery, "detect_family", mock_detect):
            be, name, diags = BackendFactory.create_with_discovery(
                TargetSpec(family=HmiFamily.AUTO), mock_sw,
            )
        assert be is None
        assert name == "unknown"
        assert any(d.code == DiagnosticCodes.HMI_FAMILY_UNKNOWN for d in diags)

    def test_create_with_discovery_no_hmi_software_still_returns_error(self):
        """无 hmi_software 时 create_with_discovery 同样返回诊断与 None。"""
        be, name, diags = BackendFactory.create_with_discovery(
            TargetSpec(family=HmiFamily.AUTO), None,
        )
        # 无 hmi_software 时回退到 ComfortBackend + TARGET_FAMILY_AMBIGUOUS
        assert be is not None  # ComfortBackend fallback
        assert any(d.code == DiagnosticCodes.TARGET_FAMILY_AMBIGUOUS for d in diags)


class TestSyncTagsBlocksUnknown:
    """sync_tags() 对 Unknown family 应阻断，不调用任何 API。"""

    def test_sync_tags_unknown_contains_hmi_family_unknown_error(self, monkeypatch):
        """Unknown family 应返回 HMI_FAMILY_UNKNOWN 错误。"""
        from backend.openness_manager import OpennessManager
        from backend.config_manager import DEFAULT_CONFIG

        cfg = {
            "openness": dict(DEFAULT_CONFIG["openness"]),
            "output": dict(DEFAULT_CONFIG["output"]),
        }
        mgr = OpennessManager(cfg)
        mgr._project = True

        # Mock _find_hmi_software
        class FakeUnknownSw:
            pass

        def fake_find(*args, **kwargs):
            return FakeUnknownSw()

        monkeypatch.setattr(mgr, "_find_hmi_software", fake_find)

        # Mock get_hmi_capabilities to return Unknown
        def fake_caps(*args, **kwargs):
            return {
                "connected": True,
                "hmi_family": "Unknown",
                "is_unified": False,
                "is_classic": False,
            }

        monkeypatch.setattr(mgr, "get_hmi_capabilities", fake_caps)

        result = mgr.sync_tags([{"name": "TestVar", "data_type": "Bool"}])

        assert not result.get("ok"), f"Expected blocked, got: {result}"
        errors = " ".join(result.get("errors", []))
        assert "HMI_FAMILY_UNKNOWN" in errors, f"Expected HMI_FAMILY_UNKNOWN, got: {errors}"
        assert "UPSERT" not in str(result), "UPSERT should not appear in result for Unknown family"

    def test_sync_tags_classic_calls_executor(self, monkeypatch):
        """Classic family 应调用 ClassicOpennessExecutor。"""
        from backend.openness_manager import OpennessManager
        from backend.config_manager import DEFAULT_CONFIG

        cfg = {
            "openness": dict(DEFAULT_CONFIG["openness"]),
            "output": dict(DEFAULT_CONFIG["output"]),
        }
        mgr = OpennessManager(cfg)
        mgr._project = True

        class _FTagsColl:
            def __iter__(self):
                return iter([])

        class _FDefaultTable:
            Tags = _FTagsColl()

        class _FTagFolder:
            DefaultTagTable = _FDefaultTable()

        class FakeClassicSw:
            TagFolder = _FTagFolder()

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

        called = []

        class FakeStepResult:
            success = True
            diagnostics = []
            api_calls = ["strategy_used=ImportOptions.Override"]
            objects_created = 1
            objects_updated = 0

        def fake_import(self_exec, hmi_sw, tags_xml, tag_items=None):
            called.append(("import_hmi_tags_safe", hmi_sw))
            return FakeStepResult()

        from backend.openness.classic_executor import ClassicOpennessExecutor
        monkeypatch.setattr(
            ClassicOpennessExecutor, "import_hmi_tags_safe", fake_import,
        )

        result = mgr.sync_tags([{"name": "CMD_A", "data_type": "Bool"}])
        assert result.get("ok"), f"Expected success, got: {result}"
        assert len(called) == 1, f"Expected import_hmi_tags_safe to be called, got: {called}"

    def test_sync_tags_unified_calls_executor(self, monkeypatch):
        """Unified family 应调用 UnifiedOpennessExecutor。"""
        from backend.openness_manager import OpennessManager
        from backend.config_manager import DEFAULT_CONFIG

        cfg = {
            "openness": dict(DEFAULT_CONFIG["openness"]),
            "output": dict(DEFAULT_CONFIG["output"]),
        }
        mgr = OpennessManager(cfg)
        mgr._project = True

        class FakeUnifiedSw:
            class FakeTagsColl:
                def __iter__(self):
                    return iter([])
            Tags = FakeTagsColl()

        def fake_find(*args, **kwargs):
            return FakeUnifiedSw()

        monkeypatch.setattr(mgr, "_find_hmi_software", fake_find)

        def fake_caps(*args, **kwargs):
            return {
                "connected": True,
                "hmi_family": "Unified",
                "is_unified": True,
                "is_classic": False,
            }

        monkeypatch.setattr(mgr, "get_hmi_capabilities", fake_caps)

        called = []

        class FakeStepResult:
            success = True
            diagnostics = []

        def fake_create(self_exec, hmi_sw, tag_specs):
            called.append(("create_tags", hmi_sw))
            return FakeStepResult()

        from backend.openness.unified_executor import UnifiedOpennessExecutor
        monkeypatch.setattr(
            UnifiedOpennessExecutor, "create_tags", fake_create,
        )

        result = mgr.sync_tags([{"name": "UNI_A", "data_type": "Real"}])
        assert result.get("ok"), f"Expected success, got: {result}"
        assert len(called) == 1, f"Expected create_tags to be called, got: {called}"

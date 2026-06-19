# -*- coding: utf-8 -*-
"""测试 PR-04: Openness 模块拆分 — 不依赖实际 TIA 连接。"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.openness.assembly_loader import AssemblyLoader, AssemblyMetadata
from backend.openness.exception_mapper import ExceptionMapper
from backend.openness.compiler import HmiCompiler
from backend.domain.diagnostics import Diagnostic, DiagnosticCodes


class TestAssemblyLoader:
    """AssemblyLoader 测试（不加载实际 DLL）。"""

    def test_diagnose(self):
        loader = AssemblyLoader()
        result = loader.diagnose()
        assert "os" in result
        assert "is_windows" in result
        assert "pythonnet_available" in result

    def test_load_nonexistent_dll(self):
        loader = AssemblyLoader()
        meta = loader.load(r"C:\nonexistent\path.dll")
        assert not meta.is_loaded
        assert len(meta.errors) > 0

    def test_assembly_metadata_defaults(self):
        meta = AssemblyMetadata()
        assert not meta.is_loaded
        assert meta.tia_version == ""
        assert meta.public_types == []

    def test_assembly_metadata_to_dict(self):
        meta = AssemblyMetadata(
            tia_version="V18",
            dll_path="C:/dll/test.dll",
            is_loaded=True,
            assembly_version="1.0.0",
        )
        d = meta.to_dict()
        assert d["tia_version"] == "V18"
        assert d["is_loaded"] is True

    def test_get_loaded_returns_none_for_unknown(self):
        loader = AssemblyLoader()
        assert loader.get_loaded("unknown.dll") is None


class TestExceptionMapper:
    """ExceptionMapper 测试。"""

    def test_maps_known_pattern(self):
        mapper = ExceptionMapper()
        exc = RuntimeError("Screen already exists in project")
        diag = mapper.map(exc, phase="P50_SCREENS", object_name="Screen1")
        assert isinstance(diag, Diagnostic)
        assert diag.code == DiagnosticCodes.CLASSIC_DUPLICATE_ID
        assert diag.severity.value == "error"

    def test_maps_unknown_exception(self):
        mapper = ExceptionMapper()
        exc = ValueError("Something completely unexpected happened")
        diag = mapper.map(exc, phase="P30_TAG_TABLES_AND_TAGS")
        assert isinstance(diag, Diagnostic)
        assert diag.code == DiagnosticCodes.IMPORT_TIA_EXCEPTION
        assert "exception_type" in diag.details

    def test_maps_disposed_exception(self):
        mapper = ExceptionMapper()
        exc = RuntimeError("Cannot access disposed object")
        diag = mapper.map(exc, phase="P50_SCREENS")
        assert diag.code == DiagnosticCodes.IMPORT_TIA_EXCEPTION

    def test_maps_compile_error(self):
        mapper = ExceptionMapper()
        exc = Exception("HMI compile error: invalid tag reference")
        diag = mapper.map(exc, phase="P70_COMPILE")
        assert diag.code == DiagnosticCodes.COMPILE_ERROR

    def test_maps_syntax_error(self):
        mapper = ExceptionMapper()
        exc = SyntaxError("JavaScript syntax error at line 5")
        diag = mapper.map(exc, phase="P40_SCRIPTS_AND_RESOURCES")
        assert diag.code == DiagnosticCodes.SCRIPT_SYNTAX_FAILED

    def test_maps_not_supported(self):
        mapper = ExceptionMapper()
        exc = NotImplementedError("Operation not supported for Basic Panel")
        diag = mapper.map(exc, phase="P50_SCREENS")
        assert diag.code == DiagnosticCodes.CAP_UNSUPPORTED_FEATURE

    def test_remediation_included(self):
        mapper = ExceptionMapper()
        exc = RuntimeError("Tag not found in controller")
        diag = mapper.map(exc, phase="P30_TAG_TABLES_AND_TAGS", object_name="Motor_Start")
        assert diag.remediation is not None

    def test_context_preserved(self):
        mapper = ExceptionMapper()
        exc = RuntimeError("test")
        diag = mapper.map(
            exc,
            phase="P50_SCREENS",
            object_type="screen_item",
            object_name="BTN_Start",
            context={"xml_path": "/tmp/test.xml"},
        )
        assert diag.details["context"]["xml_path"] == "/tmp/test.xml"


class TestHmiCompiler:
    """HmiCompiler 测试（不依赖实际 HMI）。"""

    def test_compile_no_hmi(self):
        compiler = HmiCompiler()
        result = compiler.compile(None)
        assert not result["ok"]
        assert len(result["messages"]) > 0

    def test_syntax_check_placeholder(self):
        compiler = HmiCompiler()
        result = compiler.syntax_check("console.log('test');", language="javascript")
        assert result["ok"] is True
        assert len(result["errors"]) == 0


class TestOpennessManagerFacade:
    """验证 OpennessManager façade 委托属性可访问。"""

    def test_facade_properties_accessible(self):
        """OpennessManager 的 delegate 属性可访问（不加载实际模块时不抛异常）。"""
        from backend.openness_manager import OpennessManager
        from backend.config_manager import DEFAULT_CONFIG

        cfg = {
            "openness": dict(DEFAULT_CONFIG["openness"]),
            "output": dict(DEFAULT_CONFIG["output"]),
        }
        mgr = OpennessManager(cfg)

        # 访问委托属性（会触发 lazy-init）
        assert mgr.exception_mapper is not None
        exc = RuntimeError("test")
        diag = mgr.exception_mapper.map(exc)
        assert isinstance(diag, Diagnostic)

        # 编译器
        assert mgr.compiler is not None

        # AssemblyLoader
        assert mgr.assembly_loader is not None

    def test_facade_old_api_still_works(self):
        """旧 API 仍可用：diagnose, disconnect 等。"""
        from backend.openness_manager import OpennessManager
        from backend.config_manager import DEFAULT_CONFIG

        cfg = {
            "openness": dict(DEFAULT_CONFIG["openness"]),
            "output": dict(DEFAULT_CONFIG["output"]),
        }
        mgr = OpennessManager(cfg)

        result = mgr.diagnose()
        assert isinstance(result, dict)
        assert "os" in result

        result2 = mgr.disconnect()
        assert result2["disconnected"] is True

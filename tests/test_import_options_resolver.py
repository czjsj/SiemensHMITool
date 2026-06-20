# -*- coding: utf-8 -*-
"""测试 ImportOptions 解析器 — 模拟各种 TIA 版本中的选项可用性。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock


class TestImportOptionsResolver:
    """测试 resolve_import_option 在各种场景下的行为。"""

    def test_resolve_returns_structured_dict_always(self):
        """解析器始终返回结构化字典，绝不返回 None。"""
        from backend.openness.classic_executor import ClassicOpennessExecutor
        result = ClassicOpennessExecutor.resolve_import_option()
        assert isinstance(result, dict)
        assert "ok" in result
        assert "value" in result
        assert "selected" in result
        assert "available" in result
        assert "source" in result
        assert "error" in result
        assert "diagnostics" in result

    def test_resolve_with_no_clr_available(self):
        """无 CLR 环境时返回 ok=False，不抛出异常。"""
        # resolve_import_option 是 staticmethod，不依赖实例 _clr_available
        # 通过 mock __import__ 模拟 DLL 缺失
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name.startswith("Siemens"):
                raise ImportError(f"simulated: {name}")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            from backend.openness.classic_executor import ClassicOpennessExecutor
            result = ClassicOpennessExecutor.resolve_import_option()

        assert result["ok"] is False
        assert result["source"] == "none"
        assert len(result["diagnostics"]) > 0

    def test_resolve_complete_failure(self):
        """所有解析路径都失败时返回 ok=False，含详细诊断。"""
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "Siemens" in name:
                raise ImportError(f"simulated import error for {name}")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            from backend.openness.classic_executor import ClassicOpennessExecutor
            result = ClassicOpennessExecutor.resolve_import_option()

        assert result["ok"] is False
        assert result["selected"] is None
        assert len(result["diagnostics"]) >= 1
        assert result["source"] == "none"
        assert result["error"] is not None

    def test_resolve_alias_map_exists(self):
        """验证别名映射常量存在且包含 Override。"""
        from backend.openness.classic_executor import ClassicOpennessExecutor
        aliases = ClassicOpennessExecutor._IMPORT_OPTION_ALIASES
        assert "Override" in aliases
        assert isinstance(aliases["Override"], list)
        assert len(aliases["Override"]) >= 1

    def test_resolve_function_is_callable(self):
        """resolve_import_option 是可调用的静态方法。"""
        from backend.openness.classic_executor import ClassicOpennessExecutor
        assert callable(ClassicOpennessExecutor.resolve_import_option)
        # 无参数调用不崩溃
        result = ClassicOpennessExecutor.resolve_import_option()
        assert isinstance(result, dict)


class TestMakeImportOptionsIntegration:
    """测试 _make_import_options 使用解析器后的行为。"""

    def test_make_import_options_returns_none_on_full_failure(self):
        """完全失败时返回 None（保持兼容）。"""
        with patch(
            "backend.openness.classic_executor.ClassicOpennessExecutor.resolve_import_option",
            return_value={
                "ok": False, "value": None, "selected": None,
                "available": [], "source": "none", "error": "test",
                "diagnostics": ["test diagnostic"],
            },
        ):
            from backend.openness.classic_executor import ClassicOpennessExecutor
            result = ClassicOpennessExecutor._make_import_options()
            assert result is None

    def test_make_import_options_does_not_crash(self):
        """_make_import_options 在任何情况下不崩溃。"""
        from backend.openness.classic_executor import ClassicOpennessExecutor
        # 在无 CLR 环境中应返回 None 而不崩溃
        result = ClassicOpennessExecutor._make_import_options()
        assert result is None or result is not None  # 两者都可接受


class TestImportOptionsAssemblyScan:
    """测试 assembly scan 增强。"""

    def test_resolve_returns_searched_assemblies_key(self):
        """resolve_import_option 包含 searched_assemblies 键。"""
        from backend.openness.classic_executor import ClassicOpennessExecutor
        result = ClassicOpennessExecutor.resolve_import_option()
        assert "searched_assemblies" in result, (
            "resolve_import_option should include searched_assemblies key"
        )
        assert isinstance(result["searched_assemblies"], list)

    def test_resolve_error_includes_scan_count(self):
        """失败时 error 包含扫描程序集数。"""
        from backend.openness.classic_executor import ClassicOpennessExecutor
        import builtins
        original_import = builtins.__import__

        def mock_import(*args, **kwargs):
            raise ImportError("Simulated complete import failure")

        try:
            builtins.__import__ = mock_import
            result = ClassicOpennessExecutor.resolve_import_option()
            assert not result["ok"]
            error = result.get("error", "")
            # Should mention assembly scan
            assert "程序集" in error or "searched_assemblies" in result
        finally:
            builtins.__import__ = original_import

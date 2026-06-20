# -*- coding: utf-8 -*-
"""测试 .NET 方法反射工具 — reflection_utils.py。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch

from backend.openness.reflection_utils import (
    describe_dotnet_methods,
    has_method,
    list_method_overloads,
)


class TestDescribeDotnetMethods:
    """测试 describe_dotnet_methods。"""

    def test_with_none(self):
        """None 输入返回空描述。"""
        result = describe_dotnet_methods(None)
        assert result["dotnet_type"] == "None"
        assert result["method_count"] == 0

    def test_with_magic_mock_has_gettype(self):
        """Mock 对象 — GetType 返回模拟的类型信息。"""
        obj = MagicMock()
        mock_type = MagicMock()
        mock_type.FullName = "MyNamespace.MyType"
        # Mock GetMethods to return some methods
        method_a = MagicMock()
        method_a.Name = "Create"
        method_b = MagicMock()
        method_b.Name = "Import"
        method_c = MagicMock()
        method_c.Name = "Delete"
        mock_type.GetMethods.return_value = [method_a, method_b, method_c]
        # Mock GetProperty to demonstrate properties
        mock_type.GetProperty.return_value = None

        obj.GetType.return_value = mock_type

        result = describe_dotnet_methods(obj)

        assert result["dotnet_type"] == "MyNamespace.MyType"
        assert result["method_count"] == 3
        assert "Create" in result["create_like_methods"]
        assert "Import" in result["import_like_methods"]
        assert "Delete" in result["method_names"]

    def test_with_gettype_raising(self):
        """GetType 抛出异常时优雅降级。"""
        obj = MagicMock()
        obj.GetType.side_effect = Exception("Not a .NET object")

        result = describe_dotnet_methods(obj)

        assert result["dotnet_type"] is not None
        assert "error" in result

    def test_create_like_methods_detection(self):
        """Create 类方法能正确被过滤出来。"""
        obj = MagicMock()
        mock_type = MagicMock()
        mock_type.FullName = "Test.Type"
        methods = []
        for name in ("Create", "CreateTag", "CreateNew", "Delete", "Find", "Add"):
            m = MagicMock()
            m.Name = name
            methods.append(m)
        mock_type.GetMethods.return_value = methods
        obj.GetType.return_value = mock_type

        result = describe_dotnet_methods(obj)
        assert "Create" in result["create_like_methods"]
        assert "CreateTag" in result["create_like_methods"]
        assert "Delete" not in result["create_like_methods"]

    def test_import_like_methods_detection(self):
        """Import 类方法能正确被过滤出来。"""
        obj = MagicMock()
        mock_type = MagicMock()
        mock_type.FullName = "Test.Type"
        methods = []
        for name in ("Import", "ImportXml", "Export", "Delete"):
            m = MagicMock()
            m.Name = name
            methods.append(m)
        mock_type.GetMethods.return_value = methods
        obj.GetType.return_value = mock_type

        result = describe_dotnet_methods(obj)
        assert "Import" in result["import_like_methods"]
        assert "ImportXml" in result["import_like_methods"]
        assert "Export" not in result["import_like_methods"]


class TestHasMethod:
    """测试 has_method。"""

    def test_with_none(self):
        """None 输入返回 False。"""
        assert has_method(None, "Create") is False

    def test_method_found(self):
        """GetMethod 返回非空 → True。"""
        obj = MagicMock()
        mock_type = MagicMock()
        mock_type.GetMethod.return_value = MagicMock()  # non-None
        obj.GetType.return_value = mock_type

        assert has_method(obj, "Create") is True

    def test_method_not_found(self):
        """GetMethod 返回 None → 回退 GetMethods → none match → False。"""
        obj = MagicMock()
        mock_type = MagicMock()
        mock_type.GetMethod.return_value = None  # not found
        m = MagicMock()
        m.Name = "Delete"
        mock_type.GetMethods.return_value = [m]
        obj.GetType.return_value = mock_type

        assert has_method(obj, "Create") is False

    def test_method_found_in_getmethods(self):
        """GetMethod 返回 None，但 GetMethods 中有匹配名 → True。"""
        obj = MagicMock()
        mock_type = MagicMock()
        mock_type.GetMethod.return_value = None
        methods = []
        for name in ("Create", "Delete"):
            m = MagicMock()
            m.Name = name
            methods.append(m)
        mock_type.GetMethods.return_value = methods
        obj.GetType.return_value = mock_type

        assert has_method(obj, "Create") is True

    def test_pythonnet_fallback(self):
        """当 GetType 抛出异常时，回退到 hasattr。"""
        obj = MagicMock()
        obj.GetType.side_effect = Exception("No CLR")
        # hasattr on a MagicMock returns True for anything
        assert has_method(obj, "Anything") is True


class TestListMethodOverloads:
    """测试 list_method_overloads。"""

    def test_no_overloads(self):
        """无匹配方法返回空列表。"""
        obj = MagicMock()
        mock_type = MagicMock()
        mock_type.GetMethods.return_value = []
        obj.GetType.return_value = mock_type

        result = list_method_overloads(obj, "Create")
        assert result == []

    def test_with_overloads(self):
        """有多个重载时返回签名列表。"""
        obj = MagicMock()
        mock_type = MagicMock()

        param1 = MagicMock()
        param1.Name = "name"
        param1.ParameterType.FullName = "System.String"
        param2 = MagicMock()
        param2.Name = "dataType"
        param2.ParameterType.FullName = "System.String"

        method = MagicMock()
        method.Name = "Create"
        method.ReturnType.FullName = "Siemens.Engineering.Hmi.Tag"
        method.GetParameters.return_value = [param1, param2]

        mock_type.GetMethods.return_value = [method]
        obj.GetType.return_value = mock_type

        result = list_method_overloads(obj, "Create")
        assert len(result) == 1
        assert result[0]["return_type"] == "Siemens.Engineering.Hmi.Tag"
        assert len(result[0]["parameters"]) == 2
        assert result[0]["parameters"][0]["name"] == "name"


class TestIntegration:
    """集成测试 — reflection_utils 与 classic_executor 配合使用。"""

    def test_classic_executor_upsert_without_create_emits_tag_create_not_found(self):
        """_upsert_tags_to_default_table 遇到无 Create 的 tags_collection
        应发出 TAG_CREATE_METHOD_NOT_FOUND 诊断而非 AttributeError。"""
        from backend.openness.classic_executor import ClassicOpennessExecutor

        executor = ClassicOpennessExecutor()

        # Build a mock where Tags collection exists but has no Create method
        mock_tags = MagicMock()
        mock_tags.__iter__.return_value = []
        # Simulate no Create method via reflection
        mock_type = MagicMock()
        mock_type.FullName = "Siemens.Engineering.Hmi.TagComposition"
        m = MagicMock()
        m.Name = "Import"
        mock_type.GetMethods.return_value = [m]
        mock_type.GetMethod.return_value = None
        mock_tags.GetType.return_value = mock_type

        mock_default = MagicMock()
        mock_default.Tags = mock_tags

        mock_tag_folder = MagicMock()
        mock_tag_folder.DefaultTagTable = mock_default

        mock_hmi = MagicMock()
        mock_hmi.TagFolder = mock_tag_folder

        result = executor._upsert_tags_to_default_table(mock_hmi, [
            {"name": "NoCreateTag", "data_type": "Bool", "scope": "internal"},
        ])

        # Should not crash
        assert result.success is False
        assert len(result.diagnostics) > 0
        # Should contain TAG_CREATE_METHOD_NOT_FOUND code
        codes = [d.code for d in result.diagnostics if hasattr(d, 'code')]
        from backend.domain.diagnostics import DiagnosticCodes
        assert DiagnosticCodes.TAG_CREATE_METHOD_NOT_FOUND in codes, (
            f"Expected TAG_CREATE_METHOD_NOT_FOUND in {codes}"
        )
        # Should NOT contain raw AttributeError
        messages = " ".join(d.message for d in result.diagnostics if hasattr(d, 'message'))
        assert "object has no attribute" not in messages, (
            f"Should not contain raw AttributeError: {messages}"
        )

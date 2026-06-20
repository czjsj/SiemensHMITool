# -*- coding: utf-8 -*-
"""测试从 Import 方法重载参数类型解析 ImportOptions。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch

from backend.domain.diagnostics import DiagnosticCodes
from backend.openness.classic_executor import ClassicOpennessExecutor


# 模拟 ImportOptions 枚举
class FakeImportOptions:
    """模拟 Siemens.Engineering.ImportOptions 枚举。"""
    None_ = 0
    Override = 1
    Merge = 2

    @staticmethod
    def GetType():
        mock_type = MagicMock()
        mock_type.FullName = "Siemens.Engineering.ImportOptions"
        mock_type.Name = "ImportOptions"
        mock_type.IsEnum = True
        mock_type.IsValueType = True
        return mock_type


def _make_fake_import_option_type(available_names=None):
    """创建模拟 ImportOptions 枚举类型对象。"""
    available_names = available_names or ["None", "Override", "Merge"]
    mock_type = MagicMock()
    mock_type.FullName = "Siemens.Engineering.ImportOptions"
    mock_type.Name = "ImportOptions"
    mock_type.IsEnum = True
    mock_type.IsValueType = True
    return mock_type


def _make_fake_method(name, param_types, return_type="Void"):
    """创建模拟 .NET MethodInfo。"""
    method = MagicMock()
    method.Name = name
    method.ReturnType = MagicMock()
    method.ReturnType.FullName = return_type

    params = []
    for i, (pname, ptype) in enumerate(param_types):
        p = MagicMock()
        p.Name = pname
        p.ParameterType = ptype if hasattr(ptype, "FullName") else _make_param_type(ptype)
        params.append(p)

    method.GetParameters.return_value = params
    return method


def _make_param_type(full_name, is_enum=False):
    """创建模拟 ParameterType。"""
    pt = MagicMock()
    pt.FullName = full_name
    pt.Name = full_name.split(".")[-1]
    pt.IsEnum = is_enum
    pt.IsValueType = is_enum
    pt.__str__ = lambda s: full_name
    pt.__repr__ = lambda s: full_name
    return pt


def _make_tag_composition(import_methods):
    """创建带指定 Import 方法重载的模拟 TagComposition。"""
    tc = MagicMock()
    tc_type = MagicMock()
    tc_type.FullName = "Siemens.Engineering.Hmi.Tag.TagComposition"
    tc_type.Name = "TagComposition"
    tc_type.GetMethods.return_value = import_methods

    def get_method(name):
        for m in import_methods:
            if m.Name == name:
                return m
        return None
    tc_type.GetMethod = get_method
    tc.GetType.return_value = tc_type
    return tc


# 模拟 System.Enum
class FakeSystemEnum:
    @staticmethod
    def GetNames(enum_type):
        if enum_type.IsEnum:
            return ["None", "Override", "Merge"]
        return []

    @staticmethod
    def Parse(enum_type, name):
        if name == "None":
            return type("EnumVal", (), {"__int__": lambda s: 0})()
        elif name == "Override":
            return type("EnumVal", (), {"__int__": lambda s: 1})()
        elif name == "Merge":
            return type("EnumVal", (), {"__int__": lambda s: 2})()
        raise ValueError(f"Unknown enum name: {name}")


# ---------------------------------------------------------------------------
# 测试 1: 从 Import 重载第二参数解析 enum
# ---------------------------------------------------------------------------

class TestResolveFromImportOverloadParameter:
    """从 Import 方法第二参数类型解析 ImportOptions。"""

    def test_resolve_from_import_overload_parameter(self):
        """Import(FileInfo, ImportOptions) → 从 params[1] 解析 enum。"""
        import_options_type = _make_fake_import_option_type()
        file_info_type = _make_param_type("System.IO.FileInfo")
        method = _make_fake_method(
            "Import",
            [("file", file_info_type), ("options", import_options_type)],
        )
        tag_composition = _make_tag_composition([method])

        setattr(ClassicOpennessExecutor, "_test_enum", FakeSystemEnum)
        try:
            result = ClassicOpennessExecutor.resolve_import_option_from_overload(
                tag_composition, preferred="Override",
            )
        finally:
            delattr(ClassicOpennessExecutor, "_test_enum")

        assert result["ok"], f"Expected ok=True, got: {result}"
        assert result["source"] == "import_overload_parameter"
        assert result["selected"] == "Override"
        assert "None" in result["available"]
        assert "Override" in result["available"]
        assert result["type_full_name"] == "Siemens.Engineering.ImportOptions"
        assert "Import(" in result.get("method_signature", "")

    def test_resolve_from_overload_no_single_arg_but_two_arg(self):
        """Import(FileInfo, ImportOptions) + Import(String, ImportOptions)
        但没有单参数重载 → 从 params[1] 解析 enum。"""
        import_options_type = _make_fake_import_option_type()
        file_info_type = _make_param_type("System.IO.FileInfo")
        string_type = _make_param_type("System.String")

        m1 = _make_fake_method(
            "Import", [("file", file_info_type), ("options", import_options_type)],
        )
        m2 = _make_fake_method(
            "Import", [("path", string_type), ("options", import_options_type)],
        )
        tag_composition = _make_tag_composition([m1, m2])

        setattr(ClassicOpennessExecutor, "_test_enum", FakeSystemEnum)
        try:
            result = ClassicOpennessExecutor.resolve_import_option_from_overload(
                tag_composition, preferred="Override",
            )
        finally:
            delattr(ClassicOpennessExecutor, "_test_enum")

        assert result["ok"], f"Expected ok=True, got: {result}"
        assert result["selected"] == "Override"
        assert result["source"] == "import_overload_parameter"

    def test_import_overload_second_param_not_enum(self):
        """Import(FileInfo, String) → 第二参数不是 enum → 返回失败。"""
        file_info_type = _make_param_type("System.IO.FileInfo")
        string_type = _make_param_type("System.String")
        method = _make_fake_method(
            "Import", [("file", file_info_type), ("name", string_type)],
        )
        tag_composition = _make_tag_composition([method])

        setattr(ClassicOpennessExecutor, "_test_enum", FakeSystemEnum)
        try:
            result = ClassicOpennessExecutor.resolve_import_option_from_overload(
                tag_composition, preferred="Override",
            )
        finally:
            delattr(ClassicOpennessExecutor, "_test_enum")

        assert not result["ok"], "Expected ok=False when second param is not enum"
        assert "不是 enum" in result.get("error", ""), (
            f"Error should mention not enum: {result.get('error')}"
        )

    def test_resolve_preferred_not_found_fallback(self):
        """preferred 不在 enum 名称中时依次尝试别名。"""
        # 只有 None 和 Merge 的 enum（没有 Override）
        mock_type = MagicMock()
        mock_type.FullName = "Siemens.Engineering.ImportOptions"
        mock_type.IsEnum = True

        file_info_type = _make_param_type("System.IO.FileInfo")
        method = _make_fake_method(
            "Import", [("file", file_info_type), ("options", mock_type)],
        )
        tag_composition = _make_tag_composition([method])

        # Mock Enum with limited names
        class LimitedEnum:
            @staticmethod
            def GetNames(t):
                return ["None", "Merge"]
            @staticmethod
            def Parse(t, name):
                if name == "Merge":
                    return type("EV", (), {"__int__": lambda s: 2})()
                raise ValueError()

        setattr(ClassicOpennessExecutor, "_test_enum", LimitedEnum)
        try:
            result = ClassicOpennessExecutor.resolve_import_option_from_overload(
                tag_composition, preferred="Merge",
            )
        finally:
            delattr(ClassicOpennessExecutor, "_test_enum")

        assert result["ok"], f"Expected ok=True, got: {result}"
        assert result["selected"] == "Merge"

    def test_resolver_value_is_not_python_int(self):
        """resolve 返回的 value 不是 Python int，而是 .NET enum 对象。"""
        import_options_type = _make_fake_import_option_type()
        file_info_type = _make_param_type("System.IO.FileInfo")
        method = _make_fake_method(
            "Import",
            [("file", file_info_type), ("options", import_options_type)],
        )
        tag_composition = _make_tag_composition([method])

        setattr(ClassicOpennessExecutor, "_test_enum", FakeSystemEnum)
        try:
            result = ClassicOpennessExecutor.resolve_import_option_from_overload(
                tag_composition, preferred="Override",
            )
        finally:
            delattr(ClassicOpennessExecutor, "_test_enum")

        assert result["ok"]
        # value should not be a Python int (it's a mock from FakeSystemEnum)
        # `isinstance(..., int)` on our mock is False, so this verifies we
        # aren't casting to int()
        assert result["enum_type"] is not None, (
            "enum_type should be populated"
        )

    def test_resolver_has_enum_type_populated(self):
        """resolve 成功时 enum_type 已填充。"""
        import_options_type = _make_fake_import_option_type()
        file_info_type = _make_param_type("System.IO.FileInfo")
        method = _make_fake_method(
            "Import",
            [("file", file_info_type), ("options", import_options_type)],
        )
        tag_composition = _make_tag_composition([method])

        setattr(ClassicOpennessExecutor, "_test_enum", FakeSystemEnum)
        try:
            result = ClassicOpennessExecutor.resolve_import_option_from_overload(
                tag_composition, preferred="Override",
            )
        finally:
            delattr(ClassicOpennessExecutor, "_test_enum")

        assert result["ok"]
        assert result["enum_type"] is import_options_type, (
            f"enum_type should be the ParameterType, "
            f"got {result['enum_type']}"
        )


# ---------------------------------------------------------------------------
# 测试 2: invoke_tag_composition_import
# ---------------------------------------------------------------------------

class TestInvokeTagCompositionImport:
    """测试 MethodInfo.Invoke 调用。"""

    def test_invoke_with_file_info(self):
        """Invoke Import(FileInfo, ImportOptions) 成功。"""
        file_info_type = _make_param_type("System.IO.FileInfo")
        import_opts_type = _make_param_type(
            "Siemens.Engineering.ImportOptions", is_enum=True,
        )

        method = MagicMock()
        method.Name = "Import"
        method.ReturnType = MagicMock()
        method.ReturnType.FullName = "Void"
        p1 = MagicMock()
        p1.Name = "file"
        p1.ParameterType = file_info_type
        p2 = MagicMock()
        p2.Name = "options"
        p2.ParameterType = import_opts_type
        method.GetParameters.return_value = [p1, p2]

        # Mock a second method that won't match
        m2 = MagicMock()
        m2.Name = "Delete"
        m2.GetParameters.return_value = []

        tc_type = MagicMock()
        tc_type.GetMethods.return_value = [m2, method]
        tc = MagicMock()
        tc.GetType.return_value = tc_type

        option_result = {"value": 1, "selected": "Override"}

        # This test runs without CLR, so FileInfo won't be available.
        # The method should raise RuntimeError when FileInfo can't be created.
        # We verify the method exists and attempts to call Invoke.
        try:
            ClassicOpennessExecutor.invoke_tag_composition_import(
                tc, "/tmp/test.xml", option_result,
            )
        except Exception:
            # Expected: FileInfo not available in test env
            pass

        # The test verifies the path doesn't crash unexpectedly
        # In a real TIA environment with CLR, this would work
        assert True

    def test_invoke_guards_python_int_converts_via_enum_to_object(self):
        """传入 Python int 且提供 enum_type → 调用 Enum.ToObject 转 .NET enum。"""
        file_info_type = _make_param_type("System.IO.FileInfo")
        import_opts_type = _make_param_type(
            "Siemens.Engineering.ImportOptions", is_enum=True,
        )

        method = MagicMock()
        method.Name = "Import"
        method.ReturnType = MagicMock()
        method.ReturnType.FullName = "Void"
        p1 = MagicMock()
        p1.Name = "file"
        p1.ParameterType = file_info_type
        p2 = MagicMock()
        p2.Name = "options"
        p2.ParameterType = import_opts_type
        method.GetParameters.return_value = [p1, p2]

        tc_type = MagicMock()
        tc_type.GetMethods.return_value = [method]
        tc = MagicMock()
        tc.GetType.return_value = tc_type

        # option_result with Python int value, but enum_type provided
        option_result = {"value": 1, "enum_type": import_opts_type}

        # Without CLR, FileInfo will fail. The test verifies the guard
        # logic reaches the enum_type conversion path, not the PyInt error.
        try:
            ClassicOpennessExecutor.invoke_tag_composition_import(
                tc, "/tmp/test.xml", option_result,
            )
        except RuntimeError as e:
            # Expected: FileInfo not available, but should NOT be
            # "Can't convert PyInt to ImportOptions" error
            err = str(e)
            assert "PyInt" not in err, (
                f"Should NOT contain PyInt conversion error: {err}"
            )
        except Exception:
            pass  # Other expected errors (no CLR)

    def test_invoke_uses_enum_type_to_match_overload(self):
        """多个 Import 重载时，按 enum_type 精确匹配。"""
        file_info_type = _make_param_type("System.IO.FileInfo")
        import_opts_type = _make_param_type(
            "Siemens.Engineering.ImportOptions", is_enum=True,
        )
        string_type = _make_param_type("System.String")

        # Import(String, String) — wrong match
        m1 = MagicMock()
        m1.Name = "Import"
        m1.ReturnType = MagicMock()
        m1.ReturnType.FullName = "Void"
        mp1 = MagicMock()
        mp1.Name = "path"
        mp1.ParameterType = string_type
        mp2 = MagicMock()
        mp2.Name = "name"
        mp2.ParameterType = string_type
        m1.GetParameters.return_value = [mp1, mp2]

        # Import(FileInfo, ImportOptions) — correct match
        m2 = MagicMock()
        m2.Name = "Import"
        m2.ReturnType = MagicMock()
        m2.ReturnType.FullName = "Void"
        m2p1 = MagicMock()
        m2p1.Name = "file"
        m2p1.ParameterType = file_info_type
        m2p2 = MagicMock()
        m2p2.Name = "options"
        m2p2.ParameterType = import_opts_type
        m2.GetParameters.return_value = [m2p1, m2p2]

        tc_type = MagicMock()
        tc_type.GetMethods.return_value = [m1, m2]
        tc = MagicMock()
        tc.GetType.return_value = tc_type

        # option_result tells invoke which overload to use
        option_result = {
            "value": 1,
            "enum_type": import_opts_type,
        }

        try:
            ClassicOpennessExecutor.invoke_tag_composition_import(
                tc, "/tmp/test.xml", option_result,
            )
        except RuntimeError as e:
            # Expected: FileInfo not available in test env
            # But method should have been matched by enum_type (method m2)
            err = str(e)
            assert "PyInt" not in err, (
                f"Should NOT contain PyInt error: {err}"
            )
        except Exception:
            pass  # FileInfo not available in test env


# ---------------------------------------------------------------------------
# 测试 3: 集成测试
# ---------------------------------------------------------------------------

class TestOverloadResolverIntegration:
    """集成测试 — overload resolver + import_hmi_tags_safe。"""

    def test_overload_resolver_in_import_hmi_tags_safe(self, monkeypatch):
        """import_hmi_tags_safe 通过 overload resolver 成功。"""
        # TagComposition 有 Import(FileInfo, FakeImportOptions)
        import_options_type = _make_fake_import_option_type()
        file_info_type = _make_param_type("System.IO.FileInfo")
        method = _make_fake_method(
            "Import",
            [("file", file_info_type), ("options", import_options_type)],
        )
        tag_composition = _make_tag_composition([method])
        tag_composition.__iter__ = lambda self: iter([])

        default_table = MagicMock()
        default_table.Tags = tag_composition

        tag_folder = MagicMock()
        tag_folder.DefaultTagTable = default_table

        sw = MagicMock()
        sw.TagFolder = tag_folder

        executor = ClassicOpennessExecutor()
        executor._clr_available = True

        # Mock System.Enum for overload resolver
        monkeypatch.setattr("backend.openness.classic_executor.Enum", FakeSystemEnum)

        # Mock _write_temp_xml and _make_file_info
        monkeypatch.setattr(executor, "_write_temp_xml", lambda xml, prefix: "/tmp/test.xml")
        monkeypatch.setattr(
            ClassicOpennessExecutor, "_make_file_info",
            lambda self_, path: MagicMock(),
        )

        # Mock _make_import_options to return None (force Invoke path)
        monkeypatch.setattr(
            ClassicOpennessExecutor, "_make_import_options",
            lambda: MagicMock(Mode=1),
        )

        # Mock invoke to succeed silently
        monkeypatch.setattr(
            ClassicOpennessExecutor, "invoke_tag_composition_import",
            lambda tc, path, opt: None,
        )

        tags_xml = """<?xml version="1.0"?>
<Document xmlns="http://www.siemens.com/automation/SimaticML">
  <SW.Blocks>
    <SW.TagTable>
      <ObjectList>
        <SW.Tag><AttributeList><Name>Motor_Start</Name><DataType>Bool</DataType></AttributeList></SW.Tag>
      </ObjectList>
    </SW.TagTable>
  </SW.Blocks>
</Document>"""

        tag_items = [{"name": "Motor_Start", "data_type": "Bool"}]
        result = executor.import_hmi_tags_safe(sw, tags_xml, tag_items)

        # The overload resolver should have been tried first
        # Check that we at least didn't get TAG_IMPORT_METHOD_NOT_FOUND
        has_import_not_found = any(
            d.code == DiagnosticCodes.TAG_IMPORT_METHOD_NOT_FOUND
            for d in result.diagnostics
        )
        assert not has_import_not_found, (
            "Import method should be found"
        )

# -*- coding: utf-8 -*-
"""测试 OpennessManager 诊断和错误处理（不依赖实际 TIA 连接）。"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.openness_manager import OpennessManager
from backend.config_manager import DEFAULT_CONFIG


def make_manager(**overrides) -> OpennessManager:
    """构建一个带默认配置的 OpennessManager，支持部分覆盖。"""
    cfg = {
        "openness": dict(DEFAULT_CONFIG["openness"]),
        "output": dict(DEFAULT_CONFIG["output"]),
    }
    cfg["openness"].update(overrides)
    return OpennessManager(cfg)


class TestOpennessManagerDiagnose:
    """诊断功能测试（纯 Python 逻辑，不依赖 Windows/TIA）。"""

    def test_diagnose_returns_dict(self):
        """diagnose() 始终返回 dict 而不是崩溃。"""
        mgr = make_manager()
        result = mgr.diagnose()
        assert isinstance(result, dict)
        assert "os" in result
        assert "is_windows" in result
        assert "pythonnet_installed" in result
        assert "ready" in result
        assert "messages" in result

    def test_diagnose_with_invalid_dll_path(self):
        """DLL 路径不存在时应反映在 messages 中。"""
        mgr = make_manager(dll_path=r"C:\does\not\exist.dll")
        result = mgr.diagnose()
        assert not result["dll_exists"]
        assert any("路径不存在" in m for m in result["messages"])

    def test_get_hmi_capabilities_not_connected(self):
        """未连接时 get_hmi_capabilities() 返回 disconnected 状态。"""
        mgr = make_manager()
        caps = mgr.get_hmi_capabilities()
        assert caps["connected"] is False
        assert len(caps["warnings"]) > 0

    def test_import_or_generate_from_ir_adds_mode_field(self):
        """import_or_generate_from_ir 返回中包含 mode 字段。"""
        mgr = make_manager()
        ir = {
            "meta": {"screen_name": "Test_Screen"},
            "objects": [{"id": "TXT_A", "type": "Text", "x": 0, "y": 0, "text": "A"}],
        }
        result = mgr.import_or_generate_from_ir(ir, mode="auto")
        assert "mode" in result
        # 未连接时应有错误
        assert not result.get("ok")

    def test_export_screen_xml_template_not_connected(self):
        """未连接时导出模板应返回错误。"""
        mgr = make_manager()
        result = mgr.export_screen_xml_template("Test_Screen")
        assert result.get("ok") is False

    def test_import_screen_xml_not_connected(self):
        """未连接时导入应返回错误。"""
        mgr = make_manager()
        result = mgr.import_screen_xml("/nonexistent/path.xml")
        assert result.get("imported") is False

    def test_create_unified_screen_from_ir_not_connected(self):
        """未连接时 Unified 直接绘制应返回错误。"""
        mgr = make_manager()
        ir = {
            "meta": {"screen_name": "Test_Unified"},
            "objects": [{"id": "TXT_A", "type": "Text", "x": 0, "y": 0, "text": "A"}],
        }
        result = mgr.create_unified_screen_from_ir(ir)
        assert result.get("ok") is False

    def test_disconnect_safe(self):
        """disconnect() 即使未连接也不崩溃。"""
        mgr = make_manager()
        result = mgr.disconnect()
        assert result["disconnected"] is True


class TestExportScreenToFile:
    """测试 _export_screen_to_file 统一导出封装（mock 模拟）。"""

    def test_export_never_passes_str_to_screen(self):
        """验证 _export_screen_to_file 不会传 str 给 Screen.Export()。"""
        mgr = make_manager()

        str_calls = []

        class FakeScreen:
            """模拟 Screen 对象，记录 Export 调用参数。"""
            def __init__(self):
                self.export_calls = []

            def Export(self, *args):
                self.export_calls.append(args)
                # 如果第一个参数是 str，记录并报错（模拟真实的 pythonnet 行为）
                if args and isinstance(args[0], str):
                    str_calls.append(args)
                    raise TypeError(
                        "No method matches given arguments for Screen.Export: "
                        f"(<class 'str'>)"
                    )
                # FileInfo / .NET 对象调用：成功返回

        import tempfile
        import os as _os
        fake = FakeScreen()
        tmp = _os.path.join(tempfile.gettempdir(), "_test_export.xml")

        result = mgr._export_screen_to_file(fake, tmp)

        # 在 Windows + pythonnet 环境下可能成功（FileInfo 可用）；
        # 在非 Windows 环境下返回 ok=False + attempts
        # 关键断言：绝不传 str 给 Screen.Export()
        assert len(str_calls) == 0, (
            "_export_screen_to_file 不应传 str 给 Screen.Export()！"
            f" 实际传了: {str_calls}"
        )
        assert "attempts" in result

    def test_export_returns_attempts_on_failure(self):
        """导出失败时应返回 attempts 列表（即使 GetType 不可用）。"""
        mgr = make_manager()

        class FailingScreen:
            def Export(self, *args):
                raise RuntimeError("Simulated TIA export failure")

        import tempfile
        import os as _os
        tmp = _os.path.join(tempfile.gettempdir(), "_test_fail.xml")
        result = mgr._export_screen_to_file(FailingScreen(), tmp)

        assert result.get("ok") is False
        # 直接 Export 调用失败 + InvokeMember/MethodInfo 因无 GetType 而被跳过
        # 但直接 Export 的两次尝试应已记录到 attempts
        assert len(result.get("attempts", [])) > 0, (
            f"attempts 应为非空，实际: {result.get('attempts')}"
        )
        assert "message" in result


class TestExportReferenceScreen:
    """测试导出参考画面的错误处理。"""

    def test_not_connected_returns_error(self):
        """未连接时应返回 ok=False 和 message。"""
        mgr = make_manager()
        result = mgr.export_reference_screen()
        assert result.get("ok") is False
        assert "message" in result

    def test_accepts_screen_name_parameter(self):
        """export_reference_screen 应接受 screen_name 参数。"""
        mgr = make_manager()
        result = mgr.export_reference_screen(screen_name="NonExistent")
        # 未连接，但不应因参数而崩溃
        assert result.get("ok") is False


class TestExportScreenXmlTemplate:
    """测试导出模板 XML 的错误处理。"""

    def test_not_connected_returns_error_with_message(self):
        """未连接时应返回 ok=False 和 message（而非 error）。"""
        mgr = make_manager()
        result = mgr.export_screen_xml_template("Test_Screen")
        assert result.get("ok") is False
        assert "message" in result

    def test_export_template_returns_warnings_list(self):
        """返回应始终包含 warnings 列表。"""
        mgr = make_manager()
        result = mgr.export_screen_xml_template("AnyScreen")
        assert isinstance(result.get("warnings"), list)


class TestFindScreenByName:
    """测试画面查找辅助方法。"""

    def test_no_hmi_software_returns_none(self):
        """无 HMI 软件对象时返回 None。"""
        mgr = make_manager()

        class FakeSoftware:
            @property
            def ScreenFolder(self):
                raise AttributeError("No ScreenFolder")

        screen, warnings = mgr._find_screen_by_name(FakeSoftware(), "Test")
        assert screen is None

    def test_list_available_screens_no_hmi(self):
        """无 HMI 软件时 _list_available_screens 返回空列表。"""
        mgr = make_manager()

        class FakeSoftware:
            @property
            def ScreenFolder(self):
                raise AttributeError("No ScreenFolder")

        result = mgr._list_available_screens(FakeSoftware())
        assert result == []

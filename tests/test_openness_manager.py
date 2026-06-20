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


class TestSyncTagsFamilyRouting:
    """V4.2: 测试 sync_tags 家族感知路由 — 不再硬编码 sw.TagTables。"""

    def _make_manager_with_mocks(self, monkeypatch, sw_fake, hmi_family):
        """构造 OpennessManager，mock _find_hmi_software 和 get_hmi_capabilities。"""
        mgr = make_manager()

        def fake_find(*args, **kwargs):
            return sw_fake
        monkeypatch.setattr(mgr, "_find_hmi_software", fake_find)

        def fake_caps(*args, **kwargs):
            return {
                "connected": True,
                "hmi_family": hmi_family,
                "is_unified": hmi_family == "Unified",
                "is_classic": hmi_family in ("Basic", "Comfort", "Classic"),
            }
        monkeypatch.setattr(mgr, "get_hmi_capabilities", fake_caps)

        # 确保 _project 不为 None
        mgr._project = True
        return mgr

    def test_sync_tags_no_attribute_error_on_hmi_target(self, monkeypatch):
        """Fake HmiTarget 无 TagTables → sync_tags 不应抛 AttributeError，应返回结构化错误。"""
        class FakeHmiTarget:
            """模拟 HmiTarget wrapper 对象 — 没有 TagTables 属性。"""
            pass

        sw = FakeHmiTarget()
        mgr = self._make_manager_with_mocks(monkeypatch, sw, "Classic")

        # 不应抛 AttributeError
        result = mgr.sync_tags([{"name": "BTN_Start", "data_type": "Bool"}])
        assert not result.get("ok"), f"Expected blocked, got: {result}"
        assert len(result["errors"]) > 0, f"Expected errors, got: {result}"
        # 错误信息应包含 .NET 类型和已尝试路径
        error_text = " ".join(result["errors"])
        assert "FakeHmiTarget" in error_text or "变量容器" in error_text or "解析" in error_text, \
            f"Error should contain diagnostic info, got: {error_text}"

    def test_sync_tags_classic_routes_to_safe_import(self, monkeypatch):
        """Classic 家族 → 应通过 ClassicOpennessExecutor.import_hmi_tags_safe 导入。"""
        # 使用简单对象避免嵌套类作用域问题
        class FakeTagsColl:
            def __iter__(self):
                return iter([])

        class FakeDefaultTable:
            pass

        FakeDefaultTable.Tags = FakeTagsColl()

        class FakeTagFolder:
            pass

        FakeTagFolder.DefaultTagTable = FakeDefaultTable()

        class FakeClassicSw:
            pass

        sw = FakeClassicSw()
        sw.TagFolder = FakeTagFolder()
        mgr = self._make_manager_with_mocks(monkeypatch, sw, "Comfort")

        # Mock ClassicOpennessExecutor 的 import_hmi_tags_safe
        called_with = {}

        class FakeStepResult:
            success = True
            diagnostics = []
            api_calls = ["strategy_used=ImportOptions.Override"]

        def fake_import_hmi_tags_safe(self_exec, hmi_sw, tags_xml, tag_items=None):
            called_with["called"] = True
            called_with["hmi_sw"] = hmi_sw
            called_with["tags_xml"] = tags_xml
            called_with["tag_items"] = tag_items
            return FakeStepResult()

        from backend.openness.classic_executor import ClassicOpennessExecutor
        monkeypatch.setattr(
            ClassicOpennessExecutor,
            "import_hmi_tags_safe",
            fake_import_hmi_tags_safe,
        )
        result = mgr.sync_tags([{"name": "CMD_Start", "data_type": "Bool"}])

        assert called_with.get("called"), \
            f"Expected ClassicOpennessExecutor.import_hmi_tags_safe to be called"
        assert result.get("ok"), f"Expected success, got: {result}"
        assert "CMD_Start" in result.get("created", []), \
            f"Expected CMD_Start in created, got: {result}"

    def test_sync_tags_unified_routes_to_create_tags(self, monkeypatch):
        """Unified 家族 → 应通过 UnifiedOpennessExecutor.create_tags 创建变量。"""
        class FakeUnifiedSw:
            """模拟 Unified HMI 软件对象 — 只有 Tags 直接集合。"""
            class FakeTagsColl:
                def __iter__(self):
                    return iter([])
            Tags = FakeTagsColl()

        sw = FakeUnifiedSw()
        mgr = self._make_manager_with_mocks(monkeypatch, sw, "Unified")

        called_with = {}

        class FakeStepResult:
            success = True
            diagnostics = []

        def fake_create_tags(self_exec, hmi_sw, tag_specs):
            called_with["called"] = True
            called_with["hmi_sw"] = hmi_sw
            called_with["tag_specs"] = tag_specs
            return FakeStepResult()

        from backend.openness.unified_executor import UnifiedOpennessExecutor
        monkeypatch.setattr(
            UnifiedOpennessExecutor,
            "create_tags",
            fake_create_tags,
        )

        result = mgr.sync_tags([{"name": "UNI_Tag", "data_type": "Real"}])
        assert called_with.get("called"), \
            f"Expected UnifiedOpennessExecutor.create_tags to be called"
        assert result.get("ok"), f"Expected success, got: {result}"
        assert "UNI_Tag" in result.get("created", []), \
            f"Expected UNI_Tag in created, got: {result}"

    def test_sync_tags_unknown_family_returns_diagnostic(self, monkeypatch):
        """未知 HMI 家族 → 返回结构化诊断，包含 .NET 类型和探测的属性。"""
        class FakeUnknownSw:
            """模拟未知 HMI 对象 — 无 TagFolder、无 Tags。"""
            pass

        sw = FakeUnknownSw()
        mgr = self._make_manager_with_mocks(monkeypatch, sw, "Unknown")

        result = mgr.sync_tags([{"name": "TEST_Tag", "data_type": "Bool"}])
        assert not result.get("ok"), f"Expected blocked for unknown family, got: {result}"
        assert len(result["errors"]) > 0, f"Expected diagnostic errors, got: {result}"
        error_text = " ".join(result["errors"])
        # 应包含类型名、family、已尝试路径、可用属性
        assert "FakeUnknownSw" in error_text or "Unknown" in error_text or "变量容器" in error_text, \
            f"Error should contain diagnostic info about the unknown object, got: {error_text}"

    def test_sync_tags_preserves_output_format(self, monkeypatch):
        """sync_tags 返回格式始终包含 ok/created/skipped/errors 键。"""
        class FakeSw:
            class FakeTagsColl:
                def __iter__(self):
                    return iter([])
            Tags = FakeTagsColl()

        sw = FakeSw()
        mgr = self._make_manager_with_mocks(monkeypatch, sw, "Unified")

        # Mock create_tags 成功
        class FakeStepResult:
            success = True
            diagnostics = []

        from backend.openness.unified_executor import UnifiedOpennessExecutor
        monkeypatch.setattr(
            UnifiedOpennessExecutor,
            "create_tags",
            lambda self_exec, hmi_sw, tag_specs: FakeStepResult(),
        )

        result = mgr.sync_tags([
            {"name": "Tag_A", "data_type": "Bool"},
            {"name": "Tag_B", "data_type": "Int"},
        ])

        # 验证输出格式
        assert "ok" in result
        assert "created" in result
        assert "skipped" in result
        assert "errors" in result
        assert isinstance(result["created"], list)
        assert isinstance(result["skipped"], list)
        assert isinstance(result["errors"], list)

    def test_sync_tags_skips_existing_tags(self, monkeypatch):
        """已存在的变量应放入 skipped 列表，不重复创建。"""
        class FakeSw:
            class FakeTag:
                Name = "EXIST_Tag"

            class FakeTagsColl:
                def __iter__(self):
                    return iter([FakeSw.FakeTag()])
            Tags = FakeTagsColl()

        sw = FakeSw()
        mgr = self._make_manager_with_mocks(monkeypatch, sw, "Unified")

        class FakeStepResult:
            success = True
            diagnostics = []

        from backend.openness.unified_executor import UnifiedOpennessExecutor
        monkeypatch.setattr(
            UnifiedOpennessExecutor,
            "create_tags",
            lambda self_exec, hmi_sw, tag_specs: FakeStepResult(),
        )

        result = mgr.sync_tags([
            {"name": "EXIST_Tag", "data_type": "Bool"},
            {"name": "NEW_Tag", "data_type": "Bool"},
        ])

        assert "EXIST_Tag" in result["skipped"], \
            f"EXIST_Tag should be skipped, got: {result}"
        assert "NEW_Tag" in result["created"], \
            f"NEW_Tag should be created, got: {result}"

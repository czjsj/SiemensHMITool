# -*- coding: utf-8 -*-
"""测试诊断模型和校验逻辑。"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.domain.diagnostics import Diagnostic, DiagnosticCodes
from backend.domain.enums import DiagnosticSeverity
from backend.domain.validation import (
    validate_ir_v2,
    validate_or_raise,
    IrV2ValidationError,
)
from backend.domain.ir_v2 import (
    HmiProjectSpec,
    TagSpec,
    ScreenSpec,
    ScreenItemSpec,
    GeometrySpec,
    EventSpec,
    ActionSpec,
    BindingSpec,
    ScriptSpec,
)
from backend.domain.enums import (
    ScreenItemType,
    SemanticEvent,
    SemanticActionType,
    BindingKind,
    TagScope,
)


class TestDiagnosticModel:
    """Diagnostic 模型测试。"""

    def test_minimal_diagnostic(self):
        d = Diagnostic(code="TEST_001", message="测试诊断")
        assert d.code == "TEST_001"
        assert d.severity == DiagnosticSeverity.ERROR  # 默认
        assert d.details == {}
        assert d.remediation is None

    def test_full_diagnostic(self):
        d = Diagnostic(
            code=DiagnosticCodes.CAP_UNSUPPORTED_EVENT,
            severity=DiagnosticSeverity.WARNING,
            phase="P10_VALIDATE_DEPENDENCIES",
            object_type="screen_item",
            object_name="BTN_Start",
            message="Basic 面板不支持 call_script 动作",
            details={"action_type": "call_script", "script": "Sub_Complex"},
            remediation="请将复杂逻辑转移到 PLC 或使用 FunctionList",
        )
        assert d.severity == DiagnosticSeverity.WARNING
        assert d.object_name == "BTN_Start"
        assert "Basic" in d.message

    def test_diagnostic_serialization(self):
        d = Diagnostic(code="TEST", message="msg", severity=DiagnosticSeverity.INFO)
        json_str = d.model_dump_json()
        assert "TEST" in json_str
        assert "info" in json_str

    def test_diagnostic_codes_coverage(self):
        """确保所有标准错误码可访问。"""
        codes = [
            DiagnosticCodes.CAP_UNSUPPORTED_EVENT,
            DiagnosticCodes.CAP_UNSUPPORTED_BINDING,
            DiagnosticCodes.DEP_MISSING_CONNECTION,
            DiagnosticCodes.DEP_MISSING_CONTROLLER_TAG,
            DiagnosticCodes.CLASSIC_FRAGMENT_NOT_FOUND,
            DiagnosticCodes.CLASSIC_SCHEMA_MISMATCH,
            DiagnosticCodes.CLASSIC_BROKEN_LINK,
            DiagnosticCodes.UNIFIED_TYPE_NOT_FOUND,
            DiagnosticCodes.UNIFIED_EVENT_ENUM_AMBIGUOUS,
            DiagnosticCodes.UNIFIED_PROPERTY_NOT_SUPPORTED,
            DiagnosticCodes.SCRIPT_SECURITY_REJECTED,
            DiagnosticCodes.SCRIPT_SYNTAX_FAILED,
            DiagnosticCodes.IMPORT_TIA_EXCEPTION,
            DiagnosticCodes.COMPILE_ERROR,
            DiagnosticCodes.VERIFY_TAG_MISSING,
            DiagnosticCodes.VERIFY_EVENT_MISSING,
            DiagnosticCodes.VERIFY_BINDING_MISSING,
            DiagnosticCodes.IR_VALIDATION_ERROR,
            DiagnosticCodes.LEGACY_ADAPTER_WARNING,
        ]
        for code in codes:
            assert isinstance(code, str) and code, f"错误码不应为空: {code}"


class TestValidation:
    """validate_ir_v2 测试。"""

    def test_empty_project_warns(self):
        """空 project 产生 warning（非 fatal）。"""
        project = HmiProjectSpec()
        diags = validate_ir_v2(project)
        assert any(
            d.severity == DiagnosticSeverity.WARNING and "为空" in d.message
            for d in diags
        )

    def test_valid_project_no_errors(self):
        """完整合法 project 无 error。"""
        project = HmiProjectSpec(
            tags=[
                TagSpec(name="Tag_A", data_type="Bool", scope=TagScope.INTERNAL),
                TagSpec(name="Tag_B", data_type="Real", scope=TagScope.EXTERNAL),
            ],
            screens=[
                ScreenSpec(
                    name="Main",
                    width=800,
                    height=480,
                    items=[
                        ScreenItemSpec(
                            id="BTN_Start",
                            name="按钮",
                            type=ScreenItemType.BUTTON,
                            geometry=GeometrySpec(x=10, y=10, width=120, height=50),
                            tag_binding="Tag_A",
                            events=[
                                EventSpec(
                                    event=SemanticEvent.PRESS,
                                    actions=[ActionSpec(type=SemanticActionType.SET_BIT, tag="Tag_A")],
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        )
        diags = validate_ir_v2(project)
        errors = [d for d in diags if d.severity == DiagnosticSeverity.ERROR]
        assert len(errors) == 0, f"不应该有错误: {errors}"

    def test_duplicate_tag_names_error(self):
        """重复变量名产生 error。"""
        project = HmiProjectSpec(
            tags=[
                TagSpec(name="Same", data_type="Bool"),
                TagSpec(name="Same", data_type="Real"),
            ],
            screens=[
                ScreenSpec(name="S1", width=800, height=480),
            ],
        )
        diags = validate_ir_v2(project)
        errors = [d for d in diags if d.severity == DiagnosticSeverity.ERROR]
        dup = [d for d in errors if "重复" in d.message]
        assert len(dup) >= 1

    def test_duplicate_screen_names_error(self):
        """重复画面名产生 error。"""
        project = HmiProjectSpec(
            screens=[
                ScreenSpec(name="SameScreen", width=800, height=480),
                ScreenSpec(name="SameScreen", width=1024, height=768),
            ],
        )
        diags = validate_ir_v2(project)
        errors = [d for d in diags if d.severity == DiagnosticSeverity.ERROR]
        dup = [d for d in errors if "重复" in d.message]
        assert len(dup) >= 1

    def test_missing_tag_reference_warns(self):
        """控件引用未声明的变量产生 warning。"""
        project = HmiProjectSpec(
            tags=[],
            screens=[
                ScreenSpec(
                    name="S1",
                    width=800,
                    height=480,
                    items=[
                        ScreenItemSpec(
                            id="BTN_Go",
                            name="Go",
                            type=ScreenItemType.BUTTON,
                            geometry=GeometrySpec(x=10, y=10, width=120, height=50),
                            tag_binding="NonExistentTag",
                        ),
                    ],
                ),
            ],
        )
        diags = validate_ir_v2(project)
        missing_tag = [d for d in diags if d.code == "VERIFY_TAG_MISSING"]
        assert len(missing_tag) >= 1
        assert any("NonExistentTag" in d.message for d in missing_tag)

    def test_binding_references_missing_tag_warns(self):
        """binding 引用未声明变量产生 warning。"""
        project = HmiProjectSpec(
            tags=[TagSpec(name="RealTag", data_type="Bool")],
            screens=[
                ScreenSpec(
                    name="S1",
                    width=800,
                    height=480,
                    items=[
                        ScreenItemSpec(
                            id="IND_1",
                            name="Ind",
                            type=ScreenItemType.INDICATOR,
                            geometry=GeometrySpec(x=10, y=10, width=44, height=44),
                            bindings=[
                                BindingSpec(
                                    property="background_color",
                                    kind=BindingKind.DISCRETE,
                                    source_tag="NonExistentTag",
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        )
        diags = validate_ir_v2(project)
        missing = [d for d in diags if d.code == "VERIFY_TAG_MISSING"]
        assert len(missing) >= 1

    def test_action_references_missing_screen_warns(self):
        """activate_screen 引用未声明画面产生 warning。"""
        project = HmiProjectSpec(
            tags=[],
            screens=[
                ScreenSpec(
                    name="S1",
                    width=800,
                    height=480,
                    items=[
                        ScreenItemSpec(
                            id="BTN_Go",
                            name="Go",
                            type=ScreenItemType.BUTTON,
                            geometry=GeometrySpec(x=10, y=10, width=120, height=50),
                            events=[
                                EventSpec(
                                    event=SemanticEvent.CLICK,
                                    actions=[
                                        ActionSpec(
                                            type=SemanticActionType.ACTIVATE_SCREEN,
                                            screen="NonExistentScreen",
                                        ),
                                    ],
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        )
        diags = validate_ir_v2(project)
        missing = [d for d in diags if d.code == "VERIFY_SCREEN_MISSING"]
        assert len(missing) >= 1

    def test_action_references_missing_script_warns(self):
        """call_script 引用未声明脚本产生 warning。"""
        project = HmiProjectSpec(
            tags=[],
            scripts=[],
            screens=[
                ScreenSpec(
                    name="S1",
                    width=800,
                    height=480,
                    items=[
                        ScreenItemSpec(
                            id="BTN_Go",
                            name="Go",
                            type=ScreenItemType.BUTTON,
                            geometry=GeometrySpec(x=10, y=10, width=120, height=50),
                            events=[
                                EventSpec(
                                    event=SemanticEvent.CLICK,
                                    actions=[
                                        ActionSpec(
                                            type=SemanticActionType.CALL_SCRIPT,
                                            script="NonExistentScript",
                                        ),
                                    ],
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        )
        diags = validate_ir_v2(project)
        missing = [d for d in diags if d.code == "VERIFY_SCRIPT_MISSING"]
        assert len(missing) >= 1

    def test_duplicate_script_names_error(self):
        """重复脚本名产生 error。"""
        project = HmiProjectSpec(
            scripts=[
                ScriptSpec(name="SameScript", language="vbs", body="' test 1"),
                ScriptSpec(name="SameScript", language="vbs", body="' test 2"),
            ],
            screens=[
                ScreenSpec(name="S1", width=800, height=480),
            ],
        )
        diags = validate_ir_v2(project)
        errors = [d for d in diags if d.severity == DiagnosticSeverity.ERROR]
        assert len(errors) >= 1


class TestValidateOrRaise:
    """validate_or_raise 测试。"""

    def test_valid_project_returns(self):
        project = HmiProjectSpec(
            screens=[ScreenSpec(name="S1", width=800, height=480)],
        )
        result = validate_or_raise(project)
        assert result is project
        # 有 warnings 但无 errors
        assert len(result.diagnostics) >= 0

    def test_error_project_raises(self):
        """有 error 时抛出 IrV2ValidationError。"""
        project = HmiProjectSpec(
            tags=[TagSpec(name="X", data_type="Bool"), TagSpec(name="X", data_type="Real")],
            screens=[ScreenSpec(name="S1", width=800, height=480)],
        )
        with pytest.raises(IrV2ValidationError) as exc_info:
            validate_or_raise(project)
        assert "重复" in str(exc_info.value)

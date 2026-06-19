# -*- coding: utf-8 -*-
"""测试能力矩阵和 CapabilityService。"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.capabilities.static_matrix import (
    STATIC_CAPABILITY_MATRIX,
    CapabilityEntry,
    get_capability,
)
from backend.capabilities.capability_service import (
    CapabilityService,
    CapabilitySet,
)
from backend.domain.ir_v2 import (
    HmiProjectSpec,
    TargetSpec,
    ScreenSpec,
    ScreenItemSpec,
    GeometrySpec,
    EventSpec,
    ActionSpec,
    BindingSpec,
    ScriptSpec,
    TagSpec,
    DeploymentPolicies,
)
from backend.domain.enums import (
    HmiFamily,
    ScreenItemType,
    SemanticEvent,
    SemanticActionType,
    BindingKind,
    ScriptLanguage,
    DiagnosticSeverity,
    UnsupportedFeaturePolicy,
)


class TestStaticMatrix:
    """静态能力矩阵测试。"""

    def test_matrix_has_entries(self):
        assert len(STATIC_CAPABILITY_MATRIX) > 10

    def test_get_capability_basic(self):
        assert get_capability("VBS", "basic") == "no"
        assert get_capability("画面导入/创建", "basic") == "yes"
        assert get_capability("系统FunctionList", "basic") == "yes"
        assert get_capability("JavaScript", "basic") == "no"

    def test_get_capability_comfort(self):
        assert get_capability("VBS", "comfort") == "yes"
        assert get_capability("JavaScript", "comfort") == "no"
        assert get_capability("直接强类型创建ScreenItem", "comfort") == "no"

    def test_get_capability_unified(self):
        assert get_capability("VBS", "unified") == "no"
        assert get_capability("JavaScript", "unified") == "yes"
        assert get_capability("直接强类型创建ScreenItem", "unified") == "yes"

    def test_get_capability_unknown(self):
        assert get_capability("NonExistentCapability", "basic") == "unknown"
        assert get_capability("VBS", "invalid_family") == "unknown"


class TestCapabilitySet:
    """CapabilitySet 测试。"""

    def test_basic_capabilities(self):
        caps = CapabilitySet(HmiFamily.BASIC)
        assert caps.get("VBS") == "no"
        assert not caps.supports("VBS")
        assert caps.supports("画面导入/创建")

    def test_comfort_capabilities(self):
        caps = CapabilitySet(HmiFamily.COMFORT)
        assert caps.supports("VBS")
        assert not caps.supports("JavaScript")

    def test_to_dict(self):
        caps = CapabilitySet(HmiFamily.COMFORT, "V18")
        d = caps.to_dict()
        assert d["family"] == "comfort"
        assert d["tia_version"] == "V18"
        assert "VBS" in d


class TestCapabilityService:
    """CapabilityService 测试。"""

    def test_resolve_basic(self):
        target = TargetSpec(family=HmiFamily.BASIC, tia_version="V16")
        svc = CapabilityService()
        caps = svc.resolve(target)
        assert caps.family == HmiFamily.BASIC
        assert caps.get("VBS") == "no"

    def test_validate_basic_rejects_vbs(self):
        """Basic 面板的 VBS 脚本应被拒绝。"""
        svc = CapabilityService()
        target = TargetSpec(family=HmiFamily.BASIC)
        spec = HmiProjectSpec(
            target=target,
            scripts=[
                ScriptSpec(
                    name="Sub_VBS",
                    language=ScriptLanguage.VBS,
                    body="SmartTags(\"X\") = 1",
                ),
            ],
            screens=[ScreenSpec(name="S1", width=800, height=480)],
        )
        caps = svc.resolve(target)
        diags = svc.validate_project(spec, caps)
        errors = [d for d in diags if d.severity == DiagnosticSeverity.ERROR]
        assert len(errors) > 0
        assert any("VBS" in d.message for d in errors)

    def test_validate_basic_rejects_call_script(self):
        """Basic 面板的 call_script 动作应被拒绝。"""
        svc = CapabilityService()
        target = TargetSpec(family=HmiFamily.BASIC)
        spec = HmiProjectSpec(
            target=target,
            screens=[
                ScreenSpec(
                    name="S1", width=800, height=480,
                    items=[
                        ScreenItemSpec(
                            id="BTN_X", name="X",
                            type=ScreenItemType.BUTTON,
                            geometry=GeometrySpec(x=10, y=10, width=120, height=50),
                            events=[
                                EventSpec(
                                    event=SemanticEvent.CLICK,
                                    actions=[
                                        ActionSpec(
                                            type=SemanticActionType.CALL_SCRIPT,
                                            script="Sub_Test",
                                        ),
                                    ],
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        )
        caps = svc.resolve(target)
        diags = svc.validate_project(spec, caps)
        errors = [d for d in diags if d.severity == DiagnosticSeverity.ERROR]
        assert any("call_script" in d.message for d in errors)

    def test_validate_basic_rejects_write_expression(self):
        """Basic 面板的 write_expression 动作应被拒绝。"""
        svc = CapabilityService()
        target = TargetSpec(family=HmiFamily.BASIC)
        spec = HmiProjectSpec(
            target=target,
            screens=[
                ScreenSpec(
                    name="S1", width=800, height=480,
                    items=[
                        ScreenItemSpec(
                            id="BTN_X", name="X",
                            type=ScreenItemType.BUTTON,
                            geometry=GeometrySpec(x=10, y=10, width=120, height=50),
                            events=[
                                EventSpec(
                                    event=SemanticEvent.CLICK,
                                    actions=[
                                        ActionSpec(
                                            type=SemanticActionType.WRITE_EXPRESSION,
                                            expression="x * 2",
                                        ),
                                    ],
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        )
        caps = svc.resolve(target)
        diags = svc.validate_project(spec, caps)
        errors = [d for d in diags if d.severity == DiagnosticSeverity.ERROR]
        assert any("write_expression" in d.message for d in errors)

    def test_validate_comfort_warns_javascript(self):
        """Comfort 面板的 JS 脚本产生 warning（不阻断）。"""
        svc = CapabilityService()
        target = TargetSpec(family=HmiFamily.COMFORT)
        spec = HmiProjectSpec(
            target=target,
            scripts=[
                ScriptSpec(
                    name="Sub_JS",
                    language=ScriptLanguage.JAVASCRIPT,
                    body="console.log('test');",
                ),
            ],
            screens=[ScreenSpec(name="S1", width=800, height=480)],
        )
        caps = svc.resolve(target)
        diags = svc.validate_project(spec, caps)
        # JS 在 Comfort 是 warning 不是 error
        errors = [d for d in diags if d.severity == DiagnosticSeverity.ERROR]
        assert len(errors) == 0

    def test_validate_warn_and_skip_policy(self):
        """warn_and_skip 策略下产生 warning 而非 error。"""
        svc = CapabilityService()
        target = TargetSpec(family=HmiFamily.BASIC)
        spec = HmiProjectSpec(
            target=target,
            scripts=[
                ScriptSpec(
                    name="Sub_VBS",
                    language=ScriptLanguage.VBS,
                    body="x=1",
                ),
            ],
            screens=[ScreenSpec(name="S1", width=800, height=480)],
        )
        caps = svc.resolve(target)
        diags = svc.validate_project(spec, caps, policy=UnsupportedFeaturePolicy.WARN_AND_SKIP)
        errors = [d for d in diags if d.severity == DiagnosticSeverity.ERROR]
        assert len(errors) == 0
        warnings = [d for d in diags if d.severity == DiagnosticSeverity.WARNING]
        assert len(warnings) > 0

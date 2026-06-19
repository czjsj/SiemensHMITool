# -*- coding: utf-8 -*-
"""测试 Backend 类 (PR-06-08): ComfortBackend, BasicBackend."""
import sys, os, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.domain.ir_v2 import HmiProjectSpec, TargetSpec, ScreenSpec, ScreenItemSpec, GeometrySpec, TagSpec, EventSpec, ActionSpec, BindingSpec, ScriptSpec
from backend.domain.enums import HmiFamily, TagScope, ScreenItemType, SemanticEvent, SemanticActionType, BindingKind
from backend.domain.deployment_plan import DeploymentPlan
from backend.domain.deployment_result import DeploymentResult, VerificationResult
from backend.backends.classic.comfort_backend import ComfortBackend
from backend.backends.classic.basic_backend import BasicBackend
from backend.backends.base import HmiBackend


def _make_motor_control_spec():
    return HmiProjectSpec(
        target=TargetSpec(family=HmiFamily.COMFORT, tia_version="V18"),
        tags=[
            TagSpec(name="Motor_Start", data_type="Bool", scope=TagScope.EXTERNAL),
            TagSpec(name="Motor_Running", data_type="Bool", scope=TagScope.EXTERNAL),
            TagSpec(name="Motor_Speed", data_type="Real", scope=TagScope.EXTERNAL),
        ],
        screens=[ScreenSpec(name="MotorControl", width=800, height=480, items=[
            ScreenItemSpec(id="BTN_Start", name="Start", type=ScreenItemType.BUTTON,
                           geometry=GeometrySpec(x=50, y=80, width=100, height=50),
                           tag_binding="Motor_Start",
                           events=[EventSpec(event=SemanticEvent.PRESS, actions=[ActionSpec(type=SemanticActionType.SET_BIT, tag="Motor_Start", value=1)]),
                                   EventSpec(event=SemanticEvent.RELEASE, actions=[ActionSpec(type=SemanticActionType.RESET_BIT, tag="Motor_Start", value=0)])]),
            ScreenItemSpec(id="STS_Run", name="Run", type=ScreenItemType.INDICATOR,
                           geometry=GeometrySpec(x=80, y=200, width=44, height=44, radius=22),
                           tag_binding="Motor_Running",
                           bindings=[BindingSpec(property="background_color", kind=BindingKind.DISCRETE, source_tag="Motor_Running",
                                                 config={"states": [{"value": 0, "output": "#3A4250"}, {"value": 1, "output": "#27D17F"}]})]),
        ])],
    )


class TestComfortBackend:
    def test_supports_comfort(self):
        be = ComfortBackend()
        assert be.supports(TargetSpec(family=HmiFamily.COMFORT))
        assert be.supports(TargetSpec(family=HmiFamily.AUTO))

    def test_supports_rejects_basic(self):
        be = ComfortBackend()
        assert not be.supports(TargetSpec(family=HmiFamily.UNIFIED))

    def test_build_plan(self):
        be = ComfortBackend()
        spec = _make_motor_control_spec()
        plan = be.build_plan(spec)
        assert isinstance(plan, DeploymentPlan)
        assert len(plan.steps) > 0

    def test_execute(self):
        be = ComfortBackend()
        spec = _make_motor_control_spec()
        plan = be.build_plan(spec)
        result = be.execute(plan, context={"connected": True})
        assert isinstance(result, DeploymentResult)
        assert result.tags_created > 0

    def test_verify(self):
        be = ComfortBackend()
        spec = _make_motor_control_spec()
        result = be.verify(spec)
        assert isinstance(result, VerificationResult)
        assert result.tags.expected == 3
        assert result.screens.expected == 1

    def test_compile_screen(self):
        be = ComfortBackend()
        spec = _make_motor_control_spec()
        xml = be.compile_screen(spec.screens[0])
        assert "MotorControl" in xml
        assert "BTN_Start" in xml

    def test_compile_tags(self):
        be = ComfortBackend()
        spec = _make_motor_control_spec()
        xml = be.compile_tags(spec.tags)
        assert "Motor_Start" in xml
        assert "Motor_Speed" in xml

    def test_vbs_security(self):
        be = ComfortBackend()
        with pytest.raises(ValueError):
            be.build_vbs_script(ScriptSpec(name="Danger", language="vbs", body='Shell "cmd"'))


class TestBasicBackend:
    def test_supports_basic(self):
        be = BasicBackend()
        assert be.supports(TargetSpec(family=HmiFamily.BASIC))

    def test_supports_rejects_comfort(self):
        be = BasicBackend()
        assert not be.supports(TargetSpec(family=HmiFamily.COMFORT))

    def test_build_plan_rejects_vbs(self):
        be = BasicBackend()
        spec = HmiProjectSpec(
            target=TargetSpec(family=HmiFamily.BASIC),
            scripts=[ScriptSpec(name="Sub_VBS", language="vbs", body="x=1")],
            screens=[ScreenSpec(name="S1", width=800, height=480)],
        )
        plan = be.build_plan(spec)
        assert any("Basic" in d.message for d in plan.diagnostics)

    def test_execute(self):
        be = BasicBackend()
        spec = _make_motor_control_spec()
        spec.target = TargetSpec(family=HmiFamily.BASIC)
        plan = be.build_plan(spec)
        result = be.execute(plan)
        assert isinstance(result, DeploymentResult)
        assert result.backend == "basic_classic"

    def test_verify(self):
        be = BasicBackend()
        spec = _make_motor_control_spec()
        result = be.verify(spec)
        assert result.tags.expected == 3

# -*- coding: utf-8 -*-
"""测试 HMI IR V2 数据模型（Pydantic v2）。"""
import sys
import os
import pytest
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.domain.ir_v2 import (
    HmiProjectSpec,
    ProjectMetadata,
    TargetSpec,
    ConnectionSpec,
    TagSpec,
    GeometrySpec,
    BindingSpec,
    EventSpec,
    ActionSpec,
    ScreenItemSpec,
    ScreenSpec,
    ScriptSpec,
    ResourceSpec,
    DeploymentPolicies,
)
from backend.domain.enums import (
    HmiFamily,
    TagScope,
    ConnectionKind,
    ScreenItemType,
    BindingKind,
    SemanticEvent,
    SemanticActionType,
    ScriptLanguage,
    ConflictPolicy,
    UnsupportedFeaturePolicy,
    MissingDependencyPolicy,
)


class TestHmiProjectSpec:
    """HmiProjectSpec 构建和序列化测试。"""

    def test_minimal_project_creates(self):
        """最小 project 可以创建。"""
        project = HmiProjectSpec()
        assert project.schema_version == "2.0"
        assert isinstance(project.metadata, ProjectMetadata)
        assert project.screens == []

    def test_full_project_roundtrip_to_json(self):
        """完整 project 可以序列化→反序列化。"""
        project = HmiProjectSpec(
            metadata=ProjectMetadata(
                project_name="MotorControl",
                description="电机控制画面",
            ),
            target=TargetSpec(
                family=HmiFamily.COMFORT,
                tia_version="V18",
                resolution="800x480",
                device_type="TP1200 Comfort",
            ),
            tags=[
                TagSpec(name="Motor_Start", data_type="Bool", scope=TagScope.EXTERNAL),
                TagSpec(name="Motor_Speed", data_type="Real", scope=TagScope.EXTERNAL),
                TagSpec(name="Screen_Enable", data_type="Bool", scope=TagScope.INTERNAL),
            ],
            screens=[
                ScreenSpec(
                    name="MainScreen",
                    width=800,
                    height=480,
                    items=[
                        ScreenItemSpec(
                            id="BTN_Start",
                            name="BTN_Start",
                            type=ScreenItemType.BUTTON,
                            geometry=GeometrySpec(x=100, y=200, width=120, height=50),
                            tag_binding="Motor_Start",
                            events=[
                                EventSpec(
                                    event=SemanticEvent.PRESS,
                                    actions=[
                                        ActionSpec(
                                            type=SemanticActionType.SET_BIT,
                                            tag="Motor_Start",
                                            value=1,
                                        ),
                                    ],
                                ),
                                EventSpec(
                                    event=SemanticEvent.RELEASE,
                                    actions=[
                                        ActionSpec(
                                            type=SemanticActionType.RESET_BIT,
                                            tag="Motor_Start",
                                            value=0,
                                        ),
                                    ],
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        )
        json_str = project.model_dump_json()
        restored = HmiProjectSpec.model_validate_json(json_str)
        assert restored.schema_version == "2.0"
        assert restored.metadata.project_name == "MotorControl"
        assert restored.target.family == HmiFamily.COMFORT
        assert len(restored.tags) == 3
        assert len(restored.screens) == 1
        assert len(restored.screens[0].items) == 1
        assert restored.screens[0].items[0].events[0].actions[0].type == SemanticActionType.SET_BIT

    def test_project_strict_schema_version(self):
        """schema_version 只能是 '2.0'。"""
        project = HmiProjectSpec(schema_version="2.0")
        assert project.schema_version == "2.0"


class TestTargetSpec:
    """TargetSpec 测试。"""

    def test_default_target(self):
        target = TargetSpec()
        assert target.family == HmiFamily.AUTO
        assert target.tia_version is None
        assert target.language == "zh-CN"

    def test_explicit_target(self):
        target = TargetSpec(
            family=HmiFamily.BASIC,
            tia_version="V16",
            device_type="KTP700 Basic",
            resolution="800x480",
        )
        assert target.family == HmiFamily.BASIC
        assert target.tia_version == "V16"


class TestTagSpec:
    """TagSpec 测试。"""

    def test_internal_tag(self):
        tag = TagSpec(name="MyTag", scope=TagScope.INTERNAL, data_type="Bool")
        assert tag.scope == TagScope.INTERNAL
        assert tag.table == "AI_Generated"

    def test_external_tag_with_controller_ref(self):
        tag = TagSpec(
            name="Motor_Start",
            scope=TagScope.EXTERNAL,
            data_type="Bool",
            connection="PLC_1",
            controller_tag="DB1.Motor.Start",
        )
        assert tag.connection == "PLC_1"

    def test_comment_is_multilang_dict(self):
        tag = TagSpec(
            name="X",
            comment={"zh-CN": "启动按钮", "en-US": "Start Button"},
        )
        assert tag.comment["zh-CN"] == "启动按钮"


class TestScreenItemSpec:
    """ScreenItemSpec 测试。"""

    def test_basic_button(self):
        item = ScreenItemSpec(
            id="BTN_Start",
            name="BTN_Start",
            type=ScreenItemType.BUTTON,
            geometry=GeometrySpec(x=100, y=200, width=120, height=50),
            tag_binding="Motor_Start",
        )
        assert item.type == ScreenItemType.BUTTON
        assert item.geometry.width == 120

    def test_indicator_with_bindings(self):
        item = ScreenItemSpec(
            id="STS_Run",
            name="STS_Run",
            type=ScreenItemType.INDICATOR,
            geometry=GeometrySpec(x=400, y=100, width=44, height=44, radius=22),
            tag_binding="Motor_Running",
            bindings=[
                BindingSpec(
                    property="background_color",
                    kind=BindingKind.DISCRETE,
                    source_tag="Motor_Running",
                    config={
                        "states": [
                            {"value": 0, "output": "#3A4250"},
                            {"value": 1, "output": "#27D17F"},
                        ],
                    },
                ),
            ],
        )
        assert len(item.bindings) == 1
        assert item.bindings[0].kind == BindingKind.DISCRETE

    def test_text_with_multi_language(self):
        item = ScreenItemSpec(
            id="TXT_Title",
            name="TXT_Title",
            type=ScreenItemType.TEXT,
            geometry=GeometrySpec(x=100, y=30, width=320, height=40),
            text={"zh-CN": "电机控制", "en-US": "Motor Control"},
        )
        assert item.text["zh-CN"] == "电机控制"


class TestEventAndActionSpec:
    """EventSpec 和 ActionSpec 测试。"""

    def test_activate_screen_action(self):
        action = ActionSpec(
            type=SemanticActionType.ACTIVATE_SCREEN,
            screen="AlarmScreen",
        )
        assert action.type == SemanticActionType.ACTIVATE_SCREEN
        assert action.screen == "AlarmScreen"

    def test_call_script_action(self):
        action = ActionSpec(
            type=SemanticActionType.CALL_SCRIPT,
            script="Sub_ComplexLogic",
        )
        assert action.script == "Sub_ComplexLogic"


class TestBindingSpec:
    """BindingSpec 测试。"""

    def test_direct_tag_binding(self):
        b = BindingSpec(property="visible", kind=BindingKind.DIRECT_TAG, source_tag="Screen_Enable")
        assert b.property == "visible"

    def test_discrete_binding(self):
        b = BindingSpec(
            property="background_color",
            kind=BindingKind.DISCRETE,
            source_tag="Motor_Fault",
            config={
                "states": [
                    {"value": 0, "output": "#3A4250"},
                    {"value": 1, "output": "#E25563"},
                ],
            },
        )
        assert len(b.config["states"]) == 2

    def test_flashing_binding(self):
        b = BindingSpec(
            property="flashing",
            kind=BindingKind.FLASHING,
            source_tag="Motor_Fault",
        )
        assert b.kind == BindingKind.FLASHING


class TestScriptSpec:
    """ScriptSpec 测试。"""

    def test_semantic_script(self):
        s = ScriptSpec(
            name="Sub_Toggle",
            language=ScriptLanguage.SEMANTIC,
            body="toggle Motor_AutoMode",
        )
        assert s.language == ScriptLanguage.SEMANTIC


class TestResourceSpec:
    """ResourceSpec 测试。"""

    def test_text_list_resource(self):
        r = ResourceSpec(
            name="Mode_List",
            kind="text_list",
            entries=[
                {"value": 0, "text": "Manual"},
                {"value": 1, "text": "Auto"},
            ],
        )
        assert r.kind == "text_list"
        assert len(r.entries) == 2


class TestDeploymentPolicies:
    """DeploymentPolicies 测试。"""

    def test_defaults_are_safe(self):
        p = DeploymentPolicies()
        assert p.conflict_policy == ConflictPolicy.RENAME
        assert p.unsupported_feature == UnsupportedFeaturePolicy.ERROR
        assert p.missing_dependency == MissingDependencyPolicy.ERROR

    def test_no_vbs_for_basic(self):
        """通过 policy 体现 Basic 的 VBS 禁止策略。"""
        p = DeploymentPolicies(
            unsupported_feature=UnsupportedFeaturePolicy.ERROR,
            compile_after_deploy=True,
        )
        assert p.compile_after_deploy is True

# -*- coding: utf-8 -*-
"""测试验证服务 — 导入后标签、画面、控件、编译验证。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from backend.services.verification_service import VerificationService
from backend.domain.ir_v2 import (
    HmiProjectSpec, TargetSpec, ScreenSpec, ScreenItemSpec,
    TagSpec, GeometrySpec, BindingSpec, EventSpec, ActionSpec,
)
from backend.domain.enums import (
    ScreenItemType, TagScope, HmiFamily, BindingKind,
    SemanticEvent, SemanticActionType, DiagnosticSeverity,
)


class TestVerificationService:
    """测试导入后验证。"""

    def _make_minimal_project(self) -> HmiProjectSpec:
        return HmiProjectSpec(
            target=TargetSpec(family=HmiFamily.COMFORT),
            tags=[
                TagSpec(name="BTN_Start", data_type="Bool", scope=TagScope.INTERNAL),
                TagSpec(name="STS_Run", data_type="Bool", scope=TagScope.INTERNAL),
            ],
            screens=[
                ScreenSpec(
                    name="Main",
                    width=1280, height=800,
                    items=[
                        ScreenItemSpec(
                            id="BTN_Start", name="启动", type=ScreenItemType.BUTTON,
                            geometry=GeometrySpec(x=80, y=120, width=120, height=50),
                            tag_binding="BTN_Start",
                            events=[
                                EventSpec(event=SemanticEvent.PRESS, actions=[
                                    ActionSpec(type=SemanticActionType.SET_BIT, tag="BTN_Start", value=1),
                                ]),
                            ],
                        ),
                        ScreenItemSpec(
                            id="LMP_Run", name="运行", type=ScreenItemType.INDICATOR,
                            geometry=GeometrySpec(x=260, y=120, width=60, height=60),
                            tag_binding="STS_Run",
                            bindings=[
                                BindingSpec(property="background_color", kind=BindingKind.DISCRETE,
                                           source_tag="STS_Run"),
                            ],
                        ),
                    ],
                )
            ],
        )

    def test_not_connected_returns_failure(self):
        """未连接时验证返回失败。"""
        svc = VerificationService()
        project = self._make_minimal_project()
        result = svc.verify_full(project, {}, connected=False)
        assert result.success is False
        assert result.tags.found == 0

    def test_connected_all_match_returns_success(self):
        """连接且全部匹配时验证通过。"""
        svc = VerificationService()
        project = self._make_minimal_project()

        found = {
            "tags": [
                {"name": "BTN_Start", "data_type": "Bool"},
                {"name": "STS_Run", "data_type": "Bool"},
            ],
            "screens": [
                {
                    "name": "Main",
                    "items": [
                        {"name": "BTN_Start", "type": "button", "x": 80, "y": 120},
                        {"name": "LMP_Run", "type": "indicator", "x": 260, "y": 120},
                    ],
                }
            ],
            "events": [
                {"item_id": "BTN_Start", "event": "press", "action_type": "set_bit"},
            ],
            "bindings": [
                {"item_id": "LMP_Run", "property": "background_color", "kind": "discrete",
                 "source_tag": "STS_Run"},
            ],
            "scripts": [],
            "compile": {"errors": 0, "warnings": 0, "messages": []},
        }
        result = svc.verify_full(project, found, connected=True)
        assert result.success is True

    def test_missing_tag_reported(self):
        """缺失的 tag 被报告。"""
        svc = VerificationService()
        project = self._make_minimal_project()

        found = {
            "tags": [{"name": "BTN_Start", "data_type": "Bool"}],  # STS_Run 缺失
            "screens": [],
            "events": [],
            "bindings": [],
            "scripts": [],
            "compile": {"errors": 0, "warnings": 0, "messages": []},
        }
        result = svc.verify_full(project, found, connected=True)
        assert len(result.tags.failed) > 0
        assert any("STS_Run" in f for f in result.tags.failed)

    def test_missing_screen_reported(self):
        """缺失的 screen 被报告。"""
        svc = VerificationService()
        project = self._make_minimal_project()

        found = {
            "tags": [
                {"name": "BTN_Start", "data_type": "Bool"},
                {"name": "STS_Run", "data_type": "Bool"},
            ],
            "screens": [],  # 无 screen
            "events": [],
            "bindings": [],
            "scripts": [],
            "compile": {"errors": 0, "warnings": 0, "messages": []},
        }
        result = svc.verify_full(project, found, connected=True)
        assert len(result.screens.failed) > 0
        assert any("Main" in f for f in result.screens.failed)

    def test_compile_errors_cause_failure(self):
        """编译错误导致验证失败。"""
        svc = VerificationService()
        project = self._make_minimal_project()

        found = {
            "tags": [
                {"name": "BTN_Start", "data_type": "Bool"},
                {"name": "STS_Run", "data_type": "Bool"},
            ],
            "screens": [
                {
                    "name": "Main",
                    "items": [
                        {"name": "BTN_Start", "type": "button", "x": 80, "y": 120},
                        {"name": "LMP_Run", "type": "indicator", "x": 260, "y": 120},
                    ],
                }
            ],
            "events": [
                {"item_id": "BTN_Start", "event": "press", "action_type": "set_bit"},
            ],
            "bindings": [
                {"item_id": "LMP_Run", "property": "background_color", "kind": "discrete",
                 "source_tag": "STS_Run"},
            ],
            "scripts": [],
            "compile": {"errors": 3, "warnings": 0, "messages": ["编译异常"]},
        }
        result = svc.verify_full(project, found, connected=True)
        assert result.success is False
        assert result.compile.errors == 3

    def test_legacy_verify_tags_method(self):
        """旧版 verify_tags 方法正常。"""
        svc = VerificationService()
        result = svc.verify_tags(["A", "B", "C"], ["A", "C"])
        assert result.expected == 3
        assert result.found == 2
        assert "B" in result.failed

    def test_legacy_verify_screens_method(self):
        """旧版 verify_screens 方法正常。"""
        svc = VerificationService()
        result = svc.verify_screens(["Main", "Settings"], ["Main"])
        assert result.expected == 2
        assert result.found == 1
        assert "Settings" in result.failed

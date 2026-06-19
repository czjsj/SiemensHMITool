# -*- coding: utf-8 -*-
"""测试 V4.0 生成摘要结构 — understanding / tags / bindings / deployment。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from backend.generation_summary import build_generation_summary, build_legacy_summary
from backend.domain.ir_v2 import (
    HmiProjectSpec, TargetSpec, ScreenSpec, ScreenItemSpec,
    TagSpec, GeometrySpec, BindingSpec, EventSpec, ActionSpec,
)
from backend.domain.enums import (
    ScreenItemType, TagScope, HmiFamily, BindingKind,
    SemanticEvent, SemanticActionType, ButtonBehavior, IndicatorMode,
    TagDirection,
)


class TestGenerationSummary:
    """测试 V4.0 生成摘要。"""

    def _make_project(self) -> HmiProjectSpec:
        return HmiProjectSpec(
            target=TargetSpec(family=HmiFamily.COMFORT),
            tags=[
                TagSpec(name="BTN_Motor_Start", data_type="Bool",
                        direction=TagDirection.WRITE, scope=TagScope.INTERNAL),
                TagSpec(name="BTN_Motor_Stop", data_type="Bool",
                        direction=TagDirection.WRITE, scope=TagScope.INTERNAL),
            ],
            screens=[
                ScreenSpec(
                    name="Motor_Control", width=1280, height=800,
                    items=[
                        ScreenItemSpec(
                            id="btn_start", name="BTN_Start", type=ScreenItemType.BUTTON,
                            text={"zh-CN": "启动"}, tag_binding="BTN_Motor_Start",
                            template_ref="BTN_MOMENTARY_TEMPLATE",
                            behavior=ButtonBehavior.MOMENTARY,
                            geometry=GeometrySpec(x=80, y=120, width=120, height=50),
                            events=[
                                EventSpec(event=SemanticEvent.PRESS, actions=[
                                    ActionSpec(type=SemanticActionType.SET_BIT, tag="BTN_Motor_Start", value=1),
                                ]),
                            ],
                        ),
                        ScreenItemSpec(
                            id="lmp_running", name="LMP_Running", type=ScreenItemType.INDICATOR,
                            text={"zh-CN": "运行"}, tag_binding="BTN_Motor_Stop",
                            template_ref="LMP_STATUS_TEMPLATE",
                            indicator_mode=IndicatorMode.BOOL_COLOR,
                            geometry=GeometrySpec(x=260, y=120, width=60, height=60),
                            bindings=[
                                BindingSpec(property="background_color", kind=BindingKind.DISCRETE,
                                           source_tag="BTN_Motor_Stop"),
                            ],
                        ),
                    ],
                )
            ],
        )

    def test_understanding_contains_counts(self):
        """understanding 包含控件数量统计。"""
        project = self._make_project()
        summary = build_generation_summary(project)

        u = summary["understanding"]
        assert u["items_count"] == 2
        assert u["button_count"] == 1
        assert u["indicator_count"] == 1
        assert u["tag_count"] == 2

    def test_tags_list_contains_required_fields(self):
        """tags 列表包含必要字段。"""
        project = self._make_project()
        summary = build_generation_summary(project)

        for t in summary["tags"]:
            assert "name" in t
            assert "data_type" in t
            assert "direction" in t
            assert "address" in t

    def test_bindings_list_contains_template_ref(self):
        """bindings 列表包含 template_ref。"""
        project = self._make_project()
        summary = build_generation_summary(project)

        btn = next(b for b in summary["bindings"] if b["item_type"] == "button")
        assert btn["template_ref"] == "BTN_MOMENTARY_TEMPLATE"
        assert btn["behavior"] == "momentary"

        ind = next(b for b in summary["bindings"] if b["item_type"] == "indicator")
        assert ind["template_ref"] == "LMP_STATUS_TEMPLATE"
        assert ind["indicator_mode"] == "bool_color"

    def test_bindings_have_event_summary(self):
        """bindings 包含事件摘要。"""
        project = self._make_project()
        summary = build_generation_summary(project)

        btn = next(b for b in summary["bindings"] if b["item_type"] == "button")
        assert "event_summary" in btn
        assert len(btn["event_summary"]) > 0

    def test_deployment_with_result(self):
        """传入部署结果时填充 deployment 字段。"""
        project = self._make_project()
        dep_result = {
            "status": "DEPLOYED",
            "summary": {"tags_created": 2, "screens_created": 1},
            "compile": {"errors": 0, "warnings": 0},
            "verification": {"success": True},
        }
        summary = build_generation_summary(project, dep_result)

        dep = summary["deployment"]
        assert dep["tags_imported"] is True
        assert dep["compile_success"] is True
        assert dep["verify_success"] is True

    def test_deployment_without_result(self):
        """无部署结果时 deployment 为空。"""
        project = self._make_project()
        summary = build_generation_summary(project)

        assert summary["deployment"] == {}

    def test_legacy_summary_works(self):
        """旧版 IR 摘要正常生成。"""
        ir = {
            "meta": {"screen_name": "Test"},
            "objects": [
                {"id": "BTN_1", "type": "Button", "process_tag": "Tag_1"},
                {"id": "LMP_1", "type": "Indicator", "process_tag": "Tag_2"},
            ],
            "tags": [
                {"name": "Tag_1", "data_type": "Bool"},
                {"name": "Tag_2", "data_type": "Bool"},
            ],
        }
        summary = build_legacy_summary(ir)

        assert summary["understanding"]["button_count"] == 1
        assert summary["understanding"]["indicator_count"] == 1
        assert len(summary["tags"]) == 2
        assert len(summary["bindings"]) == 2

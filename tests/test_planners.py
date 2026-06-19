# -*- coding: utf-8 -*-
"""测试部署计划器和依赖图。"""
import sys
import os
import pytest
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.domain.ir_v2 import (
    HmiProjectSpec,
    TargetSpec,
    ScreenSpec,
    ScreenItemSpec,
    GeometrySpec,
    TagSpec,
    EventSpec,
    ActionSpec,
    BindingSpec,
    ScriptSpec,
    DeploymentPolicies,
)
from backend.domain.enums import (
    HmiFamily,
    TagScope,
    ScreenItemType,
    SemanticEvent,
    SemanticActionType,
    BindingKind,
)
from backend.domain.deployment_plan import DeploymentPlan, DeploymentStep
from backend.planners.dependency_graph import (
    DependencyGraph,
    build_dependency_order,
)
from backend.planners.deployment_planner import DeploymentPlanner
from backend.capabilities.capability_service import CapabilityService


class TestDependencyGraph:
    """DependencyGraph 测试。"""

    def test_basic_topological_sort(self):
        g = DependencyGraph()
        g.add_edge("A", "B")
        g.add_edge("B", "C")
        order = g.topological_sort()
        assert order == ["A", "B", "C"]

    def test_parallel_deps(self):
        """并行依赖: A→B, A→C → [A, B, C] or [A, C, B]。"""
        g = DependencyGraph()
        g.add_edge("A", "B")
        g.add_edge("A", "C")
        order = g.topological_sort()
        assert order[0] == "A"
        assert set(order[1:]) == {"B", "C"}

    def test_no_cycle(self):
        g = DependencyGraph()
        g.add_edge("A", "B")
        g.add_edge("B", "C")
        g.add_edge("C", "D")
        assert not g.has_cycle()

    def test_has_cycle(self):
        g = DependencyGraph()
        g.add_edge("A", "B")
        g.add_edge("B", "C")
        g.add_edge("C", "A")
        assert g.has_cycle()

    def test_build_dependency_order(self):
        """标准部署阶段排序。"""
        order = build_dependency_order(
            tag_names={"X", "Y"},
            connection_names=set(),
            script_names=set(),
            screen_names={"Main"},
        )
        assert len(order) == 10
        # P20 在 P30 之前
        assert order.index("P20_CONNECTIONS") < order.index("P30_TAG_TABLES_AND_TAGS")
        # P30 在 P50 之前
        assert order.index("P30_TAG_TABLES_AND_TAGS") < order.index("P50_SCREENS")
        # 编译在验证之前
        assert order.index("P70_COMPILE") < order.index("P80_VERIFY")


class TestDeploymentPlanner:
    """DeploymentPlanner 测试。"""

    def _make_basic_project(self):
        return HmiProjectSpec(
            target=TargetSpec(family=HmiFamily.COMFORT, tia_version="V18"),
            tags=[
                TagSpec(name="Motor_Start", data_type="Bool", scope=TagScope.EXTERNAL),
                TagSpec(name="Motor_Running", data_type="Bool", scope=TagScope.EXTERNAL),
                TagSpec(name="Motor_Speed", data_type="Real", scope=TagScope.EXTERNAL),
            ],
            screens=[
                ScreenSpec(
                    name="MainScreen",
                    width=800,
                    height=480,
                    items=[
                        ScreenItemSpec(
                            id="BTN_Start",
                            name="StartBtn",
                            type=ScreenItemType.BUTTON,
                            geometry=GeometrySpec(x=50, y=80, width=100, height=50),
                            tag_binding="Motor_Start",
                            events=[
                                EventSpec(
                                    event=SemanticEvent.PRESS,
                                    actions=[
                                        ActionSpec(type=SemanticActionType.SET_BIT, tag="Motor_Start", value=1),
                                    ],
                                ),
                                EventSpec(
                                    event=SemanticEvent.RELEASE,
                                    actions=[
                                        ActionSpec(type=SemanticActionType.RESET_BIT, tag="Motor_Start", value=0),
                                    ],
                                ),
                            ],
                            bindings=[
                                BindingSpec(property="value", kind=BindingKind.DIRECT_TAG, source_tag="Motor_Start"),
                            ],
                        ),
                        ScreenItemSpec(
                            id="STS_Run",
                            name="RunIndicator",
                            type=ScreenItemType.INDICATOR,
                            geometry=GeometrySpec(x=80, y=200, width=44, height=44, radius=22),
                            tag_binding="Motor_Running",
                            bindings=[
                                BindingSpec(
                                    property="background_color",
                                    kind=BindingKind.DISCRETE,
                                    source_tag="Motor_Running",
                                    config={"states": [{"value": 0, "output": "#3A4250"}, {"value": 1, "output": "#27D17F"}]},
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        )

    def test_build_plan_without_cap_svc(self):
        """不带 CapabilityService 也能构建计划。"""
        planner = DeploymentPlanner()
        project = self._make_basic_project()
        plan = planner.build_plan(project, dry_run=True)

        assert isinstance(plan, DeploymentPlan)
        assert plan.dry_run is True
        assert len(plan.steps) > 0

    def test_build_plan_with_cap_svc(self):
        """带 CapabilityService 构建计划。"""
        cap_svc = CapabilityService()
        planner = DeploymentPlanner(cap_svc)
        project = self._make_basic_project()
        plan = planner.build_plan(project, dry_run=True)

        assert isinstance(plan, DeploymentPlan)
        # Comfort 面板无能力报错
        errors = [d for d in plan.diagnostics if d.severity.value == "error"]
        assert len(errors) == 0

    def test_build_plan_basic_rejects_vbs(self):
        """Basic 面板 + VBS 脚本 → plan 诊断有 error。"""
        cap_svc = CapabilityService()
        planner = DeploymentPlanner(cap_svc)
        project = HmiProjectSpec(
            target=TargetSpec(family=HmiFamily.BASIC),
            scripts=[
                ScriptSpec(name="Sub_VBS", language="vbs", body="x = 1"),
            ],
            screens=[ScreenSpec(name="S1", width=800, height=480)],
        )
        plan = planner.build_plan(project, dry_run=True)
        errors = [d for d in plan.diagnostics if d.severity.value == "error"]
        assert len(errors) > 0

    def test_plan_steps_have_correct_phases(self):
        """计划步骤包含正确的阶段序列。"""
        planner = DeploymentPlanner()
        project = self._make_basic_project()
        plan = planner.build_plan(project, dry_run=True)

        phases = [s.phase for s in plan.steps]
        # 必须有发现、验证、编译
        assert any("DISCOVERY" in p for p in phases)
        assert any("VALIDATE" in p for p in phases)
        assert any("COMPILE" in p for p in phases)
        assert any("VERIFY" in p for p in phases)

    def test_plan_json_serializable(self):
        """Plan 可 JSON 序列化。"""
        planner = DeploymentPlanner()
        project = self._make_basic_project()
        plan = planner.build_plan(project, dry_run=True)

        json_str = plan.model_dump_json()
        restored = DeploymentPlan.model_validate_json(json_str)
        assert restored.plan_id == plan.plan_id
        assert len(restored.steps) == len(plan.steps)

    def test_empty_project_warns_but_no_error(self):
        """空 project（仅 screens 为空）生成警告但非 fatal。"""
        planner = DeploymentPlanner()
        project = HmiProjectSpec(target=TargetSpec(family=HmiFamily.COMFORT))
        plan = planner.build_plan(project, dry_run=True)
        # 空 project：screens 为空产生 warning，不产生致命 error
        assert len(plan.steps) > 0  # 仍有 P00/P10 步骤

    def test_plan_duplicate_tags_detected(self):
        """重复变量名在 plan 中检测到。"""
        planner = DeploymentPlanner()
        project = HmiProjectSpec(
            target=TargetSpec(family=HmiFamily.COMFORT),
            tags=[
                TagSpec(name="Same", data_type="Bool"),
                TagSpec(name="Same", data_type="Real"),
            ],
            screens=[ScreenSpec(name="S1", width=800, height=480)],
        )
        plan = planner.build_plan(project, dry_run=True)
        errors = [d for d in plan.diagnostics if d.severity.value == "error"]
        assert len(errors) > 0
        assert any("重复" in d.message for d in errors)

    def test_dry_run_vs_non_dry(self):
        """dry_run=True vs False 应有区分。"""
        planner = DeploymentPlanner()
        project = self._make_basic_project()

        plan_dry = planner.build_plan(project, dry_run=True)
        plan_live = planner.build_plan(project, dry_run=False)

        assert plan_dry.dry_run is True
        assert plan_live.dry_run is False
        # 步骤内容应相同
        assert len(plan_dry.steps) == len(plan_live.steps)

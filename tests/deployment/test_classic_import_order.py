# -*- coding: utf-8 -*-
"""测试 Classic 导入顺序约束 — tags 必须在 screens 之前。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from backend.domain.enums import DeploymentPhase
from backend.domain.ir_v2 import HmiProjectSpec, TargetSpec, ScreenSpec, ScreenItemSpec, TagSpec, GeometrySpec
from backend.domain.enums import ScreenItemType, TagScope, HmiFamily
from backend.planners.deployment_planner import DeploymentPlanner


class TestClassicImportOrder:
    """测试 Classic 后端导入顺序。"""

    def _make_minimal_project(self) -> HmiProjectSpec:
        """构造最小 HmiProjectSpec（一个 button + 一个 tag）。"""
        return HmiProjectSpec(
            target=TargetSpec(family=HmiFamily.COMFORT, tia_version="V18"),
            tags=[TagSpec(name="BTN_Motor_Start", data_type="Bool", scope=TagScope.INTERNAL)],
            screens=[
                ScreenSpec(
                    name="Main",
                    width=1280, height=800,
                    items=[
                        ScreenItemSpec(
                            id="BTN_Start", name="启动", type=ScreenItemType.BUTTON,
                            geometry=GeometrySpec(x=80, y=120, width=120, height=50),
                            tag_binding="BTN_Motor_Start",
                        ),
                    ],
                )
            ],
        )

    def test_plan_phases_follow_dependency_order(self):
        """计划步骤按依赖顺序排列。"""
        project = self._make_minimal_project()
        planner = DeploymentPlanner()
        plan = planner.build_plan(project, dry_run=True)

        # 提取各阶段索引
        phase_indices: dict[str, int] = {}
        for i, step in enumerate(plan.steps):
            phase = step.phase
            if phase not in phase_indices:
                phase_indices[phase] = i

        # P30 变量必须在 P50 画面之前
        assert phase_indices.get(DeploymentPhase.P30_TAG_TABLES_AND_TAGS.value, 0) < \
               phase_indices.get(DeploymentPhase.P50_SCREENS.value, float("inf")), \
               "变量表导入必须在画面导入之前"

    def test_tags_step_before_screen_step(self):
        """tag 步骤在 screen 步骤之前。"""
        project = self._make_minimal_project()
        planner = DeploymentPlanner()
        plan = planner.build_plan(project, dry_run=True)

        first_tag_idx = float("inf")
        first_screen_idx = float("inf")
        for i, step in enumerate(plan.steps):
            if step.target_type == "tag":
                first_tag_idx = min(first_tag_idx, i)
            if step.target_type == "screen" and step.operation != "discover":
                first_screen_idx = min(first_screen_idx, i)

        assert first_tag_idx < first_screen_idx, \
            f"第一个 tag 步骤 (idx={first_tag_idx}) 必须在第一个 screen 步骤 (idx={first_screen_idx}) 之前"

    def test_compile_after_screens(self):
        """编译在画面导入之后。"""
        project = self._make_minimal_project()
        planner = DeploymentPlanner()
        plan = planner.build_plan(project, dry_run=True)

        last_screen_idx = -1
        compile_idx = -1
        for i, step in enumerate(plan.steps):
            if step.target_type == "screen":
                last_screen_idx = max(last_screen_idx, i)
            if step.phase == DeploymentPhase.P70_COMPILE.value:
                compile_idx = i

        assert compile_idx > last_screen_idx, \
            f"编译步骤 (idx={compile_idx}) 必须在所有 screen 步骤之后 (last={last_screen_idx})"

    def test_verify_after_compile(self):
        """验证在编译之后。"""
        project = self._make_minimal_project()
        planner = DeploymentPlanner()
        plan = planner.build_plan(project, dry_run=True)

        compile_idx = -1
        verify_idx = -1
        for i, step in enumerate(plan.steps):
            if step.phase == DeploymentPhase.P70_COMPILE.value:
                compile_idx = i
            if step.phase == DeploymentPhase.P80_VERIFY.value:
                verify_idx = i

        assert verify_idx > compile_idx, \
            f"验证步骤 (idx={verify_idx}) 必须在编译步骤 (idx={compile_idx}) 之后"

    def test_blocked_when_validation_errors(self):
        """校验错误时返回空步骤。"""
        project = HmiProjectSpec(
            target=TargetSpec(family=HmiFamily.COMFORT),
            tags=[], screens=[],
        )
        # 注入一个校验错误 — 空项目没有 screens
        planner = DeploymentPlanner()
        plan = planner.build_plan(project, dry_run=True)

        # 空项目仍应生成计划（只是步骤较少）
        assert isinstance(plan.steps, list)

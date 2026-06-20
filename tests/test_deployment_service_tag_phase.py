# -*- coding: utf-8 -*-
"""
Tests for DeploymentService tag phase — V4.1 FIX

测试:
  5. DeploymentService 必须阻断变量缺失
  6. 部署顺序: IMPORT_TAGS 必须早于 IMPORT_SCREEN
"""

import pytest
from unittest.mock import MagicMock, patch
from backend.domain.ir_v2 import (
    HmiProjectSpec, TargetSpec, ScreenSpec, ScreenItemSpec, TagSpec, BindingSpec,
)
from backend.domain.enums import (
    HmiFamily, ScreenItemType, BindingKind, DeploymentStatus, DeploymentPhase,
    DiagnosticSeverity, TagScope,
)
from backend.domain.deployment_plan import DeploymentPlan, DeploymentStep
from backend.domain.deployment_result import DeploymentResult
from backend.services.deployment_service import (
    DeploymentService,
    RuntimeContext,
    BackendFactory,
    assert_tag_import_before_screen_import,
    is_import_tags_step,
    is_import_screen_step,
)


class TestDeploymentServiceBlocksMissingTags:
    """测试 5: DeploymentService 必须阻断变量缺失。"""

    def _make_project_with_missing_tag(self):
        """构造 project: item.binding.tag 指向 BTN_Missing，但 project.tags 不含它。"""
        target = TargetSpec(
            family=HmiFamily.COMFORT,
            tia_version="V18",
            device_name="TestDevice",
            device_type="TP1200",
        )
        screen = ScreenSpec(
            name="MainScreen",
            width=1280,
            height=800,
            items=[
                ScreenItemSpec(
                    id="btn_start",
                    name="btn_start",
                    type=ScreenItemType.BUTTON,
                    tag_binding="BTN_Missing",
                    bindings=[
                        BindingSpec(
                            property="value",
                            kind=BindingKind.DIRECT_TAG,
                            source_tag="BTN_Missing",
                        ),
                    ],
                ),
            ],
        )
        project = HmiProjectSpec(
            schema_version="2.0",
            target=target,
            screens=[screen],
            tags=[],  # 空 — 没有 BTN_Missing
        )
        return project

    def test_validate_returns_errors_for_missing_tag(self):
        """validate() 应检测到 binding.tag 引用不存在的变量。"""
        project = self._make_project_with_missing_tag()
        svc = DeploymentService()
        result = svc.validate(project)

        # 必须有错误
        errors = [d for d in result["diagnostics"] if d.get("severity") == "error"]
        assert len(errors) > 0, f"Expected errors for missing tag, got: {result['diagnostics']}"

    def test_deploy_legacy_ir_blocks_on_missing_tag(self):
        """deploy_legacy_ir() 应该阻断缺少变量的 IR。"""
        ir = {
            "meta": {"screen_name": "Test"},
            "objects": [
                {
                    "id": "btn_start",
                    "type": "Button",
                    "process_tag": "BTN_Missing",
                    "tag_binding": "BTN_Missing",
                    "binding": {"tag": "BTN_Missing"},
                }
            ],
            "tags": [],  # 空
        }
        svc = DeploymentService()
        result = svc.deploy_legacy_ir(ir, dry_run=True)

        # 应该因 tag 缺失被阻断
        assert not result.get("ok"), f"Expected blocked, got ok=True: {result}"
        assert result.get("status") in (
            DeploymentStatus.BLOCKED.value,
            "blocked",
        ), f"Expected BLOCKED, got {result.get('status')}"


class TestDeploymentOrder:
    """测试 6: 部署顺序 — IMPORT_TAGS 必须早于 IMPORT_SCREEN。"""

    def test_is_import_tags_step(self):
        """识别 tag import 步骤。"""
        step = DeploymentStep(
            id="s1",
            phase="P30_TAG_TABLES_AND_TAGS",
            operation="IMPORT_TAGS",
            target_type="tag_table",
            target_name="DefaultTagTable",
        )
        assert is_import_tags_step(step)

    def test_is_import_screen_step(self):
        """识别 screen import 步骤。"""
        step = DeploymentStep(
            id="s2",
            phase="P50_SCREENS",
            operation="IMPORT_SCREEN",
            target_type="screen",
            target_name="MainScreen",
        )
        assert is_import_screen_step(step)

    def test_tag_before_screen_order_passes(self):
        """P30 在 P50 前 → 通过。"""
        plan = DeploymentPlan(
            plan_id="test_plan",
            target=TargetSpec(family=HmiFamily.COMFORT, tia_version="V18", device_name="T", device_type="TP1200"),
            capabilities={},
            steps=[
                DeploymentStep(id="s1", phase="P30_TAG_TABLES_AND_TAGS", operation="IMPORT_TAGS", target_type="tag_table", target_name="T"),
                DeploymentStep(id="s2", phase="P50_SCREENS", operation="IMPORT_SCREEN", target_type="screen", target_name="S"),
            ],
            dry_run=True,
        )
        # 不应抛出
        assert_tag_import_before_screen_import(plan)

    def test_tag_after_screen_order_fails(self):
        """P30 在 P50 后 → 失败。"""
        plan = DeploymentPlan(
            plan_id="test_plan",
            target=TargetSpec(family=HmiFamily.COMFORT, tia_version="V18", device_name="T", device_type="TP1200"),
            capabilities={},
            steps=[
                DeploymentStep(id="s1", phase="P50_SCREENS", operation="IMPORT_SCREEN", target_type="screen", target_name="S"),
                DeploymentStep(id="s2", phase="P30_TAG_TABLES_AND_TAGS", operation="IMPORT_TAGS", target_type="tag_table", target_name="T"),
            ],
            dry_run=True,
        )
        with pytest.raises(ValueError, match=r"before|precede|P30.*P50"):
            assert_tag_import_before_screen_import(plan)

    def test_no_tag_step_with_screen_fails(self):
        """有画面没变量步骤 → 失败。"""
        plan = DeploymentPlan(
            plan_id="test_plan",
            target=TargetSpec(family=HmiFamily.COMFORT, tia_version="V18", device_name="T", device_type="TP1200"),
            capabilities={},
            steps=[
                DeploymentStep(id="s1", phase="P50_SCREENS", operation="IMPORT_SCREEN", target_type="screen", target_name="S"),
            ],
            dry_run=True,
        )
        with pytest.raises(ValueError, match=r"no tag|P30"):
            assert_tag_import_before_screen_import(plan)

    def test_no_screen_step_no_error(self):
        """只有 tag 没有 screen → 不报错。"""
        plan = DeploymentPlan(
            plan_id="test_plan",
            target=TargetSpec(family=HmiFamily.COMFORT, tia_version="V18", device_name="T", device_type="TP1200"),
            capabilities={},
            steps=[
                DeploymentStep(id="s1", phase="P30_TAG_TABLES_AND_TAGS", operation="IMPORT_TAGS", target_type="tag_table", target_name="T"),
            ],
            dry_run=True,
        )
        # 不应抛出
        assert_tag_import_before_screen_import(plan)

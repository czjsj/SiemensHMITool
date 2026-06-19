# -*- coding: utf-8 -*-
"""
部署计划器：从 HmiProjectSpec 构建 DeploymentPlan。

按依赖顺序自动生成部署步骤，检查能力并汇聚诊断。
不依赖 Flask、pythonnet 或 Siemens DLL。
"""

from __future__ import annotations

import uuid
from typing import Any

from backend.domain.ir_v2 import (
    HmiProjectSpec,
    TargetSpec,
    DeploymentPolicies,
)
from backend.domain.deployment_plan import DeploymentPlan, DeploymentStep
from backend.domain.diagnostics import Diagnostic, DiagnosticCodes
from backend.domain.enums import (
    DeploymentPhase,
    DiagnosticSeverity,
    HmiFamily,
    ScriptLanguage,
    SemanticActionType,
    UnsupportedFeaturePolicy,
    MissingDependencyPolicy,
    ConflictPolicy,
)
from backend.domain.validation import validate_ir_v2


class DeploymentPlanner:
    """部署计划器。

    使用方式:
        planner = DeploymentPlanner(capability_service)
        plan = planner.build_plan(project_spec, dry_run=True)
    """

    def __init__(self, capability_service=None):
        """
        参数:
            capability_service: CapabilityService 实例（可选）。
                               未提供时仅做交叉引用校验，不验证能力。
        """
        self._cap_svc = capability_service

    def build_plan(
        self,
        spec: HmiProjectSpec,
        dry_run: bool = True,
        plan_id: str | None = None,
    ) -> DeploymentPlan:
        """从 HmiProjectSpec 构建 DeploymentPlan。

        参数:
            spec: HMI 工程语义 IR。
            dry_run: 是否试运行（默认 True）。
            plan_id: 计划 ID（默认自动生成）。

        返回:
            DeploymentPlan 实例。
        """
        plan_id = plan_id or f"plan_{uuid.uuid4().hex[:12]}"
        diagnostics: list[Diagnostic] = []

        # 1. V2 交叉引用校验
        ir_diags = validate_ir_v2(spec)
        diagnostics.extend(ir_diags)

        ir_errors = [d for d in ir_diags if d.severity == DiagnosticSeverity.ERROR]
        if ir_errors:
            return DeploymentPlan(
                plan_id=plan_id,
                target=spec.target,
                capabilities={},
                steps=[],
                diagnostics=diagnostics,
                dry_run=dry_run,
            )

        # 2. 能力验证
        if self._cap_svc:
            caps = self._cap_svc.resolve(spec.target)
            cap_diags = self._cap_svc.validate_project(
                spec, caps, policy=spec.policies.unsupported_feature
            )
            diagnostics.extend(cap_diags)

            # 如果 unsupported_feature=error 且有 error，返回空步骤
            cap_errors = [
                d for d in cap_diags
                if d.severity == DiagnosticSeverity.ERROR
            ]
            if cap_errors and spec.policies.unsupported_feature == UnsupportedFeaturePolicy.ERROR:
                return DeploymentPlan(
                    plan_id=plan_id,
                    target=spec.target,
                    capabilities=caps.to_dict(),
                    steps=[],
                    diagnostics=diagnostics,
                    dry_run=dry_run,
                )
        else:
            caps = None

        # 3. 构建步骤
        steps: list[DeploymentStep] = []
        step_counter = [0]

        def _next_id():
            step_counter[0] += 1
            return f"step_{step_counter[0]:04d}"

        # P00: 发现（dry-run 模式下仅记录目标信息）
        steps.append(DeploymentStep(
            id=_next_id(),
            phase=DeploymentPhase.P00_DISCOVERY.value,
            operation="discover",
            target_type="device",
            target_name=spec.target.device_name or spec.target.device_type or "auto",
            payload={
                "family": spec.target.family.value,
                "tia_version": spec.target.tia_version,
            },
        ))

        # P10: 依赖验证
        steps.append(DeploymentStep(
            id=_next_id(),
            phase=DeploymentPhase.P10_VALIDATE_DEPENDENCIES.value,
            operation="validate",
            target_type="dependencies",
            target_name="all",
            payload={
                "tag_count": len(spec.tags),
                "screen_count": len(spec.screens),
                "script_count": len(spec.scripts),
                "connection_count": len(spec.connections),
            },
        ))

        # P20: 连接
        for conn in spec.connections:
            steps.append(DeploymentStep(
                id=_next_id(),
                phase=DeploymentPhase.P20_CONNECTIONS.value,
                operation="create_or_verify" if not conn.create_if_missing else "create",
                target_type="connection",
                target_name=conn.name,
                payload=conn.model_dump(),
            ))

        # P30: 变量表与变量
        tag_tables: set[str] = set()
        for tag in spec.tags:
            if tag.table not in tag_tables:
                tag_tables.add(tag.table)
                steps.append(DeploymentStep(
                    id=_next_id(),
                    phase=DeploymentPhase.P30_TAG_TABLES_AND_TAGS.value,
                    operation="create_if_missing",
                    target_type="tag_table",
                    target_name=tag.table,
                ))

        for tag in spec.tags:
            steps.append(DeploymentStep(
                id=_next_id(),
                phase=DeploymentPhase.P30_TAG_TABLES_AND_TAGS.value,
                operation="create_or_update",
                target_type="tag",
                target_name=tag.name,
                payload=tag.model_dump(),
            ))

        # P40: 脚本与资源
        for script in spec.scripts:
            steps.append(DeploymentStep(
                id=_next_id(),
                phase=DeploymentPhase.P40_SCRIPTS_AND_RESOURCES.value,
                operation="create_or_update",
                target_type="script",
                target_name=script.name,
                payload=script.model_dump(),
            ))

        for resource in spec.resources:
            steps.append(DeploymentStep(
                id=_next_id(),
                phase=DeploymentPhase.P40_SCRIPTS_AND_RESOURCES.value,
                operation="create_or_update",
                target_type="resource",
                target_name=resource.name,
                payload=resource.model_dump(),
            ))

        # P50: 画面
        for screen in spec.screens:
            step = DeploymentStep(
                id=_next_id(),
                phase=DeploymentPhase.P50_SCREENS.value,
                operation="create_or_update",
                target_type="screen",
                target_name=screen.name,
                payload={
                    "name": screen.name,
                    "width": screen.width,
                    "height": screen.height,
                    "item_count": len(screen.items),
                },
            )
            steps.append(step)

            # 控件
            for item in screen.items:
                steps.append(DeploymentStep(
                    id=_next_id(),
                    phase=DeploymentPhase.P50_SCREENS.value,
                    operation="create_or_update",
                    target_type="screen_item",
                    target_name=item.id,
                    payload={
                        "id": item.id,
                        "type": item.type.value,
                        "geometry": item.geometry.model_dump(),
                        "tag_binding": item.tag_binding,
                    },
                ))

        # P60: 绑定与事件
        for screen in spec.screens:
            for item in screen.items:
                for binding in item.bindings:
                    steps.append(DeploymentStep(
                        id=_next_id(),
                        phase=DeploymentPhase.P60_BINDINGS_AND_EVENTS.value,
                        operation="apply",
                        target_type="binding",
                        target_name=f"{item.id}.{binding.property}",
                        payload=binding.model_dump(),
                    ))

                for event in item.events:
                    steps.append(DeploymentStep(
                        id=_next_id(),
                        phase=DeploymentPhase.P60_BINDINGS_AND_EVENTS.value,
                        operation="apply",
                        target_type="event",
                        target_name=f"{item.id}.{event.event.value}",
                        payload={
                            "event": event.event.value,
                            "action_count": len(event.actions),
                        },
                    ))

        # P70: 编译
        if spec.policies.compile_after_deploy:
            steps.append(DeploymentStep(
                id=_next_id(),
                phase=DeploymentPhase.P70_COMPILE.value,
                operation="compile",
                target_type="hmi_software",
                target_name="HMI",
            ))

        # P80: 验证
        steps.append(DeploymentStep(
            id=_next_id(),
            phase=DeploymentPhase.P80_VERIFY.value,
            operation="verify",
            target_type="deployment",
            target_name="all",
            payload={
                "expected_tags": len(spec.tags),
                "expected_screens": len(spec.screens),
            },
        ))

        # P90: 保存
        if spec.policies.save_after_deploy:
            steps.append(DeploymentStep(
                id=_next_id(),
                phase=DeploymentPhase.P90_SAVE.value,
                operation="save",
                target_type="project",
                target_name="TIA_Project",
            ))

        return DeploymentPlan(
            plan_id=plan_id,
            target=spec.target,
            capabilities=caps.to_dict() if caps else {},
            steps=steps,
            diagnostics=diagnostics,
            dry_run=dry_run,
        )

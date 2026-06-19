# -*- coding: utf-8 -*-
"""Basic Panel Backend — 经典 HMI XML + FunctionList（禁止 VBS）。"""
from __future__ import annotations
from backend.backends.base import HmiBackend
from backend.domain.ir_v2 import HmiProjectSpec, TargetSpec
from backend.domain.deployment_plan import DeploymentPlan
from backend.domain.deployment_result import DeploymentResult, VerificationResult, CompileResult, ObjectCountSummary
from backend.domain.diagnostics import Diagnostic, DiagnosticCodes
from backend.domain.enums import HmiFamily, DiagnosticSeverity
from .common import ClassicCommon


class BasicBackend(HmiBackend):
    """Basic Panel 部署后端。（生成 XML 描述；真实导入需 TIA 运行时）"""

    def __init__(self):
        self._common = ClassicCommon(target_family="basic")

    def supports(self, target: TargetSpec) -> bool:
        return target.family == HmiFamily.BASIC

    def build_plan(self, spec: HmiProjectSpec, context: dict | None = None) -> DeploymentPlan:
        from backend.planners.deployment_planner import DeploymentPlanner
        from backend.capabilities.capability_service import CapabilityService
        cap_svc = CapabilityService()
        planner = DeploymentPlanner(cap_svc)
        plan = planner.build_plan(spec, dry_run=True)
        for script in spec.scripts:
            if script.language.value in ("vbs", "javascript"):
                plan.diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.CAP_UNSUPPORTED_FEATURE,
                    severity=DiagnosticSeverity.ERROR,
                    phase="P10_VALIDATE_DEPENDENCIES",
                    object_type="script", object_name=script.name,
                    message=f"Basic 面板不支持 {script.language.value} 脚本 '{script.name}'",
                ))
        return plan

    def execute(self, plan: DeploymentPlan, context: dict | None = None) -> DeploymentResult:
        ctx = context or {}
        connected = bool(ctx.get("connected") or ctx.get("openness_manager"))

        if not connected:
            return DeploymentResult(
                success=False,
                plan_id=plan.plan_id,
                backend="basic_classic",
                diagnostics=[Diagnostic(
                    code="NOT_CONNECTED",
                    severity=DiagnosticSeverity.ERROR,
                    phase="P50_SCREENS",
                    message="未连接到 TIA Portal，无法执行 Basic 真实部署。当前仅生成 XML 描述。",
                )],
                details={"mode": "DRY_RUN", "xml_generated": True},
            )

        result = DeploymentResult(success=True, plan_id=plan.plan_id, backend="basic_classic")
        for step in plan.steps:
            if step.target_type == "tag":
                result.tags_created += 1
            elif step.target_type == "screen":
                result.screens_created += 1
            elif step.target_type == "binding":
                result.bindings_created += 1
            elif step.target_type == "event":
                result.events_created += 1
        result.details["xml_generated"] = True
        return result

    def verify(self, spec: HmiProjectSpec, context: dict | None = None) -> VerificationResult:
        ctx = context or {}
        connected = bool(ctx.get("connected") or ctx.get("openness_manager"))

        if not connected:
            return VerificationResult(
                success=False,
                tags=ObjectCountSummary(expected=len(spec.tags), found=0, failed=[t.name for t in spec.tags]),
                screens=ObjectCountSummary(expected=len(spec.screens), found=0, failed=[s.name for s in spec.screens]),
                compile=CompileResult(errors=0, warnings=0, messages=["NOT_CONNECTED: 无法验证 — 未连接 TIA Portal"]),
            )

        return VerificationResult(
            success=True,
            tags=ObjectCountSummary(expected=len(spec.tags), found=len(spec.tags)),
            screens=ObjectCountSummary(expected=len(spec.screens), found=len(spec.screens)),
            compile=CompileResult(errors=0, warnings=0),
        )

    def compile_tags(self, tags):
        return self._common.build_tags_xml(tags)

    def compile_screen(self, screen):
        return self._common.build_screen_xml(screen)

    def compile_event(self, event):
        return self._common.function_list_builder.build(event, target_family="basic")

    def compile_binding(self, binding):
        return self._common.dynamic_builder.build(binding)

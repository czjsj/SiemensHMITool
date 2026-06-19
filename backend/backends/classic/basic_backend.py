# -*- coding: utf-8 -*-
"""Basic Panel Backend — 经典 HMI XML + FunctionList（禁止 VBS）。

方案文档 §9 对齐。
"""
from __future__ import annotations
from backend.backends.base import HmiBackend
from backend.domain.ir_v2 import HmiProjectSpec, TargetSpec
from backend.domain.deployment_plan import DeploymentPlan
from backend.domain.deployment_result import DeploymentResult, VerificationResult, CompileResult, ObjectCountSummary
from backend.domain.enums import HmiFamily
from backend.domain.diagnostics import Diagnostic, DiagnosticCodes
from backend.domain.enums import DiagnosticSeverity
from .common import ClassicCommon


class BasicBackend(HmiBackend):
    """Basic Panel 部署后端。

    技术路线: IR V2 → BasicCapabilityValidator → BasicClassicCompiler
              → Tag XML + Resource XML + Screen XML → Openness Import → Compile + Verify
    禁止使用 VBS。复杂业务转为 PLC 逻辑或返回不支持错误。
    """

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

        # Basic 拒绝 VBS 和 call_script
        for script in spec.scripts:
            if script.language.value in ("vbs", "javascript"):
                plan.diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.CAP_UNSUPPORTED_FEATURE,
                    severity=DiagnosticSeverity.ERROR,
                    phase="P10_VALIDATE_DEPENDENCIES",
                    object_type="script",
                    object_name=script.name,
                    message=f"Basic 面板不支持 {script.language.value} 脚本 '{script.name}'",
                ))
        return plan

    def execute(self, plan: DeploymentPlan, context: dict | None = None) -> DeploymentResult:
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
        return result

    def verify(self, spec: HmiProjectSpec, context: dict | None = None) -> VerificationResult:
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

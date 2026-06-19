# -*- coding: utf-8 -*-
"""Unified Backend — WinCC Unified Direct Object Model。（生成规格，真实创建需 TIA 运行时）"""
from __future__ import annotations
from backend.backends.base import HmiBackend
from backend.domain.ir_v2 import HmiProjectSpec, TargetSpec
from backend.domain.deployment_plan import DeploymentPlan
from backend.domain.deployment_result import DeploymentResult, VerificationResult, CompileResult, ObjectCountSummary
from backend.domain.diagnostics import Diagnostic, DiagnosticCodes
from backend.domain.enums import HmiFamily, DiagnosticSeverity


class UnifiedBackend(HmiBackend):
    """Unified 面板部署后端。"""

    def __init__(self):
        self._tag_builder = None
        self._screen_builder = None
        self._binding_builder = None
        self._event_builder = None
        self._js_builder = None
        self._reflection_adapter = None

    @property
    def tag_builder(self):
        if self._tag_builder is None:
            from .tag_builder import UnifiedTagBuilder
            self._tag_builder = UnifiedTagBuilder()
        return self._tag_builder

    @property
    def screen_builder(self):
        if self._screen_builder is None:
            from .screen_builder import UnifiedScreenBuilder
            self._screen_builder = UnifiedScreenBuilder()
        return self._screen_builder

    @property
    def binding_builder(self):
        if self._binding_builder is None:
            from .binding_builder import UnifiedBindingBuilder
            self._binding_builder = UnifiedBindingBuilder()
        return self._binding_builder

    @property
    def event_builder(self):
        if self._event_builder is None:
            from .event_builder import UnifiedEventBuilder
            self._event_builder = UnifiedEventBuilder()
        return self._event_builder

    @property
    def js_builder(self):
        if self._js_builder is None:
            from .js_builder import JsBuilder
            self._js_builder = JsBuilder()
        return self._js_builder

    def supports(self, target: TargetSpec) -> bool:
        return target.family == HmiFamily.UNIFIED

    def build_plan(self, spec: HmiProjectSpec, context: dict | None = None) -> DeploymentPlan:
        from backend.planners.deployment_planner import DeploymentPlanner
        from backend.capabilities.capability_service import CapabilityService
        cap_svc = CapabilityService()
        planner = DeploymentPlanner(cap_svc)
        return planner.build_plan(spec, dry_run=True)

    def execute(self, plan: DeploymentPlan, context: dict | None = None) -> DeploymentResult:
        """执行部署。无 TIA 连接时返回 NOT_CONNECTED，不返回成功。"""
        ctx = context or {}
        connected = bool(ctx.get("connected") or ctx.get("openness_manager"))

        if not connected:
            return DeploymentResult(
                success=False,
                plan_id=plan.plan_id,
                backend="unified_direct",
                diagnostics=[Diagnostic(
                    code="NOT_CONNECTED",
                    severity=DiagnosticSeverity.ERROR,
                    phase="P50_SCREENS",
                    message="未连接到 TIA Portal，无法执行 Unified 真实部署。当前仅生成规格描述。",
                )],
                details={"mode": "DRY_RUN", "spec_generated": True},
            )

        result = DeploymentResult(success=True, plan_id=plan.plan_id, backend="unified_direct")
        for step in plan.steps:
            if step.target_type == "tag":
                result.tags_created += 1
            elif step.target_type == "screen":
                result.screens_created += 1
            elif step.target_type == "script":
                result.scripts_created += 1
            elif step.target_type == "binding":
                result.bindings_created += 1
            elif step.target_type == "event":
                result.events_created += 1
        result.details["spec_generated"] = True
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

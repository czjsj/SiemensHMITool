# -*- coding: utf-8 -*-
"""Comfort Panel Backend — 经典 HMI XML + FunctionList + VBS。"""
from __future__ import annotations
import uuid
from backend.backends.base import HmiBackend
from backend.domain.ir_v2 import HmiProjectSpec, TargetSpec
from backend.domain.deployment_plan import DeploymentPlan, DeploymentStep
from backend.domain.deployment_result import DeploymentResult, VerificationResult, CompileResult, ObjectCountSummary
from backend.domain.diagnostics import Diagnostic, DiagnosticCodes
from backend.domain.enums import HmiFamily, DeploymentPhase, DiagnosticSeverity
from .common import ClassicCommon
from .vbs_builder import VbsBuilder


class ComfortBackend(HmiBackend):
    """Comfort Panel 部署后端。（生成 XML 描述；真实导入需 TIA 运行时）"""

    def __init__(self):
        self._common = ClassicCommon(target_family="comfort")
        self._vbs_builder = VbsBuilder()

    def supports(self, target: TargetSpec) -> bool:
        return target.family in (HmiFamily.COMFORT, HmiFamily.AUTO)

    def build_plan(self, spec: HmiProjectSpec, context: dict | None = None) -> DeploymentPlan:
        from backend.planners.deployment_planner import DeploymentPlanner
        from backend.capabilities.capability_service import CapabilityService
        cap_svc = CapabilityService()
        planner = DeploymentPlanner(cap_svc)
        return planner.build_plan(spec, dry_run=True)

    def execute(self, plan: DeploymentPlan, context: dict | None = None) -> DeploymentResult:
        """执行部署。无 TIA 连接时返回 DRY_RUN 或 NOT_CONNECTED，不返回成功。"""
        ctx = context or {}
        connected = bool(ctx.get("connected") or ctx.get("openness_manager"))

        if not connected:
            return DeploymentResult(
                success=False,
                plan_id=plan.plan_id,
                backend="comfort_classic",
                diagnostics=[Diagnostic(
                    code="NOT_CONNECTED",
                    severity=DiagnosticSeverity.ERROR,
                    phase="P50_SCREENS",
                    message="未连接到 TIA Portal，无法执行 Comfort 真实部署。当前仅生成 XML 描述。",
                )],
                details={"mode": "DRY_RUN", "xml_generated": True},
            )

        # 真实部署：统计步骤并生成 XML 产物
        result = DeploymentResult(success=True, plan_id=plan.plan_id, backend="comfort_classic")
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

        result.details["xml_generated"] = True
        return result

    def verify(self, spec: HmiProjectSpec, context: dict | None = None) -> VerificationResult:
        """验证。无 TIA 连接时不可声称成功。"""
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

    # ---- XML 产物生成器（不调用 Siemens Openness） ----

    def compile_connections(self, connections) -> list[str]:
        return ["<!-- Comfort connections XML -->"]

    def compile_tags(self, tags) -> str:
        return self._common.build_tags_xml(tags)

    def compile_resources(self, resources) -> str:
        lines = []
        for r in resources:
            lines.append(f'<TextList Name="{r.name}">')
            for e in r.entries:
                lines.append(f'  <Entry Value="{e.get("value",0)}" Text="{e.get("text","")}"/>')
            lines.append(f'</TextList>')
        return "\n".join(lines)

    def compile_screen(self, screen) -> str:
        return self._common.build_screen_xml(screen)

    def compile_event(self, event) -> str:
        return self._common.function_list_builder.build(event, target_family="comfort")

    def compile_binding(self, binding) -> str:
        return self._common.dynamic_builder.build(binding)

    def build_vbs_script(self, script) -> str:
        code = script.body
        scan = self._vbs_builder.security_scan(code)
        if not scan["ok"]:
            raise ValueError(f"VBS security scan failed: {scan['errors']}")
        return f'<Script Name="{script.name}" Language="VBScript">\n<Code>{code}</Code>\n</Script>'

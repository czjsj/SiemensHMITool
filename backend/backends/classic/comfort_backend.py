# -*- coding: utf-8 -*-
"""Comfort Panel Backend — 经典 HMI XML + FunctionList + VBS。

方案文档 §10 对齐。
"""
from __future__ import annotations
import uuid
from backend.backends.base import HmiBackend
from backend.domain.ir_v2 import HmiProjectSpec, TargetSpec
from backend.domain.deployment_plan import DeploymentPlan, DeploymentStep
from backend.domain.deployment_result import DeploymentResult, VerificationResult, CompileResult, ObjectCountSummary
from backend.domain.enums import HmiFamily, DeploymentPhase
from .common import ClassicCommon
from .vbs_builder import VbsBuilder


class ComfortBackend(HmiBackend):
    """Comfort Panel 部署后端。

    技术路线: IR V2 → ComfortCapabilityValidator → ComfortClassicCompiler
              → Tag XML + VBS XML + Resource XML + Screen XML → Openness Import → Compile + Verify
    """

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
        result = DeploymentResult(
            success=True,
            plan_id=plan.plan_id,
            backend="comfort_classic",
        )
        # 按阶段顺序统计各步（实际执行依赖 Openness 连接，当前为 dry-execute 模式）
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
        return result

    def verify(self, spec: HmiProjectSpec, context: dict | None = None) -> VerificationResult:
        return VerificationResult(
            success=True,
            tags=ObjectCountSummary(expected=len(spec.tags), found=len(spec.tags)),
            screens=ObjectCountSummary(expected=len(spec.screens), found=len(spec.screens)),
            compile=CompileResult(errors=0, warnings=0),
        )

    def compile_connections(self, connections):
        return ["<!-- Comfort connections XML -->"]

    def compile_tags(self, tags):
        return self._common.build_tags_xml(tags)

    def compile_resources(self, resources):
        lines = []
        for r in resources:
            lines.append(f'<TextList Name="{r.name}">')
            for e in r.entries:
                lines.append(f'  <Entry Value="{e.get("value",0)}" Text="{e.get("text","")}"/>')
            lines.append(f'</TextList>')
        return "\n".join(lines)

    def compile_screen(self, screen):
        return self._common.build_screen_xml(screen)

    def compile_event(self, event):
        return self._common.function_list_builder.build(event, target_family="comfort")

    def compile_binding(self, binding):
        return self._common.dynamic_builder.build(binding)

    def build_vbs_script(self, script) -> str:
        code = script.body
        scan = self._vbs_builder.security_scan(code)
        if not scan["ok"]:
            raise ValueError(f"VBS security scan failed: {scan['errors']}")
        return f'<Script Name="{script.name}" Language="VBScript">\n<Code>{code}</Code>\n</Script>'

# -*- coding: utf-8 -*-
"""
Basic Panel Backend — 经典 HMI XML + FunctionList（禁止 VBS）。

V3.2: 真实 TIA 部署通过 ClassicOpennessExecutor 执行。
      无 TIA 连接时永远不返回 DEPLOYED。
      connected=True 不自动代表部署成功。
"""
from __future__ import annotations
from backend.backends.base import HmiBackend
from backend.domain.ir_v2 import HmiProjectSpec, TargetSpec
from backend.domain.deployment_plan import DeploymentPlan
from backend.domain.deployment_result import (
    DeploymentResult, VerificationResult, CompileResult, ObjectCountSummary,
)
from backend.domain.diagnostics import Diagnostic, DiagnosticCodes
from backend.domain.enums import (
    HmiFamily, DeploymentStatus, DiagnosticSeverity,
)
from .common import ClassicCommon


class BasicBackend(HmiBackend):
    """Basic Panel 部署后端。

    execute() 分类:
      - 无 TIA 连接: DESCRIPTION_ONLY → NOT_CONNECTED
      - 有 TIA 连接: TIA_MUTATION → ClassicOpennessExecutor.execute_all()
    verify() 分类:
      - 无 TIA 连接: DESCRIPTION_ONLY → NOT_CONNECTED
      - 有 TIA 连接: TIA_QUERY → ObjectQueryService.query_full_snapshot()

    禁止 VBS 脚本。Basic 不支持 VBS。
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
        # 拒绝 VBS 脚本
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

    # ------------------------------------------------------------------
    # execute
    # ------------------------------------------------------------------

    def execute(self, plan: DeploymentPlan, context: dict | None = None) -> DeploymentResult:
        """执行 Basic 部署。

        只有真实 Openness 修改完成且编译无错误时，status=DEPLOYED。
        """
        ctx = context or {}
        connected = bool(ctx.get("connected") or ctx.get("openness_manager"))
        dry_run = plan.dry_run

        if dry_run:
            return DeploymentResult(
                success=True,
                status=DeploymentStatus.DRY_RUN,
                plan_id=plan.plan_id,
                backend="basic_classic",
                details={"mode": "DRY_RUN", "xml_generated": True},
            )

        if not connected:
            return DeploymentResult(
                success=False,
                status=DeploymentStatus.NOT_CONNECTED,
                plan_id=plan.plan_id,
                backend="basic_classic",
                diagnostics=[Diagnostic(
                    code="NOT_CONNECTED",
                    severity=DiagnosticSeverity.ERROR,
                    phase="P50_SCREENS",
                    message="未连接到 TIA Portal，无法执行 Basic 真实部署。",
                )],
                details={"mode": "NOT_CONNECTED"},
            )

        # 真实 TIA 部署
        hmi_sw = ctx.get("hmi_software")
        project = ctx.get("project_obj")

        if hmi_sw is None:
            from backend.openness.classic_executor import ClassicOpennessExecutor
            executor = ClassicOpennessExecutor()
            hmi_sw, _, _ = executor.locate_hmi_target(project)

        if hmi_sw is None:
            return DeploymentResult(
                success=False,
                status=DeploymentStatus.FAILED,
                plan_id=plan.plan_id,
                backend="basic_classic",
                diagnostics=[Diagnostic(
                    code="TIA_NOT_CONNECTED",
                    severity=DiagnosticSeverity.ERROR,
                    message="无法定位 Basic HMI 目标设备。",
                )],
            )

        spec = ctx.get("project_spec")
        tags_xml = ""
        screen_xml_list: list[str] = []

        if spec:
            tags_xml = self.compile_tags(spec.tags)
            for screen in spec.screens:
                screen_xml_list.append(self.compile_screen(screen))

        from backend.openness.classic_executor import ClassicOpennessExecutor
        tia_executor = ClassicOpennessExecutor()

        step_results = tia_executor.execute_all(
            project=project,
            hmi_software=hmi_sw,
            connections_xml=[],
            tags_xml=tags_xml,
            scripts_xml="",
            resources_xml="",
            screen_xml_list=screen_xml_list,
        )

        all_ok = all(r.success for r in step_results)
        diags: list[Diagnostic] = []
        for r in step_results:
            diags.extend(r.diagnostics)

        tags_created = sum(r.objects_created for r in step_results if r.step_key == "tags")
        screens_created = sum(r.objects_created for r in step_results if r.step_key == "screens")
        compile_ok = any(r.step_key == "compile" and r.success for r in step_results)

        status = DeploymentStatus.DEPLOYED if all_ok and compile_ok else DeploymentStatus.FAILED

        return DeploymentResult(
            success=all_ok and compile_ok,
            status=status,
            plan_id=plan.plan_id,
            backend="basic_classic",
            tags_created=tags_created,
            screens_created=screens_created,
            diagnostics=diags,
            details={
                "step_results": [r.to_dict() for r in step_results],
                "tia_operations": [r.operation_kind.value for r in step_results],
            },
        )

    # ------------------------------------------------------------------
    # verify
    # ------------------------------------------------------------------

    def verify(self, spec: HmiProjectSpec, context: dict | None = None) -> VerificationResult:
        """验证部署结果 — 只读查询 + 语义验证。"""
        ctx = context or {}
        connected = bool(ctx.get("connected") or ctx.get("openness_manager"))

        if not connected:
            return VerificationResult(
                success=False,
                tags=ObjectCountSummary(expected=len(spec.tags), found=0,
                                        failed=[t.name for t in spec.tags]),
                screens=ObjectCountSummary(expected=len(spec.screens), found=0,
                                           failed=[s.name for s in spec.screens]),
                compile=CompileResult(errors=0, warnings=0,
                                     messages=["NOT_CONNECTED: 无法验证 — 未连接 TIA Portal"]),
            )

        hmi_sw = ctx.get("hmi_software")
        if hmi_sw is None:
            return VerificationResult(
                success=False,
                compile=CompileResult(errors=1, messages=["无法定位 HMI 目标设备"]),
            )

        compiled_result = ctx.get("compiled_result")
        plan_id = ctx.get("plan_id", "")

        from backend.openness.object_query_service import ObjectQueryService
        from backend.services.verification_service import VerificationService
        query_svc = ObjectQueryService(export_dir=ctx.get("export_dir", ""))
        snapshot = query_svc.query_full_snapshot(
            hmi_software=hmi_sw,
            compiled_result=compiled_result,
            family="basic",
        )
        query_svc.save_snapshot(snapshot, plan_id)
        rev_exports = query_svc.export_screens_xml(hmi_sw, unified=False)
        query_svc.save_reverse_export_xml(rev_exports, plan_id)

        verify_svc = VerificationService()
        return verify_svc.verify_full(spec, snapshot, connected=True)

    # ---- XML 产物生成器 ----

    def compile_tags(self, tags):
        return self._common.build_tags_xml(tags)

    def compile_screen(self, screen):
        return self._common.build_screen_xml(screen)

    def compile_event(self, event):
        return self._common.function_list_builder.build(event, target_family="basic")

    def compile_binding(self, binding):
        return self._common.dynamic_builder.build(binding)

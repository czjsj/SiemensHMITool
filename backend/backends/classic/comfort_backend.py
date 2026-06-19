# -*- coding: utf-8 -*-
"""
Comfort Panel Backend — 经典 HMI XML + FunctionList + VBS。

V3.2: 真实 TIA 部署通过 ClassicOpennessExecutor 执行。
      无 TIA 连接时永远不返回 DEPLOYED。
      connected=True 不自动代表部署成功。
"""
from __future__ import annotations
import uuid
from backend.backends.base import HmiBackend
from backend.domain.ir_v2 import HmiProjectSpec, TargetSpec
from backend.domain.deployment_plan import DeploymentPlan, DeploymentStep
from backend.domain.deployment_result import (
    DeploymentResult, VerificationResult, CompileResult, ObjectCountSummary,
)
from backend.domain.diagnostics import Diagnostic, DiagnosticCodes
from backend.domain.enums import (
    HmiFamily, DeploymentPhase, DeploymentStatus, DiagnosticSeverity,
    OpennessOperationKind,
)
from .common import ClassicCommon
from .vbs_builder import VbsBuilder


class ComfortBackend(HmiBackend):
    """Comfort Panel 部署后端。

    execute() 分类:
      - 无 TIA 连接: DESCRIPTION_ONLY → 返回 NOT_CONNECTED
      - 有 TIA 连接: TIA_MUTATION → ClassicOpennessExecutor.execute_all()
    verify() 分类:
      - 无 TIA 连接: DESCRIPTION_ONLY → 返回 NOT_CONNECTED
      - 有 TIA 连接: TIA_QUERY → ObjectQueryService.query_full_snapshot()
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

    # ------------------------------------------------------------------
    # execute — 真实 TIA 部署入口
    # ------------------------------------------------------------------

    def execute(self, plan: DeploymentPlan, context: dict | None = None) -> DeploymentResult:
        """执行 Comfort 部署。

        dry_run=true 时不要求 TIA 连接，计划成功则 success=true, status=DRY_RUN。
        dry_run=false 且未连接时 success=false, status=NOT_CONNECTED。
        只有真实 Openness 修改完成且编译无错误时，status=DEPLOYED。
        """
        ctx = context or {}
        connected = bool(ctx.get("connected") or ctx.get("openness_manager"))
        dry_run = plan.dry_run

        # DRY_RUN: 计划验证通过即可
        if dry_run:
            return DeploymentResult(
                success=True,
                status=DeploymentStatus.DRY_RUN,
                plan_id=plan.plan_id,
                backend="comfort_classic",
                details={"mode": "DRY_RUN", "xml_generated": True},
            )

        # NOT_CONNECTED: 不可执行真实部署
        if not connected:
            return DeploymentResult(
                success=False,
                status=DeploymentStatus.NOT_CONNECTED,
                plan_id=plan.plan_id,
                backend="comfort_classic",
                diagnostics=[Diagnostic(
                    code="NOT_CONNECTED",
                    severity=DiagnosticSeverity.ERROR,
                    phase="P50_SCREENS",
                    message="未连接到 TIA Portal，无法执行 Comfort 真实部署。",
                )],
                details={"mode": "NOT_CONNECTED"},
            )

        # ---- 真实 TIA 部署 ----
        hmi_sw = ctx.get("hmi_software")
        project = ctx.get("project_obj")
        openness_mgr = ctx.get("openness_manager")

        if hmi_sw is None and openness_mgr is not None:
            try:
                from backend.openness.classic_executor import ClassicOpennessExecutor
                executor = ClassicOpennessExecutor()
                hmi_sw, _, _ = executor.locate_hmi_target(project)
            except Exception:
                pass

        if hmi_sw is None:
            return DeploymentResult(
                success=False,
                status=DeploymentStatus.FAILED,
                plan_id=plan.plan_id,
                backend="comfort_classic",
                diagnostics=[Diagnostic(
                    code="TIA_NOT_CONNECTED",
                    severity=DiagnosticSeverity.ERROR,
                    message="无法定位 Comfort HMI 目标设备。",
                )],
            )

        # 生成 XML 产物
        spec = ctx.get("project_spec")
        connections_xml = []
        tags_xml = ""
        scripts_xml = ""
        resources_xml = ""
        screen_xml_list: list[str] = []

        if spec:
            connections_xml = self.compile_connections(getattr(spec, "connections", []))
            tags_xml = self.compile_tags(spec.tags)
            for script in spec.scripts:
                scripts_xml += self.build_vbs_script(script) + "\n"
            for resource in getattr(spec, "resources", []):
                resources_xml += self.compile_resources([resource])[0] + "\n"
            for screen in spec.screens:
                screen_xml_list.append(self.compile_screen(screen))

        # 执行真实 TIA 调用
        from backend.openness.classic_executor import ClassicOpennessExecutor
        tia_executor = ClassicOpennessExecutor()

        step_results = tia_executor.execute_all(
            project=project,
            hmi_software=hmi_sw,
            connections_xml=connections_xml,
            tags_xml=tags_xml,
            scripts_xml=scripts_xml,
            resources_xml=resources_xml,
            screen_xml_list=screen_xml_list,
        )

        # 汇总结果
        all_ok = all(r.success for r in step_results)
        diags: list[Diagnostic] = []
        for r in step_results:
            diags.extend(r.diagnostics)

        tags_created = sum(r.objects_created for r in step_results if r.step_key == "tags")
        screens_created = sum(r.objects_created for r in step_results if r.step_key == "screens")
        scripts_created = sum(r.objects_created for r in step_results if r.step_key == "scripts_resources")
        compile_ok = any(r.step_key == "compile" and r.success for r in step_results)

        status = DeploymentStatus.DEPLOYED if all_ok and compile_ok else DeploymentStatus.FAILED

        return DeploymentResult(
            success=all_ok and compile_ok,
            status=status,
            plan_id=plan.plan_id,
            backend="comfort_classic",
            tags_created=tags_created,
            screens_created=screens_created,
            scripts_created=scripts_created,
            diagnostics=diags,
            details={
                "step_results": [r.to_dict() for r in step_results],
                "tia_operations": [
                    r.operation_kind.value for r in step_results
                ],
            },
        )

    # ------------------------------------------------------------------
    # verify — 真实 TIA 对象查询 + 语义验证
    # ------------------------------------------------------------------

    def verify(self, spec: HmiProjectSpec, context: dict | None = None) -> VerificationResult:
        """验证部署结果 — 只读查询 + 语义验证。

        context 可携带:
          - compiled_result: HmiCompiler.compile() 返回的编译结果 dict
          - plan_id: 用于日志文件命名
          - export_dir: 快照导出目录
        """
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

        # 真实查询 TIA 对象（只读；编译结果外部传入，绝不内部调用 Compile）
        from backend.openness.object_query_service import ObjectQueryService
        export_dir = ctx.get("export_dir", "")
        query_svc = ObjectQueryService(export_dir=export_dir)
        snapshot = query_svc.query_full_snapshot(
            hmi_software=hmi_sw,
            compiled_result=compiled_result,
            family="comfort",
        )

        # 持久化快照
        snapshot_path = query_svc.save_snapshot(snapshot, plan_id)
        ctx.setdefault("_artifacts", {})["snapshot_path"] = snapshot_path

        # 反向导出 Screens XML
        rev_exports = query_svc.export_screens_xml(hmi_sw, unified=False)
        rev_paths = query_svc.save_reverse_export_xml(rev_exports, plan_id)
        ctx.setdefault("_artifacts", {})["reverse_export_paths"] = rev_paths

        # 语义验证
        from backend.services.verification_service import VerificationService
        verify_svc = VerificationService()
        return verify_svc.verify_full(spec, snapshot, connected=True)

    # ---- XML 产物生成器（DESCRIPTION_ONLY，不调用 Siemens Openness） ----

    def compile_connections(self, connections) -> list[str]:
        return ["<!-- Comfort connections XML -->"]

    def compile_tags(self, tags) -> str:
        return self._common.build_tags_xml(tags)

    def compile_resources(self, resources) -> list[str]:
        lines = []
        for r in resources:
            lines.append(f'<TextList Name="{r.name}">')
            for e in r.entries:
                lines.append(f'  <Entry Value="{e.get("value",0)}" Text="{e.get("text","")}"/>')
            lines.append('</TextList>')
        return lines

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

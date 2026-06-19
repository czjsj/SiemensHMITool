# -*- coding: utf-8 -*-
"""
Unified Backend — WinCC Unified Direct Object Model。

V3.2: 真实 TIA 部署通过 UnifiedOpennessExecutor 执行。
      需要 RuntimeContract 缓存。
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


class UnifiedBackend(HmiBackend):
    """Unified 面板部署后端。

    execute() 分类:
      - 无 TIA 连接: DESCRIPTION_ONLY → NOT_CONNECTED
      - 有 TIA 连接: TIA_MUTATION → UnifiedOpennessExecutor.execute_all()
    verify() 分类:
      - 无 TIA 连接: DESCRIPTION_ONLY → NOT_CONNECTED
      - 有 TIA 连接: TIA_QUERY → ObjectQueryService.query_full_snapshot()

    执行前:
      - 加载 RuntimeContract
      - 缺失 contract 时自动 probe
      - 类型/方法/属性/事件缺失时失败关闭
    """

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

    # ------------------------------------------------------------------
    # execute
    # ------------------------------------------------------------------

    def execute(self, plan: DeploymentPlan, context: dict | None = None) -> DeploymentResult:
        """执行 Unified 部署。

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
                backend="unified_direct",
                details={"mode": "DRY_RUN", "spec_generated": True},
            )

        if not connected:
            return DeploymentResult(
                success=False,
                status=DeploymentStatus.NOT_CONNECTED,
                plan_id=plan.plan_id,
                backend="unified_direct",
                diagnostics=[Diagnostic(
                    code="NOT_CONNECTED",
                    severity=DiagnosticSeverity.ERROR,
                    phase="P50_SCREENS",
                    message="未连接到 TIA Portal，无法执行 Unified 真实部署。",
                )],
                details={"mode": "NOT_CONNECTED"},
            )

        # 真实 TIA 部署
        hmi_sw = ctx.get("hmi_software")
        spec = ctx.get("project_spec")
        dll_path = ctx.get("dll_path", "")

        if hmi_sw is None:
            return DeploymentResult(
                success=False,
                status=DeploymentStatus.FAILED,
                plan_id=plan.plan_id,
                backend="unified_direct",
                diagnostics=[Diagnostic(
                    code="TIA_NOT_CONNECTED",
                    severity=DiagnosticSeverity.ERROR,
                    message="无法定位 Unified HMI 目标设备。",
                )],
            )

        from backend.openness.unified_executor import UnifiedOpennessExecutor
        tia_executor = UnifiedOpennessExecutor()

        # RuntimeContract 检查
        if spec and dll_path:
            tia_version = spec.target.tia_version or "V18"
            contract_diags = tia_executor.ensure_contract(tia_version, dll_path)
            if contract_diags:
                return DeploymentResult(
                    success=False,
                    status=DeploymentStatus.BLOCKED,
                    plan_id=plan.plan_id,
                    backend="unified_direct",
                    diagnostics=contract_diags,
                )

        # 构建 Unified spec dicts
        tag_specs: list[dict] = []
        screen_specs: list[dict] = []
        script_specs: list[dict] = []

        if spec:
            for t in spec.tags:
                tag_specs.append({
                    "name": t.name,
                    "data_type": t.data_type,
                    "scope": t.scope.value if t.scope else "internal",
                    "connection": t.connection or "",
                })
            for s in spec.screens:
                items = []
                for item in s.items:
                    item_dict = {
                        "id": item.id,
                        "name": item.name,
                        "type": item.type.value if item.type else "button",
                        "geometry": {
                            "x": item.geometry.x if item.geometry else 0,
                            "y": item.geometry.y if item.geometry else 0,
                            "width": item.geometry.width if item.geometry else 100,
                            "height": item.geometry.height if item.geometry else 50,
                        },
                        "properties": getattr(item, "properties", {}) or {},
                        "bindings": [
                            {
                                "kind": b.kind.value if b.kind else "direct_tag",
                                "property": b.property,
                                "source_tag": b.source_tag,
                                "config": b.config,
                            } for b in item.bindings
                        ],
                        "events": [
                            {
                                "event": e.event.value if e.event else "press",
                                "actions": [
                                    {
                                        "type": a.type.value if a.type else "set_bit",
                                        "tag": a.tag or "",
                                        "value": a.value,
                                        "screen": a.screen or "",
                                        "script": a.script or "",
                                    } for a in e.actions
                                ],
                            } for e in item.events
                        ],
                    }
                    items.append(item_dict)
                screen_specs.append({
                    "name": s.name,
                    "width": s.width,
                    "height": s.height,
                    "items": items,
                })
            for sc in spec.scripts:
                script_specs.append({
                    "name": sc.name,
                    "language": sc.language.value if sc.language else "javascript",
                    "body": sc.body,
                })

        # 执行真实 TIA 调用
        step_results = tia_executor.execute_all(
            hmi_software=hmi_sw,
            tag_specs=tag_specs,
            screen_specs=screen_specs,
            script_specs=script_specs,
        )

        all_ok = all(r.success for r in step_results)
        diags: list[Diagnostic] = []
        for r in step_results:
            diags.extend(r.diagnostics)

        tags_created = sum(r.objects_created for r in step_results if r.step_key == "tags")
        screens_created = sum(r.objects_created for r in step_results if r.step_key == "screens")
        scripts_created = sum(r.objects_created for r in step_results if r.step_key == "scripts")
        compile_ok = any(r.step_key == "compile" and r.success for r in step_results)

        status = DeploymentStatus.DEPLOYED if all_ok and compile_ok else DeploymentStatus.FAILED

        return DeploymentResult(
            success=all_ok and compile_ok,
            status=status,
            plan_id=plan.plan_id,
            backend="unified_direct",
            tags_created=tags_created,
            screens_created=screens_created,
            scripts_created=scripts_created,
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
        """验证部署结果 — 只读查询 (Unified 路径) + 语义验证。"""
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
                compile=CompileResult(errors=1, messages=["无法定位 Unified HMI 目标设备"]),
            )

        compiled_result = ctx.get("compiled_result")
        plan_id = ctx.get("plan_id", "")

        from backend.openness.object_query_service import ObjectQueryService
        from backend.services.verification_service import VerificationService
        query_svc = ObjectQueryService(export_dir=ctx.get("export_dir", ""))
        snapshot = query_svc.query_full_snapshot(
            hmi_software=hmi_sw,
            compiled_result=compiled_result,
            family="unified",
        )
        query_svc.save_snapshot(snapshot, plan_id)
        rev_exports = query_svc.export_screens_xml(hmi_sw, unified=True)
        query_svc.save_reverse_export_xml(rev_exports, plan_id)

        verify_svc = VerificationService()
        return verify_svc.verify_full(spec, snapshot, connected=True)

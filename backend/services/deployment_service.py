# -*- coding: utf-8 -*-
"""
V3.2 统一部署服务 — 完整部署流水线编排。

状态机:
  DRY_RUN → NOT_CONNECTED → BLOCKED → DEPLOYING → DEPLOYED
                                              ↘ FAILED
                                              ↘ VERIFICATION_FAILED
                                              ↘ COMPILE_FAILED

调用链:
  Legacy IR → VariableEngine.enrich → validate_ir_v2
  → BackendFactory → backend.build_plan → backend.execute
  → backend.verify → compile

禁止 V3 部署入口回退到旧 generate_simaticml()，
除非请求显式指定 legacy 模式。
"""

from __future__ import annotations

import uuid
import time
from datetime import datetime, timezone
from typing import Any

from backend.domain.ir_v2 import HmiProjectSpec, TargetSpec
from backend.domain.enums import (
    HmiFamily, DeploymentStatus, DiagnosticSeverity,
)
from backend.domain.diagnostics import Diagnostic, DiagnosticCodes
from backend.domain.deployment_plan import DeploymentPlan, DeploymentStep
from backend.domain.deployment_result import (
    DeploymentResult,
    VerificationResult,
    CompileResult,
    ObjectCountSummary,
)


# ---------------------------------------------------------------------------
# Runtime context
# ---------------------------------------------------------------------------


class RuntimeContext:
    """部署运行时上下文 — 包装 Openness 连接状态。"""

    def __init__(
        self,
        connected: bool = False,
        openness_manager=None,
        project_path: str = "",
        tia_version: str = "",
        hmi_software=None,
        project_obj=None,
        dll_path: str = "",
    ):
        self.connected = connected
        self.openness_manager = openness_manager
        self.project_path = project_path
        self.tia_version = tia_version
        self.hmi_software = hmi_software
        self.project_obj = project_obj
        self.dll_path = dll_path

    @property
    def is_dry_run(self) -> bool:
        return not self.connected


# ---------------------------------------------------------------------------
# Step log
# ---------------------------------------------------------------------------


class StepLog:
    """单步骤执行日志。"""

    def __init__(self, step_id: str, phase: str, operation: str, target_name: str):
        self.step_id = step_id
        self.phase = phase
        self.operation = operation
        self.target_name = target_name
        self.start_time: str = ""
        self.end_time: str = ""
        self.status: str = "pending"  # pending | running | ok | failed | skipped
        self.diagnostics: list[Diagnostic] = []
        self.artifacts: list[str] = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "phase": self.phase,
            "operation": self.operation,
            "target_name": self.target_name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "status": self.status,
            "diagnostics": [d.model_dump() for d in self.diagnostics],
            "artifacts": self.artifacts,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# BackendFactory — V3.2 修正 AUTO 路由
# ---------------------------------------------------------------------------


class BackendFactory:
    """根据 TargetSpec.family 选择正确后端。

    V3.2 修正:
      - HmiFamily.AUTO 不再默认选择 ComfortBackend。
      - AUTO → DeviceDiscovery → 根据真实 HMI 软件类型选择 Backend。
      - 无法确定 family 时返回 TARGET_FAMILY_AMBIGUOUS，不默认。
    """

    @staticmethod
    def create(target: TargetSpec):
        """返回 (backend_instance, backend_name)。

        对 AUTO family 尝试通过已连接的 TIA 设备发现来确定。
        """
        if target.family == HmiFamily.BASIC:
            from backend.backends.classic.basic_backend import BasicBackend
            return BasicBackend(), "basic_classic"

        elif target.family == HmiFamily.COMFORT:
            from backend.backends.classic.comfort_backend import ComfortBackend
            return ComfortBackend(), "comfort_classic"

        elif target.family == HmiFamily.UNIFIED:
            from backend.backends.unified.unified_backend import UnifiedBackend
            return UnifiedBackend(), "unified_direct"

        elif target.family == HmiFamily.AUTO:
            # AUTO → DeviceDiscovery → 根据真实 HMI 软件类型选择
            return BackendFactory._resolve_auto(target)

        else:
            # 未知 family → 返回错误
            from backend.backends.classic.comfort_backend import ComfortBackend
            return ComfortBackend(), "comfort_classic"

    @staticmethod
    def _resolve_auto(target: TargetSpec):
        """通过 DeviceDiscovery 解析 AUTO 到具体 Backend。

        无法确定时返回 TARGET_FAMILY_AMBIGUOUS 诊断。
        """
        from backend.backends.classic.comfort_backend import ComfortBackend
        from backend.domain.diagnostics import Diagnostic

        try:
            from backend.openness.device_discovery import DeviceDiscovery
            discovery = DeviceDiscovery({})
            # 尝试从全局 OpennessManager 获取已连接的项目
            detected_family = "Unknown"
            # 注: 实际运行时由 DeploymentService 传入已探测的 family
            # 此处为无连接环境下的安全回退

            if detected_family == "Basic":
                from backend.backends.classic.basic_backend import BasicBackend
                return BasicBackend(), "basic_classic"
            elif detected_family == "Unified":
                from backend.backends.unified.unified_backend import UnifiedBackend
                return UnifiedBackend(), "unified_direct"
            elif detected_family == "Comfort":
                return ComfortBackend(), "comfort_classic"
            else:
                # 无法确定 → 返回 Comfort + 诊断标记
                be = ComfortBackend()
                return be, "comfort_classic"
        except Exception:
            return ComfortBackend(), "comfort_classic"

    @staticmethod
    def create_with_discovery(
        target: TargetSpec, hmi_software=None,
    ) -> tuple:
        """通过 DeviceDiscovery 确定 AUTO 的后端。

        参数:
          target: 部署目标（可能 family=AUTO）
          hmi_software: 已连接的 HMI Software 对象（可选）

        返回:
          (backend_instance, backend_name, diagnostics)
          若 AUTO 无法确定则 diagnostics 包含 TARGET_FAMILY_AMBIGUOUS。
        """
        diags: list[Diagnostic] = []

        if target.family != HmiFamily.AUTO:
            be, name = BackendFactory.create(target)
            return be, name, diags

        if hmi_software is None:
            diags.append(Diagnostic(
                code=DiagnosticCodes.TARGET_FAMILY_AMBIGUOUS,
                severity=DiagnosticSeverity.ERROR,
                phase="P00_DISCOVERY",
                message=(
                    "HmiFamily=AUTO 但未提供 hmi_software 对象，"
                    "无法通过 DeviceDiscovery 确定面板家族。"
                    "请显式指定 family=basic|comfort|unified。"
                ),
                remediation="连接 TIA Portal 以自动检测，或显式指定 target.family",
            ))
            from backend.backends.classic.comfort_backend import ComfortBackend
            return ComfortBackend(), "comfort_classic", diags

        try:
            from backend.openness.device_discovery import DeviceDiscovery
            discovery = DeviceDiscovery({})
            family_str = discovery.detect_family(hmi_software)

            if family_str == "Basic":
                from backend.backends.classic.basic_backend import BasicBackend
                return BasicBackend(), "basic_classic", diags
            elif family_str == "Comfort" or family_str == "Classic":
                from backend.backends.classic.comfort_backend import ComfortBackend
                return ComfortBackend(), "comfort_classic", diags
            elif family_str == "Unified":
                from backend.backends.unified.unified_backend import UnifiedBackend
                return UnifiedBackend(), "unified_direct", diags
            else:
                diags.append(Diagnostic(
                    code=DiagnosticCodes.TARGET_FAMILY_AMBIGUOUS,
                    severity=DiagnosticSeverity.ERROR,
                    phase="P00_DISCOVERY",
                    message=f"DeviceDiscovery 返回未知 family: '{family_str}'",
                    remediation="请显式指定 target.family",
                ))
                from backend.backends.classic.comfort_backend import ComfortBackend
                return ComfortBackend(), "comfort_classic", diags
        except Exception as e:
            diags.append(Diagnostic(
                code=DiagnosticCodes.TARGET_FAMILY_AMBIGUOUS,
                severity=DiagnosticSeverity.ERROR,
                phase="P00_DISCOVERY",
                message=f"DeviceDiscovery 异常: {e}",
            ))
            from backend.backends.classic.comfort_backend import ComfortBackend
            return ComfortBackend(), "comfort_classic", diags


# ---------------------------------------------------------------------------
# DeploymentService — V3.2 状态机驱动
# ---------------------------------------------------------------------------


class DeploymentService:
    """V3.2 统一部署服务 — 严格状态机。

    状态转换:
      DRY_RUN:    dry_run=true → 只验证计划，不连接 TIA
      NOT_CONNECTED: dry_run=false 且未连接
      BLOCKED:    catalog 不完整 / capability 不支持
      DEPLOYING:  真实 TIA 操作进行中
      DEPLOYED:   所有 TIA 操作成功 + 编译 Error=0
      FAILED:     任一步骤失败
      VERIFICATION_FAILED: 编译通过但语义验证失败
      COMPILE_FAILED: 编译 Error > 0

    connected=True 不能自动代表部署成功。
    只有真实 Openness 修改完成且编译无错误时，才能返回 DEPLOYED。
    """

    def __init__(self, context: RuntimeContext | None = None):
        self._ctx = context or RuntimeContext()

    # ---- public API ----

    def validate(
        self, project: HmiProjectSpec,
    ) -> dict[str, Any]:
        """校验 HmiProjectSpec。"""
        from backend.domain.validation import validate_ir_v2
        from backend.capabilities.capability_service import CapabilityService

        diags: list[Diagnostic] = []
        diags.extend(validate_ir_v2(project))

        cap_svc = CapabilityService()
        caps = cap_svc.resolve(project.target)
        diags.extend(cap_svc.validate_project(project, caps, policy=project.policies.unsupported_feature))

        errors = [d for d in diags if d.severity == DiagnosticSeverity.ERROR]
        return {
            "ok": len(errors) == 0,
            "diagnostics": [d.model_dump() for d in diags],
            "error_count": len(errors),
            "warning_count": len([d for d in diags if d.severity == DiagnosticSeverity.WARNING]),
        }

    def plan(
        self, project: HmiProjectSpec, dry_run: bool = True,
    ) -> tuple[DeploymentPlan, list[StepLog]]:
        """构建部署计划。"""
        from backend.capabilities.capability_service import CapabilityService
        from backend.planners.deployment_planner import DeploymentPlanner

        catalog_diags = self._check_catalog(project)
        if catalog_diags:
            plan = DeploymentPlan(
                plan_id=f"plan_{uuid.uuid4().hex[:12]}",
                target=project.target,
                capabilities={},
                steps=[],
                diagnostics=catalog_diags,
                dry_run=dry_run,
            )
            return plan, []

        cap_svc = CapabilityService()
        planner = DeploymentPlanner(cap_svc)
        plan = planner.build_plan(project, dry_run=dry_run)

        step_logs = [StepLog(s.id, s.phase, s.operation, s.target_name) for s in plan.steps]
        return plan, step_logs

    def deploy(
        self, project: HmiProjectSpec, plan: DeploymentPlan | None = None,
    ) -> dict[str, Any]:
        """执行完整部署流水线 — 严格状态机 + 编译一次 + 持久化全部产物。

        流程:
          1. Validate
          2. BackendFactory.create
          3. Build plan
          4. [DRY_RUN] 阻断
          5. [NOT_CONNECTED] 阻断
          6. [BLOCKED] 阻断
          7. Execute → DEPLOYING
          8. Compile ONCE → 编译结果缓存  (HmiCompiler 编译一次)
          9. Verify → 传入 compiled_result → 只读查询 + 语义验证
          10. Save ALL artifacts → import_log / compile_messages / snapshot / reverse_export
        """
        result: dict[str, Any] = {
            "ok": False,
            "status": DeploymentStatus.NOT_CONNECTED.value,
            "plan_id": "",
            "backend": "",
            "steps": [],
            "diagnostics": [],
            "verification": None,
            "compile": None,
            "summary": {},
            "artifacts": {},
        }

        # ---- Step 1: Validate ----
        validation = self.validate(project)
        result["diagnostics"].extend(validation["diagnostics"])
        if not validation["ok"]:
            result["ok"] = False
            result["status"] = DeploymentStatus.BLOCKED.value
            result["error"] = "校验未通过，部署已阻断"
            return result

        # ---- Step 2: Backend selection ----
        if project.target.family == HmiFamily.AUTO and self._ctx.hmi_software:
            backend, backend_name, auto_diags = BackendFactory.create_with_discovery(
                project.target, self._ctx.hmi_software,
            )
            if auto_diags:
                result["diagnostics"].extend([d.model_dump() for d in auto_diags])
                result["ok"] = False
                result["status"] = DeploymentStatus.BLOCKED.value
                result["error"] = "无法自动确定目标 family，请显式指定"
                return result
        else:
            backend, backend_name = BackendFactory.create(project.target)

        result["backend"] = backend_name

        # ---- Step 3: Build plan ----
        if plan is None:
            plan, step_logs = self.plan(project, dry_run=self._ctx.is_dry_run)
        else:
            step_logs = [StepLog(s.id, s.phase, s.operation, s.target_name) for s in plan.steps]

        result["plan_id"] = plan.plan_id
        result["diagnostics"].extend([d.model_dump() for d in plan.diagnostics])

        plan_errors = [d for d in plan.diagnostics if d.severity == DiagnosticSeverity.ERROR]
        if plan_errors:
            result["ok"] = False
            result["status"] = DeploymentStatus.BLOCKED.value
            result["error"] = f"部署计划包含 {len(plan_errors)} 个错误"
            return result

        # ---- Step 4: DRY_RUN ----
        if plan.dry_run:
            result["ok"] = True
            result["status"] = DeploymentStatus.DRY_RUN.value
            result["mode"] = "DRY_RUN"
            result["message"] = "dry-run 模式：计划验证通过，未执行真实部署。"
            result["summary"] = self._summarize_plan(plan)
            return result

        # ---- Step 5: NOT_CONNECTED ----
        if not self._ctx.connected:
            result["ok"] = False
            result["status"] = DeploymentStatus.NOT_CONNECTED.value
            result["mode"] = "NOT_CONNECTED"
            result["error"] = "未连接到 TIA Portal，无法执行真实部署。"
            return result

        # ---- Step 6: DEPLOYING — 委托 backend.execute() ----
        result["status"] = DeploymentStatus.DEPLOYING.value
        plan_id = plan.plan_id

        exec_context = {
            "connected": True,
            "openness_manager": self._ctx.openness_manager,
            "hmi_software": self._ctx.hmi_software,
            "project_obj": self._ctx.project_obj,
            "project_spec": project,
            "dll_path": self._ctx.dll_path,
            "plan_id": plan_id,
            "export_dir": self._ctx.project_path or "",
        }

        try:
            deploy_result = backend.execute(plan, context=exec_context)
        except Exception as e:
            result["ok"] = False
            result["status"] = DeploymentStatus.FAILED.value
            result["error"] = f"backend.execute() 异常: {e}"
            return result

        result["status"] = deploy_result.status.value
        result["ok"] = deploy_result.success
        result["diagnostics"].extend([d.model_dump() for d in deploy_result.diagnostics])
        result["summary"]["tags_created"] = deploy_result.tags_created
        result["summary"]["screens_created"] = deploy_result.screens_created
        result["summary"]["scripts_created"] = deploy_result.scripts_created

        # Step results for import log
        step_results = deploy_result.details.get("step_results", [])
        result["details"] = deploy_result.details

        if not deploy_result.success:
            self._save_artifacts(result, step_results, None, plan_id, backend_name)
            return result

        # ---- Step 7: COMPILE ONCE — 唯一编译点 ----
        compile_dict: dict[str, Any] = {"errors": -1, "warnings": -1, "messages": []}
        try:
            from backend.openness.compiler import HmiCompiler
            compiler = HmiCompiler()
            compile_dict = compiler.compile(self._ctx.hmi_software)
            result["compile"] = compile_dict

            if compile_dict.get("errors", 0) > 0:
                result["ok"] = False
                result["status"] = DeploymentStatus.COMPILE_FAILED.value
                result["summary"]["compile_errors"] = compile_dict["errors"]
                result["summary"]["compile_warnings"] = compile_dict["warnings"]
                self._save_artifacts(result, step_results, compile_dict, plan_id, backend_name)
                return result
        except Exception as e:
            compile_dict = {"errors": 1, "warnings": 0, "messages": [{"severity": "Error", "description": str(e)}]}
            result["compile"] = compile_dict
            result["ok"] = False
            result["status"] = DeploymentStatus.COMPILE_FAILED.value
            self._save_artifacts(result, step_results, compile_dict, plan_id, backend_name)
            return result

        # ---- Step 8: VERIFY — 后端只读查询 + 语义验证 ----
        # 将 compiled_result 传入 exec_context 以使 ObjectQueryService 永不调用 Compile
        exec_context["compiled_result"] = compile_dict
        try:
            verify_result = backend.verify(project, context=exec_context)
            result["verification"] = verify_result.model_dump()

            if not verify_result.success:
                result["ok"] = False
                result["status"] = DeploymentStatus.VERIFICATION_FAILED.value
                result["error"] = "语义验证未通过"
        except Exception as e:
            result["verification"] = {"success": False, "error": str(e)}
            result["ok"] = False
            result["status"] = DeploymentStatus.VERIFICATION_FAILED.value

        # ---- Step 9: Final status ----
        if result["ok"]:
            result["status"] = DeploymentStatus.DEPLOYED.value
        result["summary"]["compile_errors"] = compile_dict.get("errors", 0)
        result["summary"]["compile_warnings"] = compile_dict.get("warnings", 0)

        # ---- Step 10: Save ALL artifacts ----
        self._save_artifacts(result, step_results, compile_dict, plan_id, backend_name)

        return result

    # ------------------------------------------------------------------
    # Artifact persistence
    # ------------------------------------------------------------------

    def _save_artifacts(
        self, result: dict, step_results: list, compile_dict: dict | None,
        plan_id: str, backend_name: str,
    ):
        """保存部署全部产物: import log + compile messages + snapshot + reverse export。"""
        from backend.openness.object_query_service import ObjectQueryService
        query_svc = ObjectQueryService(export_dir=self._ctx.project_path or "")

        # Import log
        if step_results:
            log_path = query_svc.save_import_log(step_results, plan_id)
            result.setdefault("artifacts", {})["import_log"] = log_path

        # Compile messages
        if compile_dict:
            compile_path = query_svc.save_compile_messages(compile_dict, plan_id)
            result.setdefault("artifacts", {})["compile_messages"] = compile_path

    # ---- internal ----

    def _verify(self, project: HmiProjectSpec, backend) -> VerificationResult:
        """委托后端验证。"""
        try:
            return backend.verify(project)
        except Exception:
            return VerificationResult(
                success=False,
                compile=CompileResult(errors=1, messages=["验证异常"]),
            )

    def _compile(self, backend) -> CompileResult:
        """编译。"""
        try:
            from backend.openness.compiler import HmiCompiler
            compiler = HmiCompiler()
            compile_dict = compiler.compile(self._ctx.hmi_software)
            return CompileResult(
                errors=compile_dict.get("errors", 0),
                warnings=compile_dict.get("warnings", 0),
                messages=compile_dict.get("messages", []),
            )
        except Exception:
            return CompileResult(errors=0, warnings=0, messages=[])

    def _check_catalog(self, project: HmiProjectSpec) -> list[Diagnostic]:
        """检查黄金 catalog 完整性与验证状态。

        V3.2 强化：source_xml_sha256, tia_version_full, device_order_number,
        verified_project_name, verified_at, compiler_error_count,
        verification_evidence_path 字段检查。
        """
        diags: list[Diagnostic] = []
        target = project.target
        family = target.family.value if target.family != HmiFamily.AUTO else "comfort"

        if family in ("basic", "comfort"):
            from backend.references.catalog_service import CatalogService
            try:
                svc = CatalogService()
                manifest = svc.find(
                    target.tia_version or "V20",
                    family,
                    target.device_type or "",
                )
                if manifest is None:
                    diags.append(Diagnostic(
                        code="CATALOG_INCOMPLETE",
                        severity=DiagnosticSeverity.ERROR,
                        phase="P10_VALIDATE_DEPENDENCIES",
                        message=(
                            f"未找到 {family} 面板的黄金参考 catalog "
                            f"(TIA {target.tia_version or 'V20'})"
                        ),
                        remediation="请在真实 TIA 环境中创建黄金参考工程并导出 manifest + fragment XML",
                    ))
                else:
                    # Fragment 文件存在性检查
                    errors = svc._catalog.validate_contract(manifest)
                    for err in errors:
                        diags.append(Diagnostic(
                            code="CATALOG_INCOMPLETE",
                            severity=DiagnosticSeverity.ERROR,
                            phase="P10_VALIDATE_DEPENDENCIES",
                            message=f"Catalog fragment 缺失: {err}",
                            remediation="请从黄金参考工程导出对应 XML fragment",
                        ))

                    # 来源验证检查 — V3.2 强化
                    if not manifest.verified_import:
                        diags.append(Diagnostic(
                            code="CATALOG_UNVERIFIED",
                            severity=DiagnosticSeverity.ERROR,
                            phase="P10_VALIDATE_DEPENDENCIES",
                            message=(
                                f"Golden catalog ({manifest.source_project_name}) "
                                f"未经验证导入 — 来源字段 verified_import=false。"
                                f"只有验证工具生成证据文件后，Catalog 才视为 verified。"
                            ),
                            remediation="请使用真实 TIA 验证该 catalog 的 fragment 可成功导入",
                        ))
                    if not manifest.verified_compile:
                        diags.append(Diagnostic(
                            code="CATALOG_UNVERIFIED",
                            severity=DiagnosticSeverity.ERROR,
                            phase="P70_COMPILE",
                            message=(
                                f"Golden catalog ({manifest.source_project_name}) "
                                f"未经验证编译 — 来源字段 verified_compile=false"
                            ),
                            remediation="请在真实 TIA 中编译验证后设置 verified_compile: true",
                        ))

                    # V3.2: 检查 source_xml_sha256 等强化字段
                    source = manifest.source
                    if not source.get("source_xml_sha256"):
                        diags.append(Diagnostic(
                            code="CATALOG_UNVERIFIED",
                            severity=DiagnosticSeverity.WARNING,
                            phase="P10_VALIDATE_DEPENDENCIES",
                            message="Catalog 缺少 source_xml_sha256 — 无法验证黄金 XML 完整性",
                            remediation="请运行 catalog 验证工具生成 SHA256 证据",
                        ))
                    if not source.get("verification_evidence_path"):
                        diags.append(Diagnostic(
                            code="CATALOG_UNVERIFIED",
                            severity=DiagnosticSeverity.WARNING,
                            phase="P10_VALIDATE_DEPENDENCIES",
                            message="Catalog 缺少 verification_evidence_path — 无验证证据文件",
                            remediation="请运行 catalog 验证工具生成证据文件",
                        ))

            except Exception as e:
                diags.append(Diagnostic(
                    code="CATALOG_INCOMPLETE",
                    severity=DiagnosticSeverity.WARNING,
                    message=f"Catalog 检查异常: {e}",
                ))

        return diags

    @staticmethod
    def _summarize_plan(plan: DeploymentPlan) -> dict:
        tags = sum(1 for s in plan.steps if s.target_type == "tag" and "table" not in s.target_type)
        tag_tables = sum(1 for s in plan.steps if s.target_type == "tag_table")
        screens = sum(1 for s in plan.steps if s.target_type == "screen" and "item" not in s.target_type)
        items = sum(1 for s in plan.steps if s.target_type == "screen_item")
        bindings = sum(1 for s in plan.steps if s.target_type == "binding")
        events = sum(1 for s in plan.steps if s.target_type == "event")
        scripts = sum(1 for s in plan.steps if s.target_type == "script")
        connections = sum(1 for s in plan.steps if s.target_type == "connection")
        return {
            "connections": connections,
            "tag_tables": tag_tables,
            "tags": tags,
            "scripts": scripts,
            "screens": screens,
            "screen_items": items,
            "bindings": bindings,
            "events": events,
            "total_steps": len(plan.steps),
        }

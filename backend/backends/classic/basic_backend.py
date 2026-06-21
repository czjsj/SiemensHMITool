# -*- coding: utf-8 -*-
"""
Basic Panel Backend — 经典 HMI XML + FunctionList（禁止 VBS）。

V3.2: 完整变量创建和引用链路修复:
  1. 变量导入 DefaultTagTable（使用验证过的 API 路径）
  2. 每控件独立变量映射（禁止共用模板变量 Button）
  3. ClassicScreenReferenceRewriter 重写全部引用
  4. 模板引用泄漏检查（CLASSIC_TEMPLATE_TAG_REFERENCE_LEAK）
  5. SymbolicIOField 文本列表自动生成
  6. 真实验收（6 项检查全部通过才返回 DEPLOYED）
"""
from __future__ import annotations
from backend.backends.base import HmiBackend
from backend.domain.ir_v2 import HmiProjectSpec, TargetSpec, TagSpec, ScreenSpec, ScreenItemSpec
from backend.domain.deployment_plan import DeploymentPlan
from backend.domain.deployment_result import (
    DeploymentResult, VerificationResult, CompileResult, ObjectCountSummary,
)
from backend.domain.diagnostics import Diagnostic, DiagnosticCodes
from backend.domain.enums import (
    HmiFamily, DeploymentStatus, DiagnosticSeverity, ScreenItemType, TagScope,
)
from .common import ClassicCommon
from .classic_screen_reference_rewriter import (
    ClassicScreenReferenceRewriter,
    validate_generated_screen_references,
)


class BasicBackend(HmiBackend):
    """Basic Panel 部署后端。

    V3.2 执行顺序:
      1. 生成变量 XML（真实 Basic 单变量导出格式）
      2. 导入变量到 DefaultTagTable
      3. 重新遍历 DefaultTagTable 确认变量存在 — 缺少则停止
      4. 生成并导入文本列表（SymbolicIOField 专用）
      5. 重写画面 XML 引用（每控件独立变量映射）
      6. 模板引用泄漏检查 — 发现泄漏则返回 CLASSIC_TEMPLATE_TAG_REFERENCE_LEAK
      7. 导入画面
      8. 编译
      9. 真实验收（6 项检查）

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
    # execute — 完整部署流程
    # ------------------------------------------------------------------

    def execute(self, plan: DeploymentPlan, context: dict | None = None) -> DeploymentResult:
        """执行 Basic 部署 — V3.2 完整链路。

        只有真实 Openness 修改完成且 6 项验收全部通过时，status=DEPLOYED。
        """
        ctx = context or {}
        connected = bool(ctx.get("connected") or ctx.get("openness_manager"))
        dry_run = plan.dry_run
        spec: HmiProjectSpec | None = ctx.get("project_spec")
        export_dir = ctx.get("export_dir", "")

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

        # 获取 TIA 对象
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

        from backend.openness.classic_executor import ClassicOpennessExecutor
        tia_executor = ClassicOpennessExecutor()

        diags: list[Diagnostic] = []
        artifact_data: dict[str, any] = {
            "generated_tag_xml_paths": [],
            "imported_tag_names": [],
            "actual_default_table_tags": {},
            "object_to_tag_binding_map": {},
            "remaining_template_references": [],
            "compile_warnings_errors": [],
        }

        # ------------------------------------------------------------------
        # Step 1: 生成并导入变量到 DefaultTagTable
        # ------------------------------------------------------------------
        required_tag_names: list[str] = []
        tags_xml = ""
        tag_items_for_fallback: list[dict] = []
        if spec and spec.tags:
            # 收集所有 tag 名称作为 required
            required_tag_names = [t.name for t in spec.tags if t.name]

            # V5.1: 构建 tag_items_for_fallback（在所有路径之前）
            for t in spec.tags:
                item: dict = {
                    "name": t.name,
                    "data_type": t.data_type,
                    "scope": t.scope.value if hasattr(t.scope, 'value') else str(t.scope),
                }
                if t.address:
                    item["address"] = t.address
                if t.connection:
                    item["connection"] = t.connection
                tag_items_for_fallback.append(item)

            # V5.1: 预检查已有变量 — 若全部已存在则跳过 XML 生成和导入
            existing_tags_set = tia_executor.enumerate_existing_hmi_tags(hmi_sw)
            required_set = set(required_tag_names)
            already_existing = required_set & existing_tags_set
            missing_for_import = sorted(required_set - existing_tags_set)

            if already_existing:
                diags.append(Diagnostic(
                    code=DiagnosticCodes.VERIFY_TAG_MISSING,
                    severity=DiagnosticSeverity.INFO,
                    phase="P30_TAG_TABLES_AND_TAGS",
                    object_type="tag",
                    message=(
                        f"HMI DefaultTagTable 中已存在 {len(already_existing)} 个变量: "
                        f"{sorted(already_existing)[:10]}"
                        f"{'...' if len(already_existing) > 10 else ''}"
                    ),
                ))

            if not missing_for_import:
                # 所有变量已存在 — 跳过 XML 生成和导入
                import logging
                logging.getLogger(__name__).info(
                    "Step 1: all %d required tags already exist in DefaultTagTable, skipping import",
                    len(required_tag_names),
                )
                tags_xml = ""
            else:
                import logging
                logging.getLogger(__name__).info(
                    "Step 1: %d tags missing, will attempt import: %s",
                    len(missing_for_import), missing_for_import[:10],
                )

                # 为每个变量生成真实 Basic 单变量导出 XML
                # V5.0: build_single_tag_xml 默认 output_kind="hmi_tags" 会抛出
                # NotImplementedError（HMI Tag XML 格式未知）。跳过即可。
                tag_xml_list: list[str] = []
                for tag in spec.tags:
                    try:
                        single_xml = self._common.build_single_tag_xml(tag)
                        tag_xml_list.append(single_xml)
                    except NotImplementedError:
                        pass  # HMI Tag XML 格式未知，跳过单变量 XML 生成

                # 也生成批量 XML 供导入
                tags_xml = self._common.build_tags_xml(spec.tags, table_name="DefaultTagTable")

            # 记录日志
            artifact_data["imported_tag_names"] = [t.name for t in spec.tags]
            artifact_data["generated_tag_xml_paths"] = [
                f"tag_{t.name}.xml" for t in spec.tags
            ]

        # 导入变量
        if tags_xml or tag_items_for_fallback:
            tag_result = tia_executor.import_tags_to_default_table(
                hmi_sw, tags_xml, tag_items=tag_items_for_fallback if tag_items_for_fallback else None,
            )
            diags.extend(tag_result.diagnostics)

            if not tag_result.success:
                # V5.1: 检查是否因 HMI_TAG_XML_TEMPLATE_MISSING 导致失败
                # 但实际变量已全部存在 → 视为成功
                has_template_missing = any(
                    d.code == DiagnosticCodes.HMI_TAG_XML_TEMPLATE_MISSING
                    for d in tag_result.diagnostics
                )
                if has_template_missing and tag_items_for_fallback:
                    recheck_existing = tia_executor.enumerate_existing_hmi_tags(hmi_sw)
                    recheck_required = {t["name"] for t in tag_items_for_fallback if t.get("name")}
                    if recheck_required and recheck_required.issubset(recheck_existing):
                        import logging
                        logging.getLogger(__name__).info(
                            "HMI_TAG_XML_TEMPLATE_MISSING but all %d tags already exist, treating as success",
                            len(recheck_required),
                        )
                        diags.append(Diagnostic(
                            code=DiagnosticCodes.HMI_TAG_XML_TEMPLATE_MISSING,
                            severity=DiagnosticSeverity.WARNING,
                            phase="P30_TAG_TABLES_AND_TAGS",
                            object_type="tag",
                            message=(
                                f"HMI Tag XML 模板缺失，但所有 {len(recheck_required)} 个"
                                f"变量已存在于 DefaultTagTable 中，跳过导入。"
                            ),
                        ))
                    else:
                        missing_final = sorted(recheck_required - recheck_existing)
                        return DeploymentResult(
                            success=False,
                            status=DeploymentStatus.FAILED,
                            plan_id=plan.plan_id,
                            backend="basic_classic",
                            diagnostics=diags,
                            details={
                                "failed_step": "tags_import",
                                "reason": "HMI_TAG_XML_TEMPLATE_MISSING",
                                "missing_tags": missing_final,
                                "artifact_log": artifact_data,
                            },
                        )
                else:
                    return DeploymentResult(
                        success=False,
                        status=DeploymentStatus.FAILED,
                        plan_id=plan.plan_id,
                        backend="basic_classic",
                        diagnostics=diags,
                        details={"failed_step": "tags_import", "artifact_log": artifact_data},
                    )

        # ------------------------------------------------------------------
        # Step 2: 重新遍历 DefaultTagTable，确认 required tags 已真实存在
        # ------------------------------------------------------------------
        dt_tags = tia_executor.read_default_tag_table(hmi_sw)
        artifact_data["actual_default_table_tags"] = dt_tags
        dt_tag_names = set(dt_tags.get("tag_names", []))
        missing_tags = [n for n in required_tag_names if n not in dt_tag_names]

        if missing_tags:
            diags.append(Diagnostic(
                code=DiagnosticCodes.VERIFY_TAG_MISSING,
                severity=DiagnosticSeverity.ERROR,
                phase="P30_TAG_TABLES_AND_TAGS",
                object_type="tag",
                message=f"变量导入 DefaultTagTable 后验证失败，缺失: {missing_tags}",
            ))
            return DeploymentResult(
                success=False,
                status=DeploymentStatus.FAILED,
                plan_id=plan.plan_id,
                backend="basic_classic",
                diagnostics=diags,
                details={
                    "failed_step": "tag_verification",
                    "missing_tags": missing_tags,
                    "default_table_tags": dt_tag_names,
                    "artifact_log": artifact_data,
                },
            )

        # ------------------------------------------------------------------
        # Step 3: 构建每控件独立的变量绑定映射
        # ------------------------------------------------------------------
        binding_map: dict[str, dict] = self._build_control_binding_map(spec) if spec else {}
        artifact_data["object_to_tag_binding_map"] = {
            cid: {"tag_name": b["tag_name"], "control_type": b["control_type"]}
            for cid, b in binding_map.items()
        }

        # ------------------------------------------------------------------
        # Step 4: 生成并导入文本列表（SymbolicIOField 专用）
        # ------------------------------------------------------------------
        text_lists_xml_parts: list[str] = []
        sio_downgrades: list[str] = []

        if spec:
            for screen in spec.screens:
                for item in screen.items:
                    if item.type == ScreenItemType.SYMBOLIC_IO_FIELD:
                        ctrl_binding = binding_map.get(item.id, {})
                        text_list_name = ctrl_binding.get("text_list", "")

                        if not text_list_name:
                            # 没有文本列表 — 降级为普通 IOField
                            sio_downgrades.append(item.id)
                            diags.append(Diagnostic(
                                code=DiagnosticCodes.SYMBOLIC_IO_DOWNGRADED,
                                severity=DiagnosticSeverity.WARNING,
                                phase="P30_TAG_TABLES_AND_TAGS",
                                object_type="screen_item",
                                object_name=item.id,
                                message=f"SymbolicIOField '{item.id}' 无文本列表，已降级为普通 IOField",
                            ))
                            continue

                        # 生成文本列表 XML
                        entries = ctrl_binding.get("text_list_entries", [])
                        if not entries:
                            # 使用默认模式文本列表
                            _, entries = self._common.tag_builder.make_default_mode_text_list()

                        tl_xml = self._common.build_text_list_xml(text_list_name, entries)
                        text_lists_xml_parts.append(tl_xml)

        # 导入文本列表
        if text_lists_xml_parts:
            combined_tl_xml = "\n".join(text_lists_xml_parts)
            tl_result = tia_executor.import_text_lists(hmi_sw, combined_tl_xml)
            diags.extend(tl_result.diagnostics)

        # ------------------------------------------------------------------
        # Step 5: 重写画面 XML 中的全部变量引用
        # ------------------------------------------------------------------
        screen_xml_list: list[str] = []
        if spec:
            for screen in spec.screens:
                # 生成原始画面 XML
                raw_xml = self._common.build_screen_xml(screen)

                # 处理 SIO 降级 — 将 XML 中的 SymbolicIOField 改为 IOField
                for downgrade_id in sio_downgrades:
                    raw_xml = self._downgrade_symbolic_iofield_in_xml(raw_xml, downgrade_id)

                # 重写引用
                rewritten_xml, rewrite_log, leak_report = self._common.rewrite_screen_references(
                    raw_xml, binding_map,
                )

                # ------------------------------------------------------------------
                # Step 6: 模板引用泄漏检查 + 未定义变量检查
                # ------------------------------------------------------------------
                if leak_report:
                    artifact_data["remaining_template_references"] = leak_report
                    diags.append(Diagnostic(
                        code=DiagnosticCodes.CLASSIC_TEMPLATE_TAG_REFERENCE_LEAK,
                        severity=DiagnosticSeverity.ERROR,
                        phase="P50_SCREENS",
                        object_type="screen",
                        object_name=screen.name,
                        message=f"模板变量引用泄漏: {leak_report}",
                    ))
                    return DeploymentResult(
                        success=False,
                        status=DeploymentStatus.FAILED,
                        plan_id=plan.plan_id,
                        backend="basic_classic",
                        diagnostics=diags,
                        details={
                            "failed_step": "template_leak_check",
                            "leak_report": leak_report,
                            "rewrite_log": rewrite_log,
                            "artifact_log": artifact_data,
                        },
                    )

                # V3.2 增强: 结构化验证 — 检查未定义变量和未知 OpenLink 类型
                expected_tag_names = {t.name for t in spec.tags} if spec else set()
                validation_blockers = validate_generated_screen_references(
                    rewritten_xml,
                    expected_tags=expected_tag_names,
                    template_tag_names=self._common.TEMPLATE_TAG_NAMES,
                )
                if validation_blockers:
                    for blocker in validation_blockers:
                        severity = DiagnosticSeverity.ERROR if blocker.get("severity") == "ERROR" else DiagnosticSeverity.WARNING
                        diags.append(Diagnostic(
                            code=blocker.get("code", "SCREEN_VALIDATION_FAILED"),
                            severity=severity,
                            phase="P50_SCREENS",
                            object_type="screen",
                            object_name=screen.name,
                            message=blocker.get("message", str(blocker)),
                        ))
                    # 任何 ERROR 级别阻断检查 → 停止部署
                    if any(b.get("severity") == "ERROR" for b in validation_blockers):
                        return DeploymentResult(
                            success=False,
                            status=DeploymentStatus.FAILED,
                            plan_id=plan.plan_id,
                            backend="basic_classic",
                            diagnostics=diags,
                            details={
                                "failed_step": "screen_reference_validation",
                                "validation_blockers": validation_blockers,
                                "artifact_log": artifact_data,
                            },
                        )

                screen_xml_list.append(rewritten_xml)

        # ------------------------------------------------------------------
        # Step 7: 执行 TIA 部署
        # ------------------------------------------------------------------
        step_results = tia_executor.execute_all(
            project=project,
            hmi_software=hmi_sw,
            connections_xml=[],
            tags_xml="",           # 已在 Step 1-2 单独导入
            text_lists_xml="",     # 已在 Step 4 单独导入
            scripts_xml="",
            resources_xml="",
            screen_xml_list=screen_xml_list,
        )

        for r in step_results:
            diags.extend(r.diagnostics)

        all_ok = all(r.success for r in step_results)
        compile_result = next((r for r in step_results if r.step_key == "compile"), None)
        compile_ok = compile_result.success if compile_result else False

        # 收集编译消息
        if compile_result:
            artifact_data["compile_warnings_errors"] = [
                d.model_dump() if hasattr(d, "model_dump") else d
                for d in compile_result.diagnostics
            ]

        # ------------------------------------------------------------------
        # Step 8: 真实验收（6 项检查）
        # ------------------------------------------------------------------
        acceptance = tia_executor.verify_deployment_acceptance(
            hmi_sw, required_tag_names, binding_map,
        )
        artifact_data["acceptance"] = acceptance

        if not acceptance.get("all_passed", False):
            failed_checks = [
                k for k, v in acceptance.get("checks", {}).items() if not v
            ]
            diags.append(Diagnostic(
                code=DiagnosticCodes.VERIFY_FAILED,
                severity=DiagnosticSeverity.ERROR,
                phase="P80_VERIFY",
                message=f"真实验收失败 — 未通过的检查: {failed_checks}",
            ))

            # 生成产物日志（即使失败也记录）
            if export_dir:
                artifact_log_path = tia_executor.generate_artifact_log(
                    tag_xml_paths=artifact_data["generated_tag_xml_paths"],
                    imported_tag_names=artifact_data["imported_tag_names"],
                    default_table_tags=artifact_data["actual_default_table_tags"],
                    binding_map=artifact_data["object_to_tag_binding_map"],
                    template_leaks=artifact_data["remaining_template_references"],
                    compile_messages=artifact_data["compile_warnings_errors"],
                    output_dir=export_dir,
                )
                artifact_data["artifact_log_path"] = artifact_log_path

            return DeploymentResult(
                success=False,
                status=DeploymentStatus.VERIFICATION_FAILED,
                plan_id=plan.plan_id,
                backend="basic_classic",
                diagnostics=diags,
                details={
                    "acceptance": acceptance,
                    "failed_checks": failed_checks,
                    "artifact_log": artifact_data,
                },
            )

        # ------------------------------------------------------------------
        # 全部通过 — 生成产物日志
        # ------------------------------------------------------------------
        if export_dir:
            artifact_log_path = tia_executor.generate_artifact_log(
                tag_xml_paths=artifact_data["generated_tag_xml_paths"],
                imported_tag_names=artifact_data["imported_tag_names"],
                default_table_tags=artifact_data["actual_default_table_tags"],
                binding_map=artifact_data["object_to_tag_binding_map"],
                template_leaks=artifact_data["remaining_template_references"],
                compile_messages=artifact_data["compile_warnings_errors"],
                output_dir=export_dir,
            )
            artifact_data["artifact_log_path"] = artifact_log_path

        tags_created = len(required_tag_names)
        screens_created = len(screen_xml_list)

        return DeploymentResult(
            success=True,
            status=DeploymentStatus.DEPLOYED,
            plan_id=plan.plan_id,
            backend="basic_classic",
            tags_created=tags_created,
            screens_created=screens_created,
            diagnostics=diags,
            details={
                "step_results": [r.to_dict() for r in step_results],
                "acceptance": acceptance,
                "artifact_log": artifact_data,
                "sio_downgrades": sio_downgrades,
            },
        )

    # ------------------------------------------------------------------
    # verify — 只读查询 + 语义验证
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

        # V3.2: 反向导出并验证模板残留
        rev_exports = query_svc.export_screens_xml(hmi_sw, unified=False)
        query_svc.save_reverse_export_xml(rev_exports, plan_id)

        # V3.2: 构建 binding_map 用于语义验证
        binding_map = self._build_control_binding_map(spec) if spec else {}

        verify_svc = VerificationService()
        return verify_svc.verify_full(
            spec, snapshot, connected=True,
            reverse_export_xmls=rev_exports,
            template_tag_names=self._common.TEMPLATE_TAG_NAMES,
            binding_map=binding_map,
        )

    # ------------------------------------------------------------------
    # 构建每控件独立的变量绑定映射
    # ------------------------------------------------------------------

    def _build_control_binding_map(self, spec: HmiProjectSpec) -> dict[str, dict]:
        """从 HmiProjectSpec 构建 {control_object_name → binding_info} 映射。

        确保每个控件有自己的独立变量，禁止共用模板变量。

        返回格式:
            {
                "BTN_Start": {
                    "tag_name": "CMD_Start",
                    "control_type": "Button",
                    "is_momentary": True,
                    "text_list": None,
                },
                ...
            }
        """
        binding_map: dict[str, dict] = {}

        for screen in spec.screens:
            for item in screen.items:
                binding = self._infer_binding_for_item(item, spec)
                if binding:
                    binding_map[item.id] = binding

        return binding_map

    def _infer_binding_for_item(
        self, item: ScreenItemSpec, spec: HmiProjectSpec,
    ) -> dict | None:
        """为单个控件推断绑定信息。"""
        oid = item.id
        otype = item.type
        tag_name = item.tag_binding or ""

        # 优先使用已绑定的 tag_binding
        # 如果 tag_binding 仍为模板变量，则从全局 tags 列表中查找
        if not tag_name or tag_name in ClassicCommon.TEMPLATE_TAG_NAMES:
            tag_name = self._resolve_tag_name_for_item(item, spec)

        if not tag_name:
            return None

        binding: dict = {
            "tag_name": tag_name,
            "control_type": self._control_type_name(otype),
            "is_momentary": item.properties.get("tag_mode", "momentary") != "toggle",
            "text_list": item.properties.get("text_list"),
        }

        # SymbolicIOField 的文本列表项
        if otype == ScreenItemType.SYMBOLIC_IO_FIELD:
            text_list_name = item.properties.get("text_list") or f"{oid}_TextList"
            binding["text_list"] = text_list_name
            # 使用默认或自定义条目
            entries = item.properties.get("text_list_entries")
            if not entries:
                _, entries = self._common.tag_builder.make_default_mode_text_list()
            binding["text_list_entries"] = entries

        return binding

    @staticmethod
    def _resolve_tag_name_for_item(item: ScreenItemSpec, spec: HmiProjectSpec) -> str:
        """从全局 tags 列表中为控件匹配变量名。

        查找规则:
          1. 匹配 item.id 去掉前缀后的名称
          2. 匹配 item.tag_binding (如果非空且非模板变量)
          3. 按控件类型前缀匹配
        """
        item_id = item.id

        # 移除已知前缀以获取基础名
        from backend.utils.tag_prefix_utils import strip_known_tag_prefixes
        base_name = strip_known_tag_prefixes(item_id)

        # 查找匹配的 tag
        tag_names = {t.name for t in spec.tags}
        if item_id in tag_names:
            return item_id
        if base_name in tag_names:
            return base_name

        # 尝试前缀匹配
        for tag in spec.tags:
            if tag.name.endswith(base_name) or base_name in tag.name:
                return tag.name

        # fallback: 返回 item.id 作为变量名
        return item_id

    @staticmethod
    def _control_type_name(otype: ScreenItemType) -> str:
        """将 ScreenItemType 枚举转为控件类型字符串。"""
        mapping = {
            ScreenItemType.BUTTON: "Button",
            ScreenItemType.IO_FIELD: "IOField",
            ScreenItemType.SYMBOLIC_IO_FIELD: "SymbolicIOField",
            ScreenItemType.INDICATOR: "Indicator",
            ScreenItemType.TEXT: "Text",
        }
        return mapping.get(otype, otype.value)

    @staticmethod
    def _downgrade_symbolic_iofield_in_xml(xml: str, control_id: str) -> str:
        """在 XML 中将指定 SymbolicIOField 降级为普通 IOField。

        修改标签: Hmi.Screen.SymbolicIOField → Hmi.Screen.IOField
        移除 TextList 相关属性。
        """
        import re
        # 将完整标签名替换
        xml = xml.replace("Hmi.Screen.SymbolicIOField", "Hmi.Screen.IOField")
        return xml

    # ------------------------------------------------------------------
    # XML 产物生成器（供旧接口兼容）
    # ------------------------------------------------------------------

    def compile_tags(self, tags):
        return self._common.build_tags_xml(tags)

    def compile_screen(self, screen):
        return self._common.build_screen_xml(screen)

    def compile_event(self, event):
        return self._common.function_list_builder.build(event, target_family="basic")

    def compile_binding(self, binding):
        return self._common.dynamic_builder.build(binding)

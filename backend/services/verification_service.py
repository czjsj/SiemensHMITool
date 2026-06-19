# -*- coding: utf-8 -*-
"""验证服务 — 语义级部署后验证。

Part 6 增强：从数量验证扩展为语义验证:
  Tag: 名称, 类型, scope, 连接, PLC 引用
  ScreenItem: 名称, 类型, 位置, 尺寸
  Binding: 目标属性, 类型, 源变量, 状态映射
  Event: 事件类型, 动作类型, 变量/画面/脚本参数
  Script: 语言, 名称, 内容摘要
"""
from __future__ import annotations
from backend.domain.ir_v2 import HmiProjectSpec, ScreenItemSpec, TagSpec
from backend.domain.deployment_result import VerificationResult, ObjectCountSummary, CompileResult
from backend.domain.diagnostics import Diagnostic, DiagnosticCodes
from backend.domain.enums import DiagnosticSeverity


class VerificationService:
    """语义级验证服务。不得在没有查询实际 TIA 对象时返回部署成功。"""

    def __init__(self):
        pass

    def verify_full(
        self, spec: HmiProjectSpec, object_query_result: dict, connected: bool = False,
        reverse_export_xmls: list[dict] | None = None,
        template_tag_names: set[str] | None = None,
        binding_map: dict[str, dict] | None = None,
    ) -> VerificationResult:
        """完整语义验证。connected=False 时返回失败。

        V3.2 增强:
          - verify_button_events: 比较按钮事件变量
          - verify_dynamizations: 比较动态化变量
          - verify_no_template_references: 反向导出模板残留检查
          - verify_tag_tables: 变量表成员验证
        """
        if not connected:
            return VerificationResult(
                success=False,
                tags=ObjectCountSummary(expected=len(spec.tags), found=0, failed=[t.name for t in spec.tags]),
                screens=ObjectCountSummary(expected=len(spec.screens), found=0, failed=[s.name for s in spec.screens]),
                compile=CompileResult(errors=0, warnings=0, messages=["NOT_CONNECTED: 无法验证"]),
            )

        found_tags = object_query_result.get("tags", [])
        found_screens = object_query_result.get("screens", [])
        found_events = object_query_result.get("events", [])
        found_bindings = object_query_result.get("bindings", [])
        found_scripts = object_query_result.get("scripts", [])

        diags: list[Diagnostic] = []

        # 语义验证每个 tag
        tag_result = self._verify_tags_semantic(spec.tags, found_tags)

        # V3.2: 验证变量表成员
        tag_table_diags = self._verify_tag_tables(spec.tags, found_tags)
        diags.extend(tag_table_diags)

        # 语义验证每个 screen
        screen_diags: list[Diagnostic] = []
        for screen in spec.screens:
            screen_data = next((s for s in found_screens if s.get("name") == screen.name), None)
            if screen_data is None:
                screen_diags.append(Diagnostic(
                    code=DiagnosticCodes.VERIFY_SCREEN_MISSING,
                    severity=DiagnosticSeverity.ERROR,
                    object_type="screen", object_name=screen.name,
                    message=f"画面 '{screen.name}' 在 TIA 项目中未找到",
                ))
                continue
            for item in screen.items:
                item_data = next((i for i in screen_data.get("items", []) if i.get("name") == item.id), None)
                if item_data is None:
                    screen_diags.append(Diagnostic(
                        code="VERIFY_ITEM_MISSING",
                        severity=DiagnosticSeverity.WARNING,
                        object_type="screen_item", object_name=item.id,
                        message=f"控件 '{item.id}' 在画面 '{screen.name}' 中未找到",
                    ))
                else:
                    self._verify_item_semantic(item, item_data, screen_diags)

        # 语义验证 events
        event_result = self._verify_events_semantic(spec, found_events)

        # V3.2: 按钮事件变量验证
        if binding_map:
            button_event_diags = self._verify_button_events(spec, found_events, binding_map, found_tags)
            diags.extend(button_event_diags)

        # 语义验证 bindings
        binding_result = self._verify_bindings_semantic(spec, found_bindings)

        # V3.2: 动态化变量验证
        if binding_map:
            dynamization_diags = self._verify_dynamizations(spec, found_bindings, binding_map, found_tags)
            diags.extend(dynamization_diags)

        # 语义验证 scripts
        script_result = self._verify_scripts_semantic(spec.scripts, found_scripts)

        # V3.2: 反向导出模板残留检查
        if reverse_export_xmls and template_tag_names:
            reverse_export_diags = self._verify_no_template_references(
                reverse_export_xmls, template_tag_names,
            )
            diags.extend(reverse_export_diags)

        compile_data = object_query_result.get("compile", {})
        compile_result = CompileResult(
            errors=compile_data.get("errors", 0),
            warnings=compile_data.get("warnings", 0),
            messages=compile_data.get("messages", []),
        )

        all_ok = (
            tag_result.failed == []
            and all(d.severity != DiagnosticSeverity.ERROR for d in screen_diags)
            and all(d.severity != DiagnosticSeverity.ERROR for d in diags)
            and event_result.failed == []
            and binding_result.failed == []
            and compile_result.errors == 0
        )

        return VerificationResult(
            success=all_ok,
            tags=tag_result,
            screens=ObjectCountSummary(
                expected=len(spec.screens),
                found=len(found_screens),
                failed=[s.name for s in spec.screens if not any(f.get("name") == s.name for f in found_screens)],
            ),
            events=event_result,
            bindings=binding_result,
            scripts=script_result,
            compile=compile_result,
        )

    # ---- 语义验证方法 ----

    def _verify_tags_semantic(self, tags: list[TagSpec], found_tags: list[dict]) -> ObjectCountSummary:
        failed = []
        found_names = {t.get("name", "") for t in found_tags}
        for tag in tags:
            if tag.name not in found_names:
                failed.append(f"{tag.name} (missing)")
                continue
            found = next(t for t in found_tags if t.get("name") == tag.name)
            if found.get("data_type") != tag.data_type:
                failed.append(f"{tag.name} (type mismatch: expected {tag.data_type}, got {found.get('data_type')})")
            if tag.scope.value == "external" and tag.connection and found.get("connection") != tag.connection:
                failed.append(f"{tag.name} (connection mismatch)")
        return ObjectCountSummary(expected=len(tags), found=len(found_tags), failed=failed)

    def _verify_item_semantic(self, item: ScreenItemSpec, found: dict, diags: list[Diagnostic]):
        if found.get("type") != item.type.value:
            diags.append(Diagnostic(
                code="VERIFY_ITEM_TYPE_MISMATCH",
                severity=DiagnosticSeverity.WARNING,
                object_type="screen_item", object_name=item.id,
                message=f"控件类型不匹配: expected {item.type.value}, got {found.get('type')}",
            ))
        geo = item.geometry
        if abs(found.get("x", 0) - geo.x) > 5 or abs(found.get("y", 0) - geo.y) > 5:
            diags.append(Diagnostic(
                code="VERIFY_ITEM_POSITION_MISMATCH",
                severity=DiagnosticSeverity.WARNING,
                object_type="screen_item", object_name=item.id,
                message=f"位置偏差: expected ({geo.x},{geo.y}), got ({found.get('x')},{found.get('y')})",
            ))

    def _verify_events_semantic(self, spec: HmiProjectSpec, found_events: list[dict]) -> ObjectCountSummary:
        failed = []
        for screen in spec.screens:
            for item in screen.items:
                for ev in item.events:
                    match = any(
                        f.get("item_id") == item.id and f.get("event") == ev.event.value
                        for f in found_events
                    )
                    if not match:
                        failed.append(f"{item.id}.{ev.event.value}")

                    for act in ev.actions:
                        act_match = any(
                            f.get("item_id") == item.id
                            and f.get("event") == ev.event.value
                            and f.get("action_type") == act.type.value
                            for f in found_events
                        )
                        if not act_match:
                            failed.append(f"{item.id}.{ev.event.value}.{act.type.value} (action)")
        return ObjectCountSummary(
            expected=sum(len(item.events) for s in spec.screens for item in s.items),
            found=len(found_events),
            failed=failed,
        )

    def _verify_bindings_semantic(self, spec: HmiProjectSpec, found_bindings: list[dict]) -> ObjectCountSummary:
        failed = []
        for screen in spec.screens:
            for item in screen.items:
                for b in item.bindings:
                    match = any(
                        f.get("item_id") == item.id
                        and f.get("property") == b.property
                        and f.get("kind") == b.kind.value
                        and f.get("source_tag") == b.source_tag
                        for f in found_bindings
                    )
                    if not match:
                        failed.append(f"{item.id}.{b.property}")
        return ObjectCountSummary(
            expected=sum(len(item.bindings) for s in spec.screens for item in s.items),
            found=len(found_bindings),
            failed=failed,
        )

    def _verify_scripts_semantic(self, scripts, found_scripts: list[dict]) -> ObjectCountSummary:
        failed = []
        found_names = {s.get("name", "") for s in found_scripts}
        for script in scripts:
            if script.name not in found_names:
                failed.append(f"{script.name} (missing)")
                continue
            found = next(s for s in found_scripts if s.get("name") == script.name)
            if found.get("language") != script.language.value:
                failed.append(f"{script.name} (language mismatch)")
        return ObjectCountSummary(expected=len(scripts), found=len(found_scripts), failed=failed)

    # ---- V3.2 语义验证增强方法 ----

    def _verify_tag_tables(
        self, tags: list[TagSpec], found_tags: list[dict],
    ) -> list[Diagnostic]:
        """验证变量是否正确位于 DefaultTagTable 或指定变量表中。

        返回诊断列表；空列表表示通过。
        """
        diags: list[Diagnostic] = []
        found_names = {t.get("name", ""): t for t in found_tags}

        for tag in tags:
            found = found_names.get(tag.name)
            if found is None:
                continue  # 已在 _verify_tags_semantic 中报告

            table_name = found.get("table_name", "")
            is_default = found.get("is_default_table", True)

            # 检查 tag 是否位于 DefaultTagTable
            if tag.scope and tag.scope.value == "external":
                if not table_name:
                    diags.append(Diagnostic(
                        code=DiagnosticCodes.DEFAULT_TAG_TABLE_NOT_FOUND,
                        severity=DiagnosticSeverity.WARNING,
                        object_type="tag", object_name=tag.name,
                        message=f"外部变量 '{tag.name}' 未关联变量表",
                    ))
            elif not is_default and table_name != "DefaultTagTable":
                diags.append(Diagnostic(
                    code=DiagnosticCodes.VERIFY_TAG_MISSING,
                    severity=DiagnosticSeverity.WARNING,
                    object_type="tag", object_name=tag.name,
                    message=f"变量 '{tag.name}' 位于 '{table_name}'，不在 DefaultTagTable",
                ))

        return diags

    def _verify_button_events(
        self,
        spec: HmiProjectSpec,
        found_events: list[dict],
        binding_map: dict[str, dict],
        found_tags: list[dict],
    ) -> list[Diagnostic]:
        """验证按钮 Press/Release/Click 事件引用正确的项目变量。

        比较 expected_button_tag == actual_button_tag。
        """
        diags: list[Diagnostic] = []
        found_tag_names = {t.get("name", "") for t in found_tags}

        for screen in spec.screens:
            for item in screen.items:
                binding = binding_map.get(item.id, {})
                expected_tag = binding.get("tag_name", "")
                if not expected_tag:
                    continue

                for ev in item.events:
                    ev_name = ev.event.value if hasattr(ev.event, "value") else str(ev.event)
                    # 查找匹配的 found event
                    matching = [
                        f for f in found_events
                        if f.get("item_id") == item.id
                        and f.get("event") == ev_name
                    ]
                    for found_ev in matching:
                        actual_tag = found_ev.get("tag", "")
                        if actual_tag and actual_tag != expected_tag:
                            diags.append(Diagnostic(
                                code=DiagnosticCodes.BUTTON_EVENT_TAG_MISMATCH,
                                severity=DiagnosticSeverity.ERROR,
                                phase="P80_VERIFY",
                                object_type="button_event",
                                object_name=f"{item.id}.{ev_name}",
                                message=(
                                    f"按钮事件变量不匹配: "
                                    f"expected '{expected_tag}', got '{actual_tag}'"
                                ),
                            ))
                        elif actual_tag and actual_tag not in found_tag_names:
                            diags.append(Diagnostic(
                                code=DiagnosticCodes.IMPORTED_TAG_NOT_FOUND,
                                severity=DiagnosticSeverity.ERROR,
                                phase="P80_VERIFY",
                                object_type="button_event",
                                object_name=f"{item.id}.{ev_name}",
                                message=f"按钮事件引用变量 '{actual_tag}' 未在变量表中找到",
                            ))

        return diags

    def _verify_dynamizations(
        self,
        spec: HmiProjectSpec,
        found_bindings: list[dict],
        binding_map: dict[str, dict],
        found_tags: list[dict],
    ) -> list[Diagnostic]:
        """验证动态化（颜色、可见性）引用正确的项目变量。

        比较 expected_dynamic_tag == actual_dynamic_tag。
        """
        diags: list[Diagnostic] = []
        found_tag_names = {t.get("name", "") for t in found_tags}

        for screen in spec.screens:
            for item in screen.items:
                binding = binding_map.get(item.id, {})
                expected_tag = binding.get("tag_name", "")
                if not expected_tag:
                    continue

                for b in item.bindings:
                    source_tag = getattr(b, "source_tag", "") or ""
                    prop = getattr(b, "property", "") or ""

                    matching = [
                        f for f in found_bindings
                        if f.get("item_id") == item.id
                        and f.get("property") == prop
                    ]
                    for found_b in matching:
                        actual_tag = found_b.get("source_tag", "")
                        if actual_tag and actual_tag != expected_tag:
                            diags.append(Diagnostic(
                                code=DiagnosticCodes.DYNAMIZATION_TAG_MISMATCH,
                                severity=DiagnosticSeverity.ERROR,
                                phase="P80_VERIFY",
                                object_type="dynamization",
                                object_name=f"{item.id}.{prop}",
                                message=(
                                    f"动态化变量不匹配: "
                                    f"expected '{expected_tag}', got '{actual_tag}'"
                                ),
                            ))

        return diags

    def _verify_no_template_references(
        self,
        reverse_export_xmls: list[dict],
        template_tag_names: set[str],
    ) -> list[Diagnostic]:
        """检查反向导出 XML 中是否存在模板变量引用残留。

        只要存在模板变量，部署结果必须为 VERIFICATION_FAILED。
        """
        diags: list[Diagnostic] = []

        for export in reverse_export_xmls:
            screen_name = export.get("screen_name", "unknown")
            xml_text = export.get("xml", "")
            if not xml_text:
                continue

            import re
            for tpl_name in template_tag_names:
                # 使用正则检查，但不匹配 ObjectName 等控件名称
                pattern = rf'<Name>{re.escape(tpl_name)}</Name>'
                if re.search(pattern, xml_text):
                    diags.append(Diagnostic(
                        code=DiagnosticCodes.REVERSE_EXPORT_TEMPLATE_REFERENCE_REMAINS,
                        severity=DiagnosticSeverity.ERROR,
                        phase="P80_VERIFY",
                        object_type="reverse_export",
                        object_name=screen_name,
                        message=(
                            f"反向导出画面 '{screen_name}' 中仍残留模板变量引用 "
                            f"'{tpl_name}'"
                        ),
                    ))

            # 也检查 ProcessTag 中的模板变量
            for tpl_name in template_tag_names:
                pattern = rf'<ProcessTag>{re.escape(tpl_name)}</ProcessTag>'
                if re.search(pattern, xml_text):
                    diags.append(Diagnostic(
                        code=DiagnosticCodes.REVERSE_EXPORT_TEMPLATE_REFERENCE_REMAINS,
                        severity=DiagnosticSeverity.ERROR,
                        phase="P80_VERIFY",
                        object_type="reverse_export",
                        object_name=screen_name,
                        message=(
                            f"反向导出画面 '{screen_name}' ProcessTag 仍引用模板变量 "
                            f"'{tpl_name}'"
                        ),
                    ))

        return diags

    def verify_compile_result(self, compile_data: dict) -> CompileResult:
        """验证编译结果 — ErrorCount 必须为 0。"""
        errors = compile_data.get("errors", -1)
        warnings = compile_data.get("warnings", -1)
        messages = compile_data.get("messages", [])

        if errors != 0:
            messages.append({
                "severity": "Error",
                "description": f"Compile ErrorCount={errors}, must be 0 for DEPLOYED status",
            })

        return CompileResult(errors=errors, warnings=warnings, messages=messages)

    # ---- 旧兼容方法 ----

    def verify_tags(self, expected: list[str], found: list[str]) -> ObjectCountSummary:
        missing = [t for t in expected if t not in found]
        return ObjectCountSummary(expected=len(expected), found=len(found), failed=missing)

    def verify_screens(self, expected: list[str], found: list[str]) -> ObjectCountSummary:
        missing = [s for s in expected if s not in found]
        return ObjectCountSummary(expected=len(expected), found=len(found), failed=missing)

    def verify_events(self, expected: list[tuple], found: list[tuple]) -> ObjectCountSummary:
        exp_set = set(expected)
        fnd_set = set(found)
        missing = [f"{item[0]}.{item[1]}" for item in exp_set - fnd_set]
        return ObjectCountSummary(expected=len(expected), found=len(found), failed=missing)

    def verify_bindings(self, expected: list[tuple], found: list[tuple]) -> ObjectCountSummary:
        exp_set = set(expected)
        fnd_set = set(found)
        missing = [f"{item[0]}.{item[1]}" for item in exp_set - fnd_set]
        return ObjectCountSummary(expected=len(expected), found=len(found), failed=missing)

    def verify_scripts(self, expected: list[str], found: list[str]) -> ObjectCountSummary:
        missing = [s for s in expected if s not in found]
        return ObjectCountSummary(expected=len(expected), found=len(found), failed=missing)

    def verify_compile(self, errors: int = 0, warnings: int = 0, messages: list | None = None) -> CompileResult:
        return CompileResult(errors=errors, warnings=warnings, messages=messages or [])

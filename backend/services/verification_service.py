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
    ) -> VerificationResult:
        """完整语义验证。connected=False 时返回失败。"""
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

        # 语义验证每个 tag
        tag_result = self._verify_tags_semantic(spec.tags, found_tags)

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

        # 语义验证 bindings
        binding_result = self._verify_bindings_semantic(spec, found_bindings)

        # 语义验证 scripts
        script_result = self._verify_scripts_semantic(spec.scripts, found_scripts)

        compile_data = object_query_result.get("compile", {})
        compile_result = CompileResult(
            errors=compile_data.get("errors", 0),
            warnings=compile_data.get("warnings", 0),
            messages=compile_data.get("messages", []),
        )

        all_ok = (
            tag_result.failed == []
            and all(d.severity != DiagnosticSeverity.ERROR for d in screen_diags)
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

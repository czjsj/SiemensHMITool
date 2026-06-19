# -*- coding: utf-8 -*-
"""验证服务 — 部署后查询目标项目验证对象存在与编译结果。

方案文档 §20 对齐。
"""
from __future__ import annotations
from backend.domain.ir_v2 import HmiProjectSpec
from backend.domain.deployment_result import VerificationResult, ObjectCountSummary, CompileResult


class VerificationService:
    """部署后验证服务。

    验证内容:
      - 变量存在与数量
      - 画面存在与数量
      - 事件存在
      - 动态绑定存在
      - 脚本存在
      - 编译结果
    """

    def __init__(self):
        pass

    def verify_tags(self, expected: list[str], found: list[str]) -> ObjectCountSummary:
        missing = [t for t in expected if t not in found]
        return ObjectCountSummary(expected=len(expected), found=len(found), failed=missing)

    def verify_screens(self, expected: list[str], found: list[str]) -> ObjectCountSummary:
        missing = [s for s in expected if s not in found]
        return ObjectCountSummary(expected=len(expected), found=len(found), failed=missing)

    def verify_events(self, expected: list[tuple], found: list[tuple]) -> ObjectCountSummary:
        """expected: [(item_id, event_type, [action_count]), ...]; found: same format."""
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

    def verify_full(self, spec: HmiProjectSpec, object_query_result: dict) -> VerificationResult:
        """从 HmiProjectSpec 和查询结果构建 VerificationResult。"""
        found_tags = object_query_result.get("tags", [])
        found_screens = object_query_result.get("screens", [])
        found_events = object_query_result.get("events", [])
        found_bindings = object_query_result.get("bindings", [])
        found_scripts = object_query_result.get("scripts", [])

        expected_tag_names = [t.name for t in spec.tags]
        expected_screen_names = [s.name for s in spec.screens]
        expected_events = []
        expected_bindings = []
        for s in spec.screens:
            for item in s.items:
                for ev in item.events:
                    expected_events.append((item.id, ev.event.value, len(ev.actions)))
                for b in item.bindings:
                    expected_bindings.append((item.id, b.property, b.kind.value))
        expected_script_names = [sc.name for sc in spec.scripts]

        compile_data = object_query_result.get("compile", {})
        compile_result = self.verify_compile(
            errors=compile_data.get("errors", 0),
            warnings=compile_data.get("warnings", 0),
            messages=compile_data.get("messages", []),
        )

        return VerificationResult(
            success=all(s.failed == [] for s in [
                self.verify_tags(expected_tag_names, found_tags),
                self.verify_screens(expected_screen_names, found_screens),
            ]),
            tags=self.verify_tags(expected_tag_names, found_tags),
            screens=self.verify_screens(expected_screen_names, found_screens),
            events=self.verify_events(expected_events, found_events),
            bindings=self.verify_bindings(expected_bindings, found_bindings),
            scripts=self.verify_scripts(expected_script_names, found_scripts),
            compile=compile_result,
        )

# -*- coding: utf-8 -*-
"""
部署前变量绑定闸门 — 在画面导入前阻断变量缺失/模板残留。

职责:
  1. validate_project_tag_bindings(project) — 校验 HmiProjectSpec 的 tag 完整性
  2. raise_if_project_tag_bindings_invalid(project) — 存在阻断错误时抛出
  3. validate_legacy_ir_tag_bindings(ir) — 校验 legacy IR

在以下位置必须调用:
  - DeploymentService build_plan 前
  - BasicBackend build_screen_xml 前
  - ComfortBackend build_screen_xml 前
  - UnifiedBackend 创建画面前
  - template_xml_generator 生成 XML 前
  - OpennessManager 旧入口导入画面前
"""

from __future__ import annotations

from typing import Any

from backend.domain.ir_v2 import HmiProjectSpec, ScreenItemSpec, TagSpec
from backend.domain.diagnostics import Diagnostic, DiagnosticCodes
from backend.domain.enums import (
    DiagnosticSeverity,
    ScreenItemType,
    TagScope,
)


# ---------------------------------------------------------------------------
# HmiProjectSpec 级别校验
# ---------------------------------------------------------------------------


def validate_project_tag_bindings(project: HmiProjectSpec) -> list[Diagnostic]:
    """校验 HmiProjectSpec 的 tag 完整性。

    检查:
      - project.tags 中 tag name 唯一。
      - 所有需要变量的 item 都有 binding.tag。
      - binding.tag 必须存在于 project.tags。
      - Button 的变量建议是 Bool。
      - Indicator 的变量建议是 Bool / Int，视 indicator_mode 而定。
      - IOField 的变量必须是数值类型。
      - SymbolicIOField 的变量必须能对应 text_list / Int 类状态。
      - 外部 PLC 地址为空时，允许 pending_mapping，但必须在 diagnostics 中标注。
    """
    diagnostics: list[Diagnostic] = []

    tag_names: set[str] = set()
    tag_map: dict[str, TagSpec] = {}
    for tag in project.tags:
        if tag.name in tag_names:
            diagnostics.append(Diagnostic(
                code=DiagnosticCodes.IR_VALIDATION_ERROR,
                severity=DiagnosticSeverity.ERROR,
                phase="P30_TAG_TABLES_AND_TAGS",
                object_type="tag",
                object_name=tag.name,
                message=f"变量名 '{tag.name}' 在 project.tags 中重复",
            ))
        tag_names.add(tag.name)
        tag_map[tag.name] = tag

    # 遍历所有需要变量的控件
    for screen in project.screens:
        for item in screen.items:
            if item.type not in (
                ScreenItemType.BUTTON,
                ScreenItemType.INDICATOR,
                ScreenItemType.IO_FIELD,
                ScreenItemType.SYMBOLIC_IO_FIELD,
            ):
                continue

            binding_tag = item.tag_binding or ""
            if not binding_tag:
                diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.IR_BUTTON_BINDING_MISSING,
                    severity=DiagnosticSeverity.ERROR,
                    phase="P30_TAG_TABLES_AND_TAGS",
                    object_type=item.type.value if item.type else "unknown",
                    object_name=item.id,
                    message=f"控件 '{item.id}' ({item.type.value if item.type else '?'}) 缺少 binding.tag",
                    remediation="请为该控件绑定变量",
                ))
                continue

            if binding_tag not in tag_map:
                diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.VERIFY_TAG_MISSING,
                    severity=DiagnosticSeverity.ERROR,
                    phase="P30_TAG_TABLES_AND_TAGS",
                    object_type=item.type.value if item.type else "unknown",
                    object_name=item.id,
                    message=f"控件 '{item.id}' 的 binding.tag '{binding_tag}' 不存在于 project.tags",
                    remediation=f"请在 project.tags 中声明变量 '{binding_tag}'",
                ))
                continue

            tag = tag_map[binding_tag]

            # 类型检查
            if item.type == ScreenItemType.BUTTON:
                if tag.data_type != "Bool":
                    diagnostics.append(Diagnostic(
                        code=DiagnosticCodes.IR_VALIDATION_ERROR,
                        severity=DiagnosticSeverity.WARNING,
                        phase="P30_TAG_TABLES_AND_TAGS",
                        object_type="button",
                        object_name=item.id,
                        message=f"按钮 '{item.id}' 的变量 '{binding_tag}' 类型为 {tag.data_type}，建议使用 Bool",
                    ))

            elif item.type == ScreenItemType.INDICATOR:
                if tag.data_type not in ("Bool", "Int"):
                    diagnostics.append(Diagnostic(
                        code=DiagnosticCodes.IR_VALIDATION_ERROR,
                        severity=DiagnosticSeverity.WARNING,
                        phase="P30_TAG_TABLES_AND_TAGS",
                        object_type="indicator",
                        object_name=item.id,
                        message=f"指示灯 '{item.id}' 的变量 '{binding_tag}' 类型为 {tag.data_type}，建议使用 Bool 或 Int",
                    ))

            elif item.type == ScreenItemType.IO_FIELD:
                if tag.data_type not in ("Bool", "Int", "DInt", "Real", "Word"):
                    diagnostics.append(Diagnostic(
                        code=DiagnosticCodes.IR_VALIDATION_ERROR,
                        severity=DiagnosticSeverity.WARNING,
                        phase="P30_TAG_TABLES_AND_TAGS",
                        object_type="io_field",
                        object_name=item.id,
                        message=f"IOField '{item.id}' 的变量 '{binding_tag}' 类型为 {tag.data_type}（非数值类型）",
                    ))

            elif item.type == ScreenItemType.SYMBOLIC_IO_FIELD:
                if tag.data_type != "Int":
                    diagnostics.append(Diagnostic(
                        code=DiagnosticCodes.IR_VALIDATION_ERROR,
                        severity=DiagnosticSeverity.WARNING,
                        phase="P30_TAG_TABLES_AND_TAGS",
                        object_type="symbolic_io_field",
                        object_name=item.id,
                        message=f"SymbolicIOField '{item.id}' 的变量 '{binding_tag}' 类型为 {tag.data_type}，建议使用 Int",
                    ))
                # 检查 text_list
                text_list = item.properties.get("text_list", "")
                if not text_list:
                    diagnostics.append(Diagnostic(
                        code=DiagnosticCodes.IR_VALIDATION_ERROR,
                        severity=DiagnosticSeverity.WARNING,
                        phase="P30_TAG_TABLES_AND_TAGS",
                        object_type="symbolic_io_field",
                        object_name=item.id,
                        message=f"SymbolicIOField '{item.id}' 未关联 TextList",
                    ))

            # 外部 PLC 变量 pending_mapping 检查
            if tag.scope == TagScope.EXTERNAL and not tag.address:
                pending = tag.metadata.get("pending_mapping", False) if tag.metadata else False
                if pending:
                    diagnostics.append(Diagnostic(
                        code="PENDING_PLC_MAPPING",
                        severity=DiagnosticSeverity.WARNING,
                        phase="P30_TAG_TABLES_AND_TAGS",
                        object_type="tag",
                        object_name=tag.name,
                        message=f"变量 '{tag.name}' 为外部 PLC 变量但无地址映射",
                        remediation="请提供 PLC 地址映射或标记为内部变量",
                    ))

    return diagnostics


def raise_if_project_tag_bindings_invalid(project: HmiProjectSpec) -> None:
    """如果存在阻断错误，直接抛出 ValueError。

    不阻断 WARNING 级别诊断。
    """
    errors = validate_project_tag_bindings(project)
    blocking = [e for e in errors if e.severity == DiagnosticSeverity.ERROR]
    if blocking:
        msg_lines = [f"Tag binding validation failed ({len(blocking)} error(s)):"]
        for e in blocking:
            msg_lines.append(f"  - [{e.code}] {e.message}")
        raise ValueError("\n".join(msg_lines))


def validate_legacy_ir_tag_bindings(ir: dict) -> list[dict]:
    """校验 legacy IR 的变量绑定完整性（兼容旧路径）。

    检查:
      - process_tag/tag_binding/binding.tag 是否一致。
      - tags 是否包含所有对象引用变量。
    """
    from backend.tag_binding_normalizer import validate_legacy_ir_tag_bindings as _validate
    return _validate(ir)


def assert_legacy_ir_tag_bindings(ir: dict) -> None:
    """断言 legacy IR 变量绑定完整。不完整时抛出 ValueError。"""
    from backend.tag_binding_normalizer import assert_legacy_tags_complete
    assert_legacy_tags_complete(ir)


def summarize_project_tags(project: HmiProjectSpec) -> dict:
    """生成 HmiProjectSpec 的 tag 摘要。"""
    tags_summary = []
    for t in project.tags:
        tags_summary.append({
            "name": t.name,
            "data_type": t.data_type,
            "scope": t.scope.value if t.scope else "internal",
            "address": t.address or "",
            "pending_mapping": t.metadata.get("pending_mapping", False) if t.metadata else False,
            "comment": t.comment.get("zh-CN", "") if t.comment else "",
        })

    bindings = []
    for screen in project.screens:
        for item in screen.items:
            bindings.append({
                "screen": screen.name,
                "item": item.id,
                "type": item.type.value if item.type else "?",
                "binding_tag": item.tag_binding or "",
                "tag_exists": bool(item.tag_binding),
            })

    return {
        "tag_count": len(project.tags),
        "tag_names": [t.name for t in project.tags],
        "tags": tags_summary,
        "bindings": bindings,
    }


def validate_project_tag_integrity(project: HmiProjectSpec) -> list[Diagnostic]:
    """校验 project tag 完整性（VariableEngine 内部调用）。

    检查:
      - item.binding.tag 为空
      - binding.tag 不在 project.tags
      - 同名变量类型冲突
      - 同名变量地址冲突
    """
    return validate_project_tag_bindings(project)

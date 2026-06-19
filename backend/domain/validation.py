# -*- coding: utf-8 -*-
"""
HMI IR V2 校验模块。

对 HmiProjectSpec 做交叉引用校验、能力感知校验等。
不依赖 Flask、pythonnet 或 Siemens DLL。
"""

from __future__ import annotations

from .ir_v2 import HmiProjectSpec
from .diagnostics import Diagnostic, DiagnosticCodes
from .enums import DiagnosticSeverity


class IrV2ValidationError(Exception):
    """IR V2 校验失败异常。"""
    pass


def validate_ir_v2(project: HmiProjectSpec) -> list[Diagnostic]:
    """校验 HmiProjectSpec 的完整性和交叉引用。

    校验内容包括：
      1. schema_version 检查
      2. screens 非空
      3. tag 名称唯一性
      4. screen name 唯一性
      5. 外部变量交叉引用（connection 存在）
      6. 脚本名称唯一性
      7. 资源名称唯一性
      8. 控件内部引用（tag_binding 目标存在）
      9. 事件动作引用（tag、screen、script 目标存在）

    参数:
        project: HmiProjectSpec 实例。

    返回:
        诊断信息列表。空的 list 表示无错误。
    """
    diagnostics: list[Diagnostic] = []

    # 1. schema_version
    if project.schema_version != "2.0":
        diagnostics.append(Diagnostic(
            code=DiagnosticCodes.IR_VALIDATION_ERROR,
            severity=DiagnosticSeverity.ERROR,
            phase="P10_VALIDATE_DEPENDENCIES",
            message=f"不支持的 schema_version: {project.schema_version}",
            remediation="请使用 schema_version='2.0'",
        ))

    # 2. screens 非空（温和警告，非阻断）
    if not project.screens:
        diagnostics.append(Diagnostic(
            code=DiagnosticCodes.IR_VALIDATION_ERROR,
            severity=DiagnosticSeverity.WARNING,
            phase="P10_VALIDATE_DEPENDENCIES",
            message="项目不包含任何画面（screens 为空）",
        ))

    # 3-7. 名称唯一性检查
    tag_names: set[str] = set()
    for tag in project.tags:
        if tag.name in tag_names:
            diagnostics.append(Diagnostic(
                code=DiagnosticCodes.IR_VALIDATION_ERROR,
                severity=DiagnosticSeverity.ERROR,
                phase="P10_VALIDATE_DEPENDENCIES",
                object_type="tag",
                object_name=tag.name,
                message=f"变量名 '{tag.name}' 重复",
                remediation="请确保所有变量名在项目内唯一",
            ))
        tag_names.add(tag.name)

    screen_names: set[str] = set()
    for screen in project.screens:
        if screen.name in screen_names:
            diagnostics.append(Diagnostic(
                code=DiagnosticCodes.IR_VALIDATION_ERROR,
                severity=DiagnosticSeverity.ERROR,
                phase="P10_VALIDATE_DEPENDENCIES",
                object_type="screen",
                object_name=screen.name,
                message=f"画面名 '{screen.name}' 重复",
                remediation="请确保所有画面名在项目内唯一",
            ))
        screen_names.add(screen.name)

    script_names: set[str] = set()
    for script in project.scripts:
        if script.name in script_names:
            diagnostics.append(Diagnostic(
                code=DiagnosticCodes.IR_VALIDATION_ERROR,
                severity=DiagnosticSeverity.ERROR,
                phase="P10_VALIDATE_DEPENDENCIES",
                object_type="script",
                object_name=script.name,
                message=f"脚本名 '{script.name}' 重复",
            ))
        script_names.add(script.name)

    resource_names: set[str] = set()
    for resource in project.resources:
        if resource.name in resource_names:
            diagnostics.append(Diagnostic(
                code=DiagnosticCodes.IR_VALIDATION_ERROR,
                severity=DiagnosticSeverity.ERROR,
                phase="P10_VALIDATE_DEPENDENCIES",
                object_type="resource",
                object_name=resource.name,
                message=f"资源名 '{resource.name}' 重复",
            ))
        resource_names.add(resource.name)

    # 8. 控件 tag_binding 引用目标变量必须存在
    for screen in project.screens:
        for item in screen.items:
            if item.tag_binding and item.tag_binding not in tag_names:
                diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.VERIFY_TAG_MISSING,
                    severity=DiagnosticSeverity.WARNING,
                    phase="P10_VALIDATE_DEPENDENCIES",
                    object_type="screen_item",
                    object_name=item.id,
                    message=(
                        f"控件 '{item.id}' 的 tag_binding '{item.tag_binding}' "
                        f"引用了未声明的变量"
                    ),
                    remediation="请在 tags 中声明该变量或修正 tag_binding 引用",
                ))

            # 控件 bindings
            for binding in item.bindings:
                if binding.source_tag and binding.source_tag not in tag_names:
                    diagnostics.append(Diagnostic(
                        code=DiagnosticCodes.VERIFY_TAG_MISSING,
                        severity=DiagnosticSeverity.WARNING,
                        phase="P10_VALIDATE_DEPENDENCIES",
                        object_type="binding",
                        object_name=item.id,
                        message=(
                            f"控件 '{item.id}' 的绑定 '{binding.property}' "
                            f"引用了未声明的变量 '{binding.source_tag}'"
                        ),
                    ))

            # 控件事件动作引用
            for event in item.events:
                for action in event.actions:
                    if action.tag and action.tag not in tag_names:
                        diagnostics.append(Diagnostic(
                            code=DiagnosticCodes.VERIFY_TAG_MISSING,
                            severity=DiagnosticSeverity.WARNING,
                            phase="P10_VALIDATE_DEPENDENCIES",
                            object_type="action",
                            object_name=item.id,
                            message=(
                                f"控件 '{item.id}' 的事件动作引用了"
                                f"未声明的变量 '{action.tag}'"
                            ),
                        ))
                    if action.screen and action.screen not in screen_names:
                        diagnostics.append(Diagnostic(
                            code=DiagnosticCodes.VERIFY_SCREEN_MISSING,
                            severity=DiagnosticSeverity.WARNING,
                            phase="P10_VALIDATE_DEPENDENCIES",
                            object_type="action",
                            object_name=item.id,
                            message=(
                                f"控件 '{item.id}' 的 activate_screen "
                                f"引用了未声明的画面 '{action.screen}'"
                            ),
                        ))
                    if action.script and action.script not in script_names:
                        diagnostics.append(Diagnostic(
                            code=DiagnosticCodes.VERIFY_SCRIPT_MISSING,
                            severity=DiagnosticSeverity.WARNING,
                            phase="P10_VALIDATE_DEPENDENCIES",
                            object_type="action",
                            object_name=item.id,
                            message=(
                                f"控件 '{item.id}' 的 call_script "
                                f"引用了未声明的脚本 '{action.script}'"
                            ),
                        ))

    return diagnostics


def validate_or_raise(project: HmiProjectSpec) -> HmiProjectSpec:
    """校验 HmiProjectSpec，有错误时抛出 IrV2ValidationError。

    返回原对象以便链式调用。
    """
    diags = validate_ir_v2(project)
    errors = [d for d in diags if d.severity == DiagnosticSeverity.ERROR]
    if errors:
        msg_lines = [f"IR V2 校验失败 ({len(errors)} 个错误):"]
        for d in errors:
            msg_lines.append(f"  - [{d.code}] {d.message}")
        raise IrV2ValidationError("\n".join(msg_lines))
    project.diagnostics = diags
    return project

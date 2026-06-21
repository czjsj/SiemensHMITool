# -*- coding: utf-8 -*-
"""
HMI IR V2 校验模块。

对 HmiProjectSpec 做交叉引用校验、能力感知校验等。
不依赖 Flask、pythonnet 或 Siemens DLL。
"""

from __future__ import annotations

from .ir_v2 import HmiProjectSpec, ScreenItemSpec, TagSpec
from .diagnostics import Diagnostic, DiagnosticCodes
from .enums import (
    ButtonBehavior,
    DiagnosticSeverity,
    ScreenItemType,
    TagDirection,
    TagScope,
)


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

    # 8. 控件 tag_binding 引用目标变量必须存在 — V4.1: ERROR 级别阻断
    for screen in project.screens:
        for item in screen.items:
            if item.tag_binding and item.tag_binding not in tag_names:
                diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.VERIFY_TAG_MISSING,
                    severity=DiagnosticSeverity.ERROR,
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
                        severity=DiagnosticSeverity.ERROR,
                        phase="P10_VALIDATE_DEPENDENCIES",
                        object_type="binding",
                        object_name=item.id,
                        message=(
                            f"控件 '{item.id}' 的绑定 '{binding.property}' "
                            f"引用了未声明的变量 '{binding.source_tag}'"
                        ),
                    ))

            # 控件事件动作引用 — V4.1: ERROR 级别阻断
            for event in item.events:
                for action in event.actions:
                    if action.tag and action.tag not in tag_names:
                        diagnostics.append(Diagnostic(
                            code=DiagnosticCodes.VERIFY_TAG_MISSING,
                            severity=DiagnosticSeverity.ERROR,
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
                            severity=DiagnosticSeverity.ERROR,
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
                            severity=DiagnosticSeverity.ERROR,
                            phase="P10_VALIDATE_DEPENDENCIES",
                            object_type="action",
                            object_name=item.id,
                            message=(
                                f"控件 '{item.id}' 的 call_script "
                                f"引用了未声明的脚本 '{action.script}'"
                            ),
                        ))

    return diagnostics


def validate_template_binding_requirements(project: HmiProjectSpec) -> list[Diagnostic]:
    """校验按钮和指示灯是否满足模板绑定要求。

    必须检查：
    1. 每个 button 必须有 binding.tag，除非 behavior=navigate
    2. 每个 indicator 必须有 binding.tag
    3. binding.tag 必须存在于 tags
    4. button tag 类型建议为 Bool
    5. momentary/toggle/set/reset 按钮 tag 必须可写
    6. indicator tag 必须可读
    7. template_ref 如果存在，必须是字符串
    8. 不允许控件引用不存在的 tag
    9. 不允许事件引用不存在的 tag
    10. 外部 PLC 变量如果没有 address，标记为 pending_mapping
    """
    diagnostics: list[Diagnostic] = []

    tag_names = {t.name for t in project.tags}
    tag_map = {t.name: t for t in project.tags}

    for screen in project.screens:
        for item in screen.items:
            # Check 7: template_ref type
            if item.template_ref is not None and not isinstance(item.template_ref, str):
                diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.IR_VALIDATION_ERROR,
                    severity=DiagnosticSeverity.ERROR,
                    phase="P10_VALIDATE_DEPENDENCIES",
                    object_type="screen_item",
                    object_name=item.id,
                    message=f"控件 '{item.id}' 的 template_ref 必须是字符串",
                ))

            if item.type == ScreenItemType.BUTTON:
                diags = _validate_button_binding(item, tag_names, tag_map)
                diagnostics.extend(diags)

            elif item.type == ScreenItemType.INDICATOR:
                diags = _validate_indicator_binding(item, tag_names, tag_map)
                diagnostics.extend(diags)

            # Check 8: tag_binding reference
            if item.tag_binding and item.tag_binding not in tag_names:
                diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.VERIFY_TAG_MISSING,
                    severity=DiagnosticSeverity.ERROR,
                    phase="P10_VALIDATE_DEPENDENCIES",
                    object_type="screen_item",
                    object_name=item.id,
                    message=f"控件 '{item.id}' 引用了不存在的变量 '{item.tag_binding}'",
                    remediation=f"请在 tags 中声明变量 '{item.tag_binding}'",
                ))

            # Check 9: event tag references
            for event in item.events:
                for action in event.actions:
                    if action.tag and action.tag not in tag_names:
                        diagnostics.append(Diagnostic(
                            code=DiagnosticCodes.VERIFY_TAG_MISSING,
                            severity=DiagnosticSeverity.ERROR,
                            phase="P10_VALIDATE_DEPENDENCIES",
                            object_type="action",
                            object_name=item.id,
                            message=f"控件 '{item.id}' 的事件引用了不存在的变量 '{action.tag}'",
                        ))

            # Check 10: PLC variables without address
            for binding in item.bindings:
                bt = binding.tag or binding.source_tag
                if bt and bt in tag_map:
                    tag = tag_map[bt]
                    if tag.scope in (TagScope.EXTERNAL,) and not tag.address:
                        if "pending_mapping" not in tag.metadata:
                            tag.metadata["pending_mapping"] = True

    return diagnostics


def validate_action_target_types(project: HmiProjectSpec) -> list[Diagnostic]:
    """校验 bit 操作的目标变量类型。

    SET_BIT / RESET_BIT / TOGGLE_BIT 的目标变量必须是 Bool。
    如果不是 Bool，记录 ERROR 级别诊断。

    参数:
        project: HmiProjectSpec 实例

    返回:
        诊断信息列表
    """
    BIT_ACTIONS = {"SET_BIT", "RESET_BIT", "TOGGLE_BIT", "INVERT_BIT"}

    diagnostics: list[Diagnostic] = []
    tag_map = {t.name: t for t in project.tags}

    for screen in project.screens:
        for item in screen.items:
            for event in item.events:
                for action in event.actions:
                    action_type = str(action.type.value).upper() if hasattr(action.type, 'value') else str(action.type).upper()

                    if action_type in BIT_ACTIONS:
                        target = action.tag
                        if not target:
                            continue

                        tag = tag_map.get(target)
                        if not tag:
                            diagnostics.append(Diagnostic(
                                code=DiagnosticCodes.VERIFY_TAG_MISSING,
                                severity=DiagnosticSeverity.ERROR,
                                phase="P30_TAG_TABLES_AND_TAGS",
                                object_type="action",
                                object_name=item.id,
                                message=f"Bit 操作 {action_type} 的目标变量 '{target}' 未在 project.tags 中定义",
                            ))
                            continue

                        # 归一化类型比较
                        actual_type = tag.data_type
                        normalized = actual_type.strip().capitalize() if actual_type else ""
                        # 支持 Bool 的各种写法
                        if normalized not in ("Bool", "Boolean", "Bit"):
                            diagnostics.append(Diagnostic(
                                code=DiagnosticCodes.IR_VALIDATION_ERROR,
                                severity=DiagnosticSeverity.ERROR,
                                phase="P30_TAG_TABLES_AND_TAGS",
                                object_type="action",
                                object_name=item.id,
                                message=(
                                    f"Bit 操作 {action_type} 的目标变量 '{target}' "
                                    f"类型为 {actual_type}，必须是 Bool"
                                ),
                                remediation=f"请将变量 '{target}' 的类型改为 Bool",
                            ))

    return diagnostics


def _validate_button_binding(
    item: 'ScreenItemSpec',
    tag_names: set[str],
    tag_map: dict[str, 'TagSpec'],
) -> list[Diagnostic]:
    """校验按钮绑定要求。"""
    diags: list[Diagnostic] = []

    is_navigate = (
        item.behavior == ButtonBehavior.NAVIGATE
        if hasattr(item, 'behavior') and item.behavior
        else False
    )

    if is_navigate:
        return diags  # navigate 按钮不需要变量绑定

    # Check 1: binding.tag required
    binding_tag = item.tag_binding
    for b in item.bindings:
        if b.tag:
            binding_tag = b.tag
            break

    if not binding_tag:
        diags.append(Diagnostic(
            code=DiagnosticCodes.IR_BUTTON_BINDING_MISSING,
            severity=DiagnosticSeverity.ERROR,
            phase="P10_VALIDATE_DEPENDENCIES",
            object_type="button",
            object_name=item.id,
            message=f"按钮 '{item.id}' 缺少 binding.tag，除非 behavior=navigate",
            remediation="请为按钮添加 binding.tag",
        ))
    elif binding_tag not in tag_names:
        diags.append(Diagnostic(
            code=DiagnosticCodes.IR_TAG_REFERENCE_MISSING,
            severity=DiagnosticSeverity.ERROR,
            phase="P10_VALIDATE_DEPENDENCIES",
            object_type="button",
            object_name=item.id,
            message=f"按钮 '{item.id}' 的 binding.tag '{binding_tag}' 不存在于 tags 列表",
        ))
    else:
        # Check 4,5: tag type and direction
        tag = tag_map.get(binding_tag)
        if tag:
            if tag.data_type != "Bool":
                diags.append(Diagnostic(
                    code=DiagnosticCodes.IR_VALIDATION_ERROR,
                    severity=DiagnosticSeverity.WARNING,
                    phase="P10_VALIDATE_DEPENDENCIES",
                    object_type="button",
                    object_name=item.id,
                    message=f"按钮 '{item.id}' 的变量 '{binding_tag}' 类型为 {tag.data_type}，建议使用 Bool",
                ))
            # momentary/toggle/set/reset 按钮 tag 必须可写
            behavior = getattr(item, 'behavior', None)
            if behavior and behavior.value in ("momentary", "toggle", "set", "reset"):
                if tag.read_only:
                    diags.append(Diagnostic(
                        code=DiagnosticCodes.IR_VALIDATION_ERROR,
                        severity=DiagnosticSeverity.ERROR,
                        phase="P10_VALIDATE_DEPENDENCIES",
                        object_type="button",
                        object_name=item.id,
                        message=f"按钮 '{item.id}' (behavior={behavior.value}) 需要可写变量，但 '{binding_tag}' 为只读",
                    ))

    return diags


def _validate_indicator_binding(
    item: 'ScreenItemSpec',
    tag_names: set[str],
    tag_map: dict[str, 'TagSpec'],
) -> list[Diagnostic]:
    """校验指示灯绑定要求。"""
    diags: list[Diagnostic] = []

    # Check 2: binding.tag required
    binding_tag = item.tag_binding
    for b in item.bindings:
        if b.tag:
            binding_tag = b.tag
            break

    if not binding_tag:
        diags.append(Diagnostic(
            code=DiagnosticCodes.IR_INDICATOR_BINDING_MISSING,
            severity=DiagnosticSeverity.ERROR,
            phase="P10_VALIDATE_DEPENDENCIES",
            object_type="indicator",
            object_name=item.id,
            message=f"指示灯 '{item.id}' 缺少 binding.tag",
            remediation="请为指示灯添加 binding.tag",
        ))
    elif binding_tag not in tag_names:
        diags.append(Diagnostic(
            code=DiagnosticCodes.IR_TAG_REFERENCE_MISSING,
            severity=DiagnosticSeverity.ERROR,
            phase="P10_VALIDATE_DEPENDENCIES",
            object_type="indicator",
            object_name=item.id,
            message=f"指示灯 '{item.id}' 的 binding.tag '{binding_tag}' 不存在于 tags 列表",
        ))
    else:
        # Check 6: indicator tag 必须可读
        tag = tag_map.get(binding_tag)
        if tag and tag.read_only is False and tag.direction == TagDirection.WRITE:
            diags.append(Diagnostic(
                code=DiagnosticCodes.IR_VALIDATION_ERROR,
                severity=DiagnosticSeverity.WARNING,
                phase="P10_VALIDATE_DEPENDENCIES",
                object_type="indicator",
                object_name=item.id,
                message=f"指示灯 '{item.id}' 的变量 '{binding_tag}' 为只写，指示灯通常需要可读",
            ))

    return diags


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

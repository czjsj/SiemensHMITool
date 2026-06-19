# -*- coding: utf-8 -*-
"""
能力服务：目标设备能力解析与项目校验。

组合静态矩阵 + 运行时反射结果，输出能力集并校验项目可行性。
不依赖 Flask、pythonnet 或 Siemens DLL（runtime_discovery 为独立模块）。
"""

from __future__ import annotations

from typing import Any

from backend.domain.ir_v2 import HmiProjectSpec, TargetSpec
from backend.domain.enums import (
    HmiFamily,
    BindingKind,
    SemanticActionType,
    SemanticEvent,
    ScreenItemType,
    ScriptLanguage,
    UnsupportedFeaturePolicy,
)
from backend.domain.diagnostics import Diagnostic, DiagnosticCodes
from backend.domain.enums import DiagnosticSeverity
from .static_matrix import get_capability, STATIC_CAPABILITY_MATRIX


class CapabilitySet:
    """目标设备的能力集合。"""

    def __init__(self, family: HmiFamily, tia_version: str | None = None):
        self.family = family
        self.tia_version = tia_version
        self._cache: dict[str, str] = {}

    def get(self, capability_name: str) -> str:
        """查询某项能力值（"yes"/"no"/"limited"/"device"/"unknown"）。"""
        if capability_name not in self._cache:
            self._cache[capability_name] = get_capability(
                capability_name, self.family.value
            )
        return self._cache[capability_name]

    def supports(self, capability_name: str) -> bool:
        """某项能力是否支持（yes 或 limited 都视为支持）。"""
        v = self.get(capability_name)
        return v in ("yes", "limited", "device")

    def is_strict(self, capability_name: str) -> bool:
        """严格支持（仅 yes）。"""
        return self.get(capability_name) == "yes"

    def to_dict(self) -> dict[str, Any]:
        """导出为 dict。"""
        result: dict[str, Any] = {
            "family": self.family.value,
            "tia_version": self.tia_version,
        }
        for entry in STATIC_CAPABILITY_MATRIX:
            result[entry.name] = self.get(entry.name)
        return result


class CapabilityService:
    """设备能力服务。

    使用方式:
        svc = CapabilityService()
        caps = svc.resolve(target_spec)
        diags = svc.validate_project(hmi_project_spec, caps)
    """

    def __init__(self):
        pass

    def resolve(
        self,
        target: TargetSpec,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> CapabilitySet:
        """根据目标设备规格解析能力集。

        参数:
            target: 目标设备规格。
            runtime_metadata: 可选的运行时反射结果（用于覆盖静态矩阵）。

        返回:
            CapabilitySet 实例。
        """
        caps = CapabilitySet(target.family, target.tia_version)

        # 未来：用 runtime_metadata 覆盖静态矩阵中的值
        # 当前版本：纯静态矩阵
        if runtime_metadata:
            for key, value in runtime_metadata.items():
                if key in caps._cache:
                    caps._cache[key] = str(value)

        return caps

    def validate_project(
        self,
        spec: HmiProjectSpec,
        caps: CapabilitySet,
        policy: UnsupportedFeaturePolicy | None = None,
    ) -> list[Diagnostic]:
        """验证项目是否适用于目标设备。

        检查内容：
          1. VBS 脚本在 Basic 面板 → error/warning
          2. call_script 动作在 Basic 面板 → error/warning
          3. write_expression 动作在 Basic 面板 → error/warning
          4. JavaScript 在 Comfort 面板 → warning
          5. 不支持的事件/控件类型检测

        参数:
            spec: HmiProjectSpec 实例。
            caps: 目标能力集。
            policy: 不支持的策略，默认 ERROR。

        返回:
            诊断信息列表。
        """
        policy = policy or UnsupportedFeaturePolicy.ERROR
        diags: list[Diagnostic] = []

        if caps.family == HmiFamily.BASIC:
            # Basic 禁止 VBS
            for script in spec.scripts:
                if script.language == ScriptLanguage.VBS:
                    diags.append(Diagnostic(
                        code=DiagnosticCodes.CAP_UNSUPPORTED_FEATURE,
                        severity=(
                            DiagnosticSeverity.ERROR
                            if policy == UnsupportedFeaturePolicy.ERROR
                            else DiagnosticSeverity.WARNING
                        ),
                        phase="P10_VALIDATE_DEPENDENCIES",
                        object_type="script",
                        object_name=script.name,
                        message=f"Basic 面板不支持 VBS 脚本 '{script.name}'",
                        remediation=(
                            "请将逻辑改为 PLC 实现或使用 FunctionList"
                        ),
                    ))

            # Basic 不支持 call_script / write_expression
            for screen in spec.screens:
                for item in screen.items:
                    for event in item.events:
                        for action in event.actions:
                            if action.type == SemanticActionType.CALL_SCRIPT:
                                diags.append(Diagnostic(
                                    code=DiagnosticCodes.CAP_UNSUPPORTED_EVENT,
                                    severity=(
                                        DiagnosticSeverity.ERROR
                                        if policy == UnsupportedFeaturePolicy.ERROR
                                        else DiagnosticSeverity.WARNING
                                    ),
                                    phase="P10_VALIDATE_DEPENDENCIES",
                                    object_type="action",
                                    object_name=item.id,
                                    message=(
                                        f"Basic 面板不支持 call_script 动作"
                                        f"（控件 '{item.id}'）"
                                    ),
                                    remediation="请使用 FunctionList 或 PLC 逻辑替代",
                                ))
                            if action.type == SemanticActionType.WRITE_EXPRESSION:
                                diags.append(Diagnostic(
                                    code=DiagnosticCodes.CAP_UNSUPPORTED_EVENT,
                                    severity=(
                                        DiagnosticSeverity.ERROR
                                        if policy == UnsupportedFeaturePolicy.ERROR
                                        else DiagnosticSeverity.WARNING
                                    ),
                                    phase="P10_VALIDATE_DEPENDENCIES",
                                    object_type="action",
                                    object_name=item.id,
                                    message=(
                                        f"Basic 面板不支持 write_expression 动作"
                                        f"（控件 '{item.id}'）"
                                    ),
                                ))

            # Basic 闪烁动态检查
            if not caps.supports("闪烁动态"):
                for screen in spec.screens:
                    for item in screen.items:
                        for binding in item.bindings:
                            if binding.kind == BindingKind.FLASHING:
                                diags.append(Diagnostic(
                                    code=DiagnosticCodes.CAP_UNSUPPORTED_BINDING,
                                    severity=(
                                        DiagnosticSeverity.ERROR
                                        if policy == UnsupportedFeaturePolicy.ERROR
                                        else DiagnosticSeverity.WARNING
                                    ),
                                    phase="P10_VALIDATE_DEPENDENCIES",
                                    object_type="binding",
                                    object_name=item.id,
                                    message=(
                                        f"当前 Basic 设备可能不支持闪烁动态"
                                        f"（控件 '{item.id}'）"
                                    ),
                                    remediation="请在目标设备上验证闪烁能力",
                                ))

        # Comfort 面板不支持 JavaScript
        if caps.family == HmiFamily.COMFORT:
            for script in spec.scripts:
                if script.language == ScriptLanguage.JAVASCRIPT:
                    diags.append(Diagnostic(
                        code=DiagnosticCodes.CAP_UNSUPPORTED_FEATURE,
                        severity=DiagnosticSeverity.WARNING,
                        phase="P10_VALIDATE_DEPENDENCIES",
                        object_type="script",
                        object_name=script.name,
                        message=f"Comfort 面板不支持 JavaScript 脚本 '{script.name}'",
                    ))

        return diags

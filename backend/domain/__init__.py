# -*- coding: utf-8 -*-
"""
HMI IR V2 Domain 层。

提供：
  - IR V2 数据模型（ir_v2）
  - 枚举定义（enums）
  - 校验逻辑（validation）
  - Legacy IR 适配器（legacy_adapter）
  - 诊断模型（diagnostics）
  - 部署计划模型（deployment_plan）
  - 部署结果模型（deployment_result）

本层不依赖 Flask、pythonnet 或 Siemens DLL。
"""

from .ir_v2 import (
    ActionSpec,
    BindingSpec,
    ConnectionSpec,
    DeploymentPolicies,
    EventSpec,
    GeometrySpec,
    HmiProjectSpec,
    ProjectMetadata,
    ResourceSpec,
    ScreenItemSpec,
    ScreenSpec,
    ScriptSpec,
    TagSpec,
    TargetSpec,
)

from .enums import (
    BindingKind,
    ConflictPolicy,
    ConnectionKind,
    DeploymentPhase,
    DiagnosticSeverity,
    HmiFamily,
    MissingDependencyPolicy,
    ScreenItemType,
    ScriptLanguage,
    SemanticActionType,
    SemanticEvent,
    TagScope,
    UnsupportedFeaturePolicy,
)

from .diagnostics import Diagnostic, DiagnosticCodes

from .deployment_plan import DeploymentPlan, DeploymentStep

from .deployment_result import (
    CompileResult,
    DeploymentResult,
    ObjectCountSummary,
    VerificationResult,
)

from .validation import (
    IrV2ValidationError,
    validate_ir_v2,
    validate_or_raise,
)

from .legacy_adapter import LegacyIrAdapter

__all__ = [
    # IR V2 核心模型
    "HmiProjectSpec",
    "ProjectMetadata",
    "TargetSpec",
    "ConnectionSpec",
    "TagSpec",
    "ScreenSpec",
    "ScreenItemSpec",
    "GeometrySpec",
    "BindingSpec",
    "EventSpec",
    "ActionSpec",
    "ScriptSpec",
    "ResourceSpec",
    "DeploymentPolicies",
    # 枚举
    "HmiFamily",
    "TagScope",
    "ConnectionKind",
    "ScreenItemType",
    "BindingKind",
    "SemanticEvent",
    "SemanticActionType",
    "ScriptLanguage",
    "DiagnosticSeverity",
    "DeploymentPhase",
    "ConflictPolicy",
    "UnsupportedFeaturePolicy",
    "MissingDependencyPolicy",
    # 诊断
    "Diagnostic",
    "DiagnosticCodes",
    # 部署
    "DeploymentPlan",
    "DeploymentStep",
    "DeploymentResult",
    "VerificationResult",
    "CompileResult",
    "ObjectCountSummary",
    # 校验
    "IrV2ValidationError",
    "validate_ir_v2",
    "validate_or_raise",
    # 适配器
    "LegacyIrAdapter",
]

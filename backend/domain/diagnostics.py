# -*- coding: utf-8 -*-
"""
诊断与错误模型。

不依赖 Flask、pythonnet 或 Siemens DLL。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .enums import DiagnosticSeverity


class Diagnostic(BaseModel):
    """结构化诊断信息。

    用于部署计划、能力验证、编译等各阶段输出统一的诊断结果。
    """

    code: str = Field(..., description="错误代码，如 CAP_UNSUPPORTED_EVENT")
    severity: DiagnosticSeverity = Field(
        default=DiagnosticSeverity.ERROR, description="严重等级"
    )
    phase: str = Field(default="", description="发生阶段")
    object_type: str | None = Field(default=None, description="涉及对象类型")
    object_name: str | None = Field(default=None, description="涉及对象名称")
    message: str = Field(..., description="人类可读的诊断描述")
    details: dict[str, Any] = Field(default_factory=dict, description="附加详情")
    remediation: str | None = Field(
        default=None, description="建议的修复措施"
    )


# ---------------------------------------------------------------------------
# 常用错误码（与方案文档 §17 对齐）
# ---------------------------------------------------------------------------

class DiagnosticCodes:
    """标准诊断错误码。

    不允许硬编码字符串，统一通过此类引用。
    """

    # 能力相关
    CAP_UNSUPPORTED_EVENT = "CAP_UNSUPPORTED_EVENT"
    CAP_UNSUPPORTED_BINDING = "CAP_UNSUPPORTED_BINDING"
    CAP_UNSUPPORTED_SCREEN_ITEM = "CAP_UNSUPPORTED_SCREEN_ITEM"
    CAP_UNSUPPORTED_FEATURE = "CAP_UNSUPPORTED_FEATURE"

    # 依赖相关
    DEP_MISSING_CONNECTION = "DEP_MISSING_CONNECTION"
    DEP_MISSING_CONTROLLER_TAG = "DEP_MISSING_CONTROLLER_TAG"
    DEP_MISSING_TAG_TABLE = "DEP_MISSING_TAG_TABLE"
    DEP_MISSING_SCRIPT = "DEP_MISSING_SCRIPT"

    # Classic XML 相关
    CLASSIC_FRAGMENT_NOT_FOUND = "CLASSIC_FRAGMENT_NOT_FOUND"
    CLASSIC_SCHEMA_MISMATCH = "CLASSIC_SCHEMA_MISMATCH"
    CLASSIC_BROKEN_LINK = "CLASSIC_BROKEN_LINK"
    CLASSIC_DUPLICATE_ID = "CLASSIC_DUPLICATE_ID"

    # Unified 相关
    UNIFIED_TYPE_NOT_FOUND = "UNIFIED_TYPE_NOT_FOUND"
    UNIFIED_EVENT_ENUM_AMBIGUOUS = "UNIFIED_EVENT_ENUM_AMBIGUOUS"
    UNIFIED_PROPERTY_NOT_SUPPORTED = "UNIFIED_PROPERTY_NOT_SUPPORTED"

    # 脚本相关
    SCRIPT_SECURITY_REJECTED = "SCRIPT_SECURITY_REJECTED"
    SCRIPT_SYNTAX_FAILED = "SCRIPT_SYNTAX_FAILED"

    # 导入/编译相关
    IMPORT_TIA_EXCEPTION = "IMPORT_TIA_EXCEPTION"
    COMPILE_ERROR = "COMPILE_ERROR"
    COMPILE_WARNING = "COMPILE_WARNING"

    # 验证相关
    VERIFY_TAG_MISSING = "VERIFY_TAG_MISSING"
    VERIFY_EVENT_MISSING = "VERIFY_EVENT_MISSING"
    VERIFY_BINDING_MISSING = "VERIFY_BINDING_MISSING"
    VERIFY_SCRIPT_MISSING = "VERIFY_SCRIPT_MISSING"
    VERIFY_SCREEN_MISSING = "VERIFY_SCREEN_MISSING"

    # 通用
    IR_VALIDATION_ERROR = "IR_VALIDATION_ERROR"
    LEGACY_ADAPTER_WARNING = "LEGACY_ADAPTER_WARNING"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"

    # 部署状态机
    TARGET_FAMILY_AMBIGUOUS = "TARGET_FAMILY_AMBIGUOUS"
    TIA_NOT_CONNECTED = "TIA_NOT_CONNECTED"
    DEPLOY_BLOCKED = "DEPLOY_BLOCKED"
    DEPLOY_FAILED = "DEPLOY_FAILED"
    VERIFY_FAILED = "VERIFY_FAILED"

    # 编译相关
    COMPILE_SUCCESS = "COMPILE_SUCCESS"
    COMPILE_FAILED = "COMPILE_FAILED"

    # 运行时契约
    CONTRACT_MISSING_TYPE = "CONTRACT_MISSING_TYPE"
    CONTRACT_MISSING_METHOD = "CONTRACT_MISSING_METHOD"
    CONTRACT_MISSING_PROPERTY = "CONTRACT_MISSING_PROPERTY"
    CONTRACT_MISSING_EVENT = "CONTRACT_MISSING_EVENT"
    CONTRACT_DYNAMIZATION_UNSUPPORTED = "CONTRACT_DYNAMIZATION_UNSUPPORTED"

# -*- coding: utf-8 -*-
"""
异常映射器 — 将 .NET/Openness 异常转换为结构化 Diagnostic。

负责：
  - 捕获 .NET 异常并提取信息
  - 映射到标准 Diagnostic 错误码
  - 保留原始 stack trace 但不直接返回前端
"""

from __future__ import annotations

import traceback
from typing import Any

from backend.domain.diagnostics import Diagnostic, DiagnosticCodes
from backend.domain.enums import DiagnosticSeverity


class ExceptionMapper:
    """.NET 异常 → Diagnostic 转换器。

    使用方式:
        mapper = ExceptionMapper()
        diagnostic = mapper.map(exception, phase="P50_SCREENS", object_name="Screen1")
    """

    # 已知 .NET 异常消息模式 → 错误码
    _PATTERN_MAP: dict[str, str] = {
        "already exists": DiagnosticCodes.CLASSIC_DUPLICATE_ID,
        "does not exist": DiagnosticCodes.DEP_MISSING_CONTROLLER_TAG,
        "not found": DiagnosticCodes.UNIFIED_TYPE_NOT_FOUND,
        "access denied": DiagnosticCodes.DEP_MISSING_CONNECTION,
        "disposed": DiagnosticCodes.IMPORT_TIA_EXCEPTION,
        "cannot import": DiagnosticCodes.IMPORT_TIA_EXCEPTION,
        "compile error": DiagnosticCodes.COMPILE_ERROR,
        "syntax error": DiagnosticCodes.SCRIPT_SYNTAX_FAILED,
        "not supported": DiagnosticCodes.CAP_UNSUPPORTED_FEATURE,
    }

    def map(
        self,
        exception: Exception,
        phase: str = "",
        object_type: str | None = None,
        object_name: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> Diagnostic:
        """将异常映射为 Diagnostic。

        参数:
            exception: 捕获的异常。
            phase: 发生阶段。
            object_type: 相关对象类型。
            object_name: 相关对象名称。
            context: 额外的上下文信息。

        返回:
            Diagnostic 实例。
        """
        msg = str(exception)

        # 匹配已知模式
        code = DiagnosticCodes.IMPORT_TIA_EXCEPTION
        msg_lower = msg.lower()
        for pattern, mapped_code in self._PATTERN_MAP.items():
            if pattern in msg_lower:
                code = mapped_code
                break

        details: dict[str, Any] = {
            "exception_type": type(exception).__name__,
            "traceback": traceback.format_exc(),
        }
        if context:
            details["context"] = context

        return Diagnostic(
            code=code,
            severity=DiagnosticSeverity.ERROR,
            phase=phase,
            object_type=object_type,
            object_name=object_name,
            message=f"TIA 操作异常：{msg}",
            details=details,
            remediation=self._suggest_remediation(code),
        )

    @staticmethod
    def _suggest_remediation(code: str) -> str | None:
        remediations = {
            DiagnosticCodes.CLASSIC_DUPLICATE_ID: (
                "对象已存在，请使用 conflict_policy=rename 或手动删除后重试"
            ),
            DiagnosticCodes.DEP_MISSING_CONTROLLER_TAG: (
                "请先在 PLC 中创建对应的 Tag/DB 成员，并确保集成连接已存在"
            ),
            DiagnosticCodes.UNIFIED_TYPE_NOT_FOUND: (
                "目标 TIA 版本可能不支持该控件类型，请检查版本兼容性并运行反射确认"
            ),
            DiagnosticCodes.IMPORT_TIA_EXCEPTION: (
                "请确认 XML 格式兼容当前 TIA 版本，检查命名空间和 schema"
            ),
            DiagnosticCodes.COMPILE_ERROR: (
                "请检查变量引用、事件配置和脚本语法，在 TIA Portal 中手动编译查看详情"
            ),
            DiagnosticCodes.SCRIPT_SYNTAX_FAILED: (
                "请检查脚本语法，确保变量名存在且 API 调用合规"
            ),
        }
        return remediations.get(code)

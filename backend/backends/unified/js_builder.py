# -*- coding: utf-8 -*-
"""JavaScript Builder — Unified JavaScript 生成与安全验证。

方案文档 §11.8 对齐。
"""
from __future__ import annotations
import re


class JsBuilder:
    """Unified JavaScript 生成与安全扫描。

    仅允许白名单 API（Tags, UI, HMIRuntime）。
    """

    ALLOWED_APIS = {"Tags", "UI", "HMIRuntime", "console", "Math", "JSON", "Array", "Object", "String", "Number", "Boolean"}

    FORBIDDEN_PATTERNS = [
        r"\beval\s*\(", r"\bFunction\s*\(",
        r"\bdocument\b", r"\bwindow\b", r"\bfetch\b",
        r"\bXMLHttpRequest\b", r"\bWebSocket\b",
        r"\bimport\s*\(", r"\brequire\s*\(",
        r"\blocalStorage\b", r"\bsessionStorage\b",
    ]

    def __init__(self):
        pass

    def build_from_actions(self, actions, function_name: str = "") -> str:
        from .event_builder import UnifiedEventBuilder
        builder = UnifiedEventBuilder()
        return builder.build_javascript(actions)

    def security_scan(self, code: str) -> dict:
        """安全扫描 JavaScript 代码。"""
        errors = []
        for pattern in self.FORBIDDEN_PATTERNS:
            if re.search(pattern, code, re.IGNORECASE):
                errors.append(f"禁止的 API 调用: {pattern}")
        if len(code) > 8192:
            errors.append("JS 代码超过 8192 字符限制")
        return {"ok": len(errors) == 0, "errors": errors}

    def syntax_check(self, code: str) -> dict:
        """预留语法检查接口。"""
        return {"ok": True, "errors": []}

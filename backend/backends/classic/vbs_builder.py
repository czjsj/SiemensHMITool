# -*- coding: utf-8 -*-
"""VBS Builder — Comfort 面板的 VBS 脚本生成与安全验证。

方案文档 §10.3 对齐。
"""
from __future__ import annotations
import re
from backend.domain.ir_v2 import ActionSpec, ScriptSpec
from backend.domain.enums import SemanticActionType


class VbsBuilder:
    """Comfort 面板 VBS 脚本生成器。

    仅用于 FunctionList 无法表达的复杂逻辑。
    禁止直接执行外部程序、文件系统写入、Shell。
    """

    # 白名单 SmartTags API
    ALLOWED_APIS = {"SmartTags", "CInt", "CDbl", "CStr", "CBool", "If", "Then", "Else", "End", "Not", "And", "Or"}

    # 禁止的 API
    FORBIDDEN_PATTERNS = [
        r"\bShell\b", r"\bCreateObject\b", r"\bWScript\b",
        r"\bFileSystemObject\b", r"\bOpen\b.*\bFor\b",
        r"\bExecute\b", r"\bEval\b", r"\bSendKeys\b",
    ]

    def __init__(self):
        pass

    def build_toggle(self, tag: str) -> str:
        safe = self.quote_smarttag(tag)
        return f"SmartTags(\"{safe}\") = Not SmartTags(\"{safe}\")"

    def build_set_bit(self, tag: str, value: int = 1) -> str:
        safe = self.quote_smarttag(tag)
        return f"SmartTags(\"{safe}\") = {value}"

    def build_reset_bit(self, tag: str) -> str:
        safe = self.quote_smarttag(tag)
        return f"SmartTags(\"{safe}\") = 0"

    def build_set_value(self, tag: str, value) -> str:
        safe = self.quote_smarttag(tag)
        return f"SmartTags(\"{safe}\") = {value}"

    def build_set_by_condition(self, condition_tag: str, target_tag: str, true_value, false_value) -> str:
        c = self.quote_smarttag(condition_tag)
        t = self.quote_smarttag(target_tag)
        return (
            f"If SmartTags(\"{c}\") = 1 Then\n"
            f"  SmartTags(\"{t}\") = {true_value}\n"
            f"Else\n"
            f"  SmartTags(\"{t}\") = {false_value}\n"
            f"End If"
        )

    def build_from_action(self, action: ActionSpec) -> str:
        tag = action.tag or ""
        if action.type == SemanticActionType.TOGGLE_BIT:
            return self.build_toggle(tag)
        if action.type == SemanticActionType.SET_BIT:
            return self.build_set_bit(tag, int(action.value or 1))
        if action.type == SemanticActionType.RESET_BIT:
            return self.build_reset_bit(tag)
        if action.type == SemanticActionType.SET_VALUE:
            return self.build_set_value(tag, action.value or 0)
        if action.type == SemanticActionType.INCREMENT:
            safe = self.quote_smarttag(tag)
            return f"SmartTags(\"{safe}\") = SmartTags(\"{safe}\") + {action.value or 1}"
        if action.type == SemanticActionType.DECREMENT:
            safe = self.quote_smarttag(tag)
            return f"SmartTags(\"{safe}\") = SmartTags(\"{safe}\") - {action.value or 1}"
        return f"' Unsupported action: {action.type.value}"

    def security_scan(self, code: str) -> dict:
        """安全扫描 VBS 代码。返回 {"ok": bool, "errors": [...]}。"""
        errors = []
        for pattern in self.FORBIDDEN_PATTERNS:
            if re.search(pattern, code, re.IGNORECASE):
                errors.append(f"禁止的 API 调用: {pattern}")
        if len(code) > 4096:
            errors.append("VBS 代码超过 4096 字符限制")
        return {"ok": len(errors) == 0, "errors": errors}

    @staticmethod
    def quote_smarttag(tag: str) -> str:
        """安全转义 SmartTags 内的变量名。"""
        return tag.replace('"', '""')

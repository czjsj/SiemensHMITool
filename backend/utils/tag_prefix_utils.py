# -*- coding: utf-8 -*-
"""
HMI 变量名前缀工具 — 纯字符串操作，无 .NET 依赖。

提供幂等的前缀剥离/确保/检查函数，用于变量命名中避免重复前缀。
"""

from __future__ import annotations

KNOWN_TAG_PREFIXES = ("BTN_", "MEM_", "STS_", "LMP_", "IO_", "SIO_", "TXT_")


def strip_known_tag_prefixes(name: str) -> str:
    """递归剥离所有已知前缀，直到没有匹配的前缀为止。

    示例:
        "BTN_BTN_Start"    -> "Start"
        "BTN_Start"        -> "Start"
        "LMP_LMP_Fault"    -> "Fault"
        "STS_LMP_Run"      -> "Run"
        "Motor_Start"      -> "Motor_Start"  (无已知前缀，不变)
        ""                 -> ""
    """
    if not name:
        return name

    previous = None
    current = name
    while current != previous:
        previous = current
        for prefix in KNOWN_TAG_PREFIXES:
            if current.startswith(prefix):
                current = current[len(prefix):]
                break
    return current


def has_known_tag_prefix(name: str) -> bool:
    """检查 name 是否以任何已知前缀开头。"""
    if not name:
        return False
    return any(name.startswith(p) for p in KNOWN_TAG_PREFIXES)


def ensure_tag_prefix(name: str, prefix: str) -> str:
    """幂等地确保 name 以指定 prefix 开头。

    先递归剥离所有已知前缀，再添加所需前缀。

    示例:
        ensure_tag_prefix("Start", "BTN_")           -> "BTN_Start"
        ensure_tag_prefix("BTN_Start", "BTN_")       -> "BTN_Start"
        ensure_tag_prefix("BTN_BTN_Start", "BTN_")   -> "BTN_Start"
        ensure_tag_prefix("LMP_Fault", "LMP_")        -> "LMP_Fault"
        ensure_tag_prefix("LMP_LMP_Fault", "LMP_")    -> "LMP_Fault"
        ensure_tag_prefix("STS_LMP_Run", "STS_")      -> "STS_Run"
        ensure_tag_prefix("", "BTN_")                 -> "BTN_"
    """
    base = strip_known_tag_prefixes(name)
    return prefix + base

# -*- coding: utf-8 -*-
"""
静态 HMI 设备能力矩阵。

方案文档 §7 对齐。矩阵不能代替目标版本实际验证；
运行时反射（runtime_discovery）用于最终确认。
"""

from __future__ import annotations

from typing import Literal


class CapabilityEntry:
    """单项能力描述。"""

    def __init__(self, name: str, basic: str, comfort: str, unified: str):
        self.name = name
        self.basic = basic      # "yes" | "no" | "limited" | "device"
        self.comfort = comfort
        self.unified = unified


# fmt: off
STATIC_CAPABILITY_MATRIX: list[CapabilityEntry] = [
    CapabilityEntry("画面导入/创建",          "yes",      "yes",      "yes"),
    CapabilityEntry("HMI变量表导入/创建",     "yes",      "yes",      "yes"),
    CapabilityEntry("外部变量",               "yes",      "yes",      "yes"),
    CapabilityEntry("内部变量",               "yes",      "yes",      "yes"),
    CapabilityEntry("系统FunctionList",       "yes",      "yes",      "no"),
    CapabilityEntry("VBS",                    "no",       "yes",      "no"),
    CapabilityEntry("JavaScript",             "no",       "no",       "yes"),
    CapabilityEntry("标签动态化",             "limited",  "yes",      "yes"),
    CapabilityEntry("离散颜色动态",           "yes",      "yes",      "yes"),
    CapabilityEntry("闪烁动态",               "device",   "yes",      "yes"),
    CapabilityEntry("动态可操作性",           "limited",  "yes",      "yes"),
    CapabilityEntry("Popup/Slide-in",         "limited",  "device",   "yes"),
    CapabilityEntry("Faceplate",              "limited",  "yes",      "yes"),
    CapabilityEntry("直接强类型创建ScreenItem", "no",     "no",       "yes"),
    CapabilityEntry("TextList",               "yes",      "yes",      "yes"),
    CapabilityEntry("GraphicList",            "limited",  "yes",      "yes"),
]
# fmt: on


def get_capability(name: str, family: str) -> str:
    """按能力名称和设备家族查询静态矩阵。

    返回 "yes" / "no" / "limited" / "device"。
    未找到能力名称时返回 "unknown"。
    """
    attr_map = {
        "basic": "basic",
        "comfort": "comfort",
        "unified": "unified",
    }
    attr = attr_map.get(family.lower())
    if not attr:
        return "unknown"

    for entry in STATIC_CAPABILITY_MATRIX:
        if entry.name == name:
            return getattr(entry, attr, "unknown")

    return "unknown"

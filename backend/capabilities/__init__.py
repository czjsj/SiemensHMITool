# -*- coding: utf-8 -*-
"""
HMI 设备能力矩阵与服务。

提供：
  - static_matrix: 静态设备能力对照表
  - capability_service: 目标能力解析与项目校验
"""

from .static_matrix import (
    STATIC_CAPABILITY_MATRIX,
    CapabilityEntry,
    get_capability,
)
from .capability_service import CapabilityService

__all__ = [
    "STATIC_CAPABILITY_MATRIX",
    "CapabilityEntry",
    "get_capability",
    "CapabilityService",
]

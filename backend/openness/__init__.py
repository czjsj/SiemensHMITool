# -*- coding: utf-8 -*-
"""
Openness 运行时层 — TIA Portal Openness 接口的模块化拆分。

职责边界：
  - 所有 .NET/Siemens.DLL 依赖仅在此层；
  - domain / capabilities / planners 层不得引用此层；
  - 对外提供统一的 façade（OpennessManager）。

分层：
  assembly_loader   — DLL 加载与版本元数据
  session_manager   — TIA Portal 会话（Attach/Open/Dispose）
  device_discovery  — HMI 设备查找与类型识别
  compiler          — HMI 编译触发
  exception_mapper  — .NET 异常 → Diagnostic 转换
"""

from .assembly_loader import AssemblyLoader, AssemblyMetadata
from .session_manager import SessionManager
from .device_discovery import DeviceDiscovery
from .compiler import HmiCompiler
from .exception_mapper import ExceptionMapper

__all__ = [
    "AssemblyLoader",
    "AssemblyMetadata",
    "SessionManager",
    "DeviceDiscovery",
    "HmiCompiler",
    "ExceptionMapper",
]

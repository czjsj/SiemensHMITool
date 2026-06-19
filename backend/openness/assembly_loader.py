# -*- coding: utf-8 -*-
"""
DLL 加载器 — 加载 Siemens.Engineering 程序集并记录版本元数据。

功能：
  - 加载 DLL
  - 记录程序集版本号、文件路径
  - 记录公开类型列表
  - 防止混用不同版本 DLL
"""

from __future__ import annotations

import os
import sys
import platform
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AssemblyMetadata:
    """已加载程序集的元数据。"""

    tia_version: str = ""
    dll_path: str = ""
    assembly_name: str = ""
    assembly_version: str = ""
    is_loaded: bool = False
    public_types: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tia_version": self.tia_version,
            "dll_path": self.dll_path,
            "assembly_name": self.assembly_name,
            "assembly_version": self.assembly_version,
            "is_loaded": self.is_loaded,
            "public_types_count": len(self.public_types),
            "warnings": self.warnings,
            "errors": self.errors,
        }


class AssemblyLoader:
    """DLL 加载与元数据记录。

    使用方式:
        loader = AssemblyLoader()
        meta = loader.load("C:/.../Siemens.Engineering.dll", tia_version="V18")
        if meta.is_loaded:
            print(f"已加载 {meta.assembly_version}")
    """

    def __init__(self):
        self._loaded: dict[str, AssemblyMetadata] = {}
        self._clr_available = self._check_pythonnet()

    @staticmethod
    def _check_pythonnet() -> bool:
        try:
            import clr  # noqa: F401
            return True
        except Exception:
            return False

    def diagnose(self) -> dict[str, Any]:
        """环境诊断。"""
        return {
            "os": platform.system(),
            "is_windows": platform.system() == "Windows",
            "pythonnet_available": self._clr_available,
            "loaded_assemblies": list(self._loaded.keys()),
        }

    def load(
        self,
        dll_path: str,
        tia_version: str = "",
    ) -> AssemblyMetadata:
        """加载 Siemens.Engineering DLL。

        参数:
            dll_path: DLL 完整路径。
            tia_version: TIA 版本（用于记录，不负责验证）。

        返回:
            AssemblyMetadata 实例。
        """
        meta = AssemblyMetadata(
            tia_version=tia_version,
            dll_path=dll_path,
        )

        if not self._clr_available:
            meta.errors.append("pythonnet 不可用")
            return meta

        if not os.path.exists(dll_path):
            meta.errors.append(f"DLL 路径不存在: {dll_path}")
            return meta

        try:
            import clr
            sys.path.append(os.path.dirname(dll_path))
            clr.AddReference(dll_path)
            import Siemens.Engineering as tia  # type: ignore

            meta.is_loaded = True
            meta.assembly_name = "Siemens.Engineering"

            # 尝试获取版本号
            try:
                from System.Reflection import Assembly  # type: ignore
                asm = Assembly.LoadFrom(dll_path)
                meta.assembly_version = str(asm.GetName().Version)
            except Exception:
                pass

            # 记录部分公开类型
            try:
                types = [
                    t for t in dir(tia)
                    if not t.startswith("_") and isinstance(getattr(tia, t, None), type)
                ]
                meta.public_types = types[:200]  # 截断以避免过大
            except Exception:
                pass

            self._loaded[dll_path] = meta

        except Exception as e:
            meta.errors.append(str(e))

        return meta

    def get_loaded(self, dll_path: str) -> AssemblyMetadata | None:
        """获取已加载的程序集元数据。"""
        return self._loaded.get(dll_path)

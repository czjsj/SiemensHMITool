# -*- coding: utf-8 -*-
"""Unified Runtime Contract — 运行时 DLL 探测与版本化 JSON 缓存。

枚举当前 DLL 中:
  - Unified 类型
  - Create 方法
  - 属性
  - Event 枚举
  - Dynamization 类型

结果保存为 runtime_cache/<tia-version>/<assembly-hash>.json。
"""
from __future__ import annotations
import os
import json
import hashlib
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuntimeContract:
    """Unified 运行时契约 — DLL 反射结果。"""

    tia_version: str = ""
    assembly_hash: str = ""
    types: list[str] = field(default_factory=list)
    create_methods: list[str] = field(default_factory=list)
    properties: dict[str, list[str]] = field(default_factory=dict)
    event_enums: dict[str, list[str]] = field(default_factory=dict)
    dynamization_types: list[str] = field(default_factory=list)
    scanned_at: str = ""
    dll_path: str = ""
    errors: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.types

    def to_dict(self) -> dict[str, Any]:
        return {
            "tia_version": self.tia_version,
            "assembly_hash": self.assembly_hash,
            "types": self.types,
            "create_methods": self.create_methods,
            "properties": self.properties,
            "event_enums": self.event_enums,
            "dynamization_types": self.dynamization_types,
            "scanned_at": self.scanned_at,
            "dll_path": self.dll_path,
            "errors": self.errors,
        }

    def save(self, cache_root: str = ""):
        if not cache_root:
            cache_root = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "runtime_cache",
            )
        ver_dir = os.path.join(cache_root, self.tia_version or "unknown")
        os.makedirs(ver_dir, exist_ok=True)
        path = os.path.join(ver_dir, f"{self.assembly_hash}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, tia_version: str, assembly_hash: str, cache_root: str = "") -> "RuntimeContract | None":
        if not cache_root:
            cache_root = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "runtime_cache",
            )
        path = os.path.join(cache_root, tia_version, f"{assembly_hash}.json")
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(
            tia_version=data.get("tia_version", ""),
            assembly_hash=data.get("assembly_hash", ""),
            types=data.get("types", []),
            create_methods=data.get("create_methods", []),
            properties=data.get("properties", {}),
            event_enums=data.get("event_enums", {}),
            dynamization_types=data.get("dynamization_types", []),
            scanned_at=data.get("scanned_at", ""),
            dll_path=data.get("dll_path", ""),
            errors=data.get("errors", []),
        )

    @classmethod
    def from_dll_reflection(
        cls, tia_version: str, dll_path: str, reflection_result: dict,
    ) -> "RuntimeContract":
        asm_bytes = dll_path.encode() if dll_path else b""
        asm_hash = hashlib.sha256(asm_bytes).hexdigest()[:16]
        from datetime import datetime, timezone
        return cls(
            tia_version=tia_version,
            assembly_hash=asm_hash,
            types=reflection_result.get("types", []),
            create_methods=reflection_result.get("create_methods", []),
            properties=reflection_result.get("properties", {}),
            event_enums=reflection_result.get("event_enums", {}),
            dynamization_types=reflection_result.get("dynamization_types", []),
            scanned_at=datetime.now(timezone.utc).isoformat(),
            dll_path=dll_path,
            errors=reflection_result.get("errors", []),
        )


class RuntimeProber:
    """运行时探针 — 扫描 DLL 中 Unified 类型、方法、属性、枚举。

    无真实 DLL 时返回空 contract。
    """

    def __init__(self):
        self._clr_available = False
        try:
            import clr  # noqa: F401
            self._clr_available = True
        except Exception:
            pass

    def probe(self, tia_version: str = "", dll_path: str = "") -> RuntimeContract:
        """探测 DLL 并返回 RuntimeContract。"""
        from datetime import datetime, timezone

        if not self._clr_available:
            return RuntimeContract(
                tia_version=tia_version,
                assembly_hash="no-pythonnet",
                errors=["pythonnet 不可用，无法进行运行时反射"],
            )

        if not dll_path or not os.path.exists(dll_path):
            return RuntimeContract(
                tia_version=tia_version,
                assembly_hash="no-dll",
                errors=["DLL 路径不存在或未配置"],
            )

        try:
            import clr
            import sys
            sys.path.append(os.path.dirname(dll_path))
            clr.AddReference(dll_path)

            types = []
            create_methods = []
            properties: dict[str, list[str]] = {}
            event_enums: dict[str, list[str]] = {}
            dynamization_types = []
            errors = []

            # 尝试加载 HmiUnified
            try:
                import Siemens.Engineering.HmiUnified as hu  # type: ignore
                for name in dir(hu):
                    if not name.startswith("_") and not name[0].islower():
                        obj = getattr(hu, name)
                        if isinstance(obj, type):
                            types.append(name)
                            # 收集公共方法
                            methods = [m for m in dir(obj) if not m.startswith("_") and callable(getattr(obj, m, None))]
                            create_methods.extend([f"{name}.{m}" for m in methods if "Create" in m])
                            # 收集属性
                            prop_names = [p for p in dir(obj) if not p.startswith("_") and not callable(getattr(obj, p, None))]
                            if prop_names:
                                properties[name] = prop_names
            except Exception as e:
                errors.append(f"HmiUnified load failed: {e}")

            # 尝试加载 ExportOptions 枚举
            try:
                from Siemens.Engineering import ExportOptions  # type: ignore
                for attr in dir(ExportOptions):
                    if not attr.startswith("_"):
                        event_enums.setdefault("ExportOptions", []).append(attr)
            except Exception:
                pass

            return RuntimeContract(
                tia_version=tia_version,
                assembly_hash=hashlib.sha256(dll_path.encode()).hexdigest()[:16],
                types=types,
                create_methods=create_methods,
                properties=properties,
                event_enums=event_enums,
                dynamization_types=dynamization_types,
                scanned_at=datetime.now(timezone.utc).isoformat(),
                dll_path=dll_path,
                errors=errors,
            )

        except Exception as e:
            return RuntimeContract(
                tia_version=tia_version,
                assembly_hash="reflection-failed",
                errors=[str(e)],
            )

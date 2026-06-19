# -*- coding: utf-8 -*-
"""XML Fragment Catalog — 清单加载、校验与 fragment 克隆。

方案文档 §12 对齐。
"""
from __future__ import annotations
import os
import yaml
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ManifestEntry:
    key: str
    path: str
    description: str = ""

    def to_dict(self) -> dict:
        return {"key": self.key, "path": self.path, "description": self.description}


@dataclass
class CatalogManifest:
    catalog_version: int = 1
    key: dict = field(default_factory=dict)
    source: dict = field(default_factory=dict)
    fragments: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, yaml_path: str) -> "CatalogManifest":
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls(
            catalog_version=data.get("catalog_version", 1),
            key=data.get("key", {}),
            source=data.get("source", {}),
            fragments=data.get("fragments", {}),
        )

    def get_fragment_path(self, key: str) -> str | None:
        return self.fragments.get(key)

    @property
    def verified_import(self) -> bool:
        return bool(self.source.get("verified_import", False) or self.source.get("verified", False))

    @property
    def verified_compile(self) -> bool:
        return bool(self.source.get("verified_compile", False))

    @property
    def source_project_name(self) -> str:
        return self.source.get("project_name", "")

    @property
    def source_export_timestamp(self) -> str:
        return self.source.get("exported_at", "")

    def validate(self) -> list[str]:
        errors = []
        if self.catalog_version < 1:
            errors.append("catalog_version 必须 >= 1")
        if not self.key.get("tia_version"):
            errors.append("key.tia_version 缺失")
        if not self.key.get("family"):
            errors.append("key.family 缺失")
        if not self.fragments:
            errors.append("fragments 为空")
        if not self.source_project_name:
            errors.append("source.project_name 缺失")
        return errors


class XmlFragmentCatalog:
    """XML Fragment Catalog — 加载、校验、提供服务。"""

    def __init__(self, catalog_root: str = ""):
        self._root = catalog_root or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
            "reference_catalog",
        )
        self._manifests: dict[str, CatalogManifest] = {}
        self._fragment_cache: dict[str, str] = {}

    def load_manifest(self, manifest_path: str) -> CatalogManifest:
        m = CatalogManifest.from_yaml(manifest_path)
        key = f"{m.key.get('tia_version','')}/{m.key.get('family','')}/{m.key.get('device_type','')}"
        self._manifests[key] = m
        return m

    def find_manifest(self, tia_version: str, family: str, device_type: str = "") -> CatalogManifest | None:
        for key, m in self._manifests.items():
            k = m.key
            if k.get("tia_version") == tia_version and k.get("family", "").lower() == family.lower():
                if not device_type or k.get("device_type", "").lower() == device_type.lower():
                    return m
        return None

    def get_fragment(self, manifest: CatalogManifest, fragment_key: str) -> str | None:
        cache_k = f"{manifest.key.get('tia_version','')}/{fragment_key}"
        if cache_k in self._fragment_cache:
            return self._fragment_cache[cache_k]

        rel_path = manifest.get_fragment_path(fragment_key)
        if not rel_path:
            return None

        full = os.path.join(self._root, rel_path)
        if not os.path.exists(full):
            full = os.path.join(os.path.dirname(self._root), rel_path)
        if not os.path.exists(full):
            return None

        with open(full, "r", encoding="utf-8") as f:
            content = f.read()
        self._fragment_cache[cache_k] = content
        return content

    def list_manifests(self) -> list[dict]:
        return [
            {"key": m.key, "catalog_version": m.catalog_version, "fragment_count": len(m.fragments)}
            for m in self._manifests.values()
        ]

    def validate_contract(self, manifest: CatalogManifest) -> list[str]:
        errors = manifest.validate()
        for frag_key, rel_path in manifest.fragments.items():
            full = os.path.join(self._root, rel_path)
            if not os.path.exists(full):
                full = os.path.join(os.path.dirname(self._root), rel_path)
            if not os.path.exists(full):
                errors.append(f"Fragment 文件不存在: {frag_key} → {rel_path}")
        return errors

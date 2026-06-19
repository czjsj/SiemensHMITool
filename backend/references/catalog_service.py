# -*- coding: utf-8 -*-
"""Catalog Service — 黄金参考工程 catalog 服务。

负责查找、加载 manifest，提供 fragment lookup。
"""
from __future__ import annotations
import os
from backend.backends.classic.xml_fragment_catalog import XmlFragmentCatalog, CatalogManifest


class CatalogService:
    """黄金参考 catalog 服务。

    使用方式:
        svc = CatalogService("reference_catalog")
        manifest = svc.find("V20", "comfort", "TP1200 Comfort")
        fragment = svc.get_fragment(manifest, "controls.button")
    """

    def __init__(self, catalog_root: str = ""):
        self._catalog = XmlFragmentCatalog(catalog_root)
        self._root = self._catalog._root

    def find(self, tia_version: str, family: str, device_type: str = "") -> CatalogManifest | None:
        # Auto-load if no manifests yet
        if not self._catalog._manifests:
            self.load_all()
        return self._catalog.find_manifest(tia_version, family, device_type)

    def get_fragment(self, manifest: CatalogManifest, fragment_key: str) -> str | None:
        return self._catalog.get_fragment(manifest, fragment_key)

    def load_all(self) -> list[CatalogManifest]:
        """扫描 catalog_root 并加载所有 manifest.yaml。"""
        manifests = []
        for root, dirs, files in os.walk(self._root):
            for f in files:
                if f == "manifest.yaml":
                    full = os.path.join(root, f)
                    try:
                        m = self._catalog.load_manifest(full)
                        manifests.append(m)
                    except Exception:
                        pass
        return manifests

    def validate_all(self) -> dict[str, list[str]]:
        """校验所有已加载 manifest 的完整性。"""
        results = {}
        for m in self._catalog._manifests.values():
            key = f"{m.key.get('tia_version','')}/{m.key.get('family','')}"
            results[key] = self._catalog.validate_contract(m)
        return results

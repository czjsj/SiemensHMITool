# -*- coding: utf-8 -*-
"""XmlIdRegistry — 确定性 XML ID 分配。

同一部署输入在同一目标下生成稳定 ID。
"""
from __future__ import annotations
import hashlib
import xml.etree.ElementTree as ET
from typing import Any


class XmlIdRegistry:
    """确定性 XML ID 注册器。

    生成稳定的十六进制 ID，同一 logical_key 总是返回相同 ID。
    """

    def __init__(self, seed: str = ""):
        self._seed = seed
        self._allocated: dict[str, str] = {}
        self._by_id: dict[str, str] = {}
        self._counter = 0

    def allocate(self, logical_key: str) -> str:
        if logical_key in self._allocated:
            return self._allocated[logical_key]

        h = hashlib.sha256(f"{self._seed}:{logical_key}".encode()).hexdigest()[:8].upper()
        if h in self._by_id:
            h = self._allocate_fallback(logical_key)
        self._allocated[logical_key] = h
        self._by_id[h] = logical_key
        return h

    def _allocate_fallback(self, logical_key: str) -> str:
        while True:
            self._counter += 1
            cand = f"{self._counter:08X}"
            if cand not in self._by_id:
                return cand

    def register_existing(self, xml_root: ET.Element):
        for elem in xml_root.iter():
            id_val = elem.get("ID") or elem.get("Id") or elem.get("id")
            if id_val:
                self._by_id[str(id_val)] = "existing"

    def rewrite_subtree(self, subtree: ET.Element) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for elem in subtree.iter():
            for attr in ("ID", "Id", "id"):
                if attr in elem.attrib:
                    old = str(elem.attrib[attr])
                    logical_key = f"{self._seed}:{old}"
                    new = self.allocate(logical_key)
                    elem.set(attr, new)
                    mapping[old] = new
        return mapping

    def assert_unique(self, root: ET.Element):
        seen = set()
        for elem in root.iter():
            for attr in ("ID", "Id", "id"):
                if attr in elem.attrib:
                    v = elem.attrib[attr]
                    if v in seen:
                        raise ValueError(f"Duplicate XML ID: {v}")
                    seen.add(v)

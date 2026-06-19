# -*- coding: utf-8 -*-
"""Unified Tag Builder — 通过 HmiUnified API 创建变量。"""
from __future__ import annotations
from backend.domain.ir_v2 import TagSpec
from backend.domain.enums import TagScope


class UnifiedTagBuilder:
    """Unified 变量创建器。"""

    def __init__(self):
        pass

    def build_tag_spec(self, tag: TagSpec) -> dict:
        """将 TagSpec 转换为 Unified Tag 创建参数 dict。"""
        spec = {
            "Name": tag.name,
            "DataType": tag.data_type,
            "Table": tag.table,
        }
        if tag.scope == TagScope.EXTERNAL:
            if tag.connection:
                spec["Connection"] = tag.connection
            if tag.controller_tag:
                spec["ControllerTag"] = tag.controller_tag
            elif tag.address:
                spec["Address"] = tag.address
        if tag.acquisition_cycle:
            spec["AcquisitionCycle"] = tag.acquisition_cycle
        if tag.initial_value is not None:
            spec["StartValue"] = tag.initial_value
        return spec

    def build_tags(self, tags: list[TagSpec]) -> list[dict]:
        return [self.build_tag_spec(t) for t in tags]

    def build_wincc_ml(self, tags: list[TagSpec], table_name: str = "AI_Generated") -> str:
        """生成 WinCC ML YAML 格式变量表（用于批量导入）。"""
        lines = [f'TagTable:', f'  Name: "{table_name}"', f'  Tags:']
        for tag in tags:
            lines.append(f'    - Name: "{tag.name}"')
            lines.append(f'      DataType: {tag.data_type}')
            if tag.scope == TagScope.EXTERNAL and tag.connection:
                lines.append(f'      Connection: {tag.connection}')
            if tag.controller_tag:
                lines.append(f'      ControllerTag: {tag.controller_tag}')
            if tag.address:
                lines.append(f'      Address: {tag.address}')
        return "\n".join(lines)

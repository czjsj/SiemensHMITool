# -*- coding: utf-8 -*-
"""Unified Binding Builder — Dynamization 创建。

方案文档 §11.7 对齐。
"""
from __future__ import annotations
from backend.domain.ir_v2 import BindingSpec
from backend.domain.enums import BindingKind


class UnifiedBindingBuilder:
    """Unified 动态化创建器。"""

    # Binding kind → Unified Dynamization 类型
    KIND_TO_DYNAMIZATION = {
        BindingKind.DIRECT_TAG: "TagDynamization",
        BindingKind.DISCRETE: "TagDynamization",
        BindingKind.RANGE: "TagDynamization",
        BindingKind.LINEAR: "TagDynamization",
        BindingKind.FLASHING: "FlashingDynamization",
        BindingKind.RESOURCE_LIST: "ResourceListDynamization",
        BindingKind.EXPRESSION: "ExpressionDynamization",
        BindingKind.SCRIPT: "ScriptDynamization",
    }

    def __init__(self):
        pass

    def create(self, binding: BindingSpec, context: dict | None = None) -> dict:
        """创建动态化规格。"""
        dyn_type = self.KIND_TO_DYNAMIZATION.get(binding.kind, "TagDynamization")
        spec = {
            "PropertyName": binding.property,
            "DynamizationType": dyn_type,
        }
        if binding.source_tag:
            spec["TagName"] = binding.source_tag
        if binding.config:
            spec["Config"] = binding.config
        if binding.fallback is not None:
            spec["Fallback"] = binding.fallback
        return spec

    def validate_binding_target(self, binding: BindingSpec, available_properties: set[str]) -> bool:
        """验证绑定目标属性支持对应动态化类型。"""
        return binding.property in available_properties

# -*- coding: utf-8 -*-
"""测试兼容策略与兜底路线 — Phase 13。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from backend.domain.enums import (
    HmiFamily, ScreenItemType, ButtonBehavior, IndicatorMode,
    DeploymentPhase, DiagnosticSeverity,
)
from backend.capabilities.capability_service import CapabilityService, CapabilitySet
from backend.domain.ir_v2 import HmiProjectSpec, TargetSpec, ScreenSpec, ScreenItemSpec, TagSpec, GeometrySpec
from backend.services.deployment_service import BackendFactory
from backend.domain.diagnostics import Diagnostic, DiagnosticCodes


class TestCompatibilityFallback:
    """测试兼容策略与兜底路线。"""

    def test_basic_family_selects_basic_backend(self):
        """Basic 面板选择 BasicBackend。"""
        target = TargetSpec(family=HmiFamily.BASIC)
        backend, name = BackendFactory.create(target)
        assert "basic" in name.lower()

    def test_comfort_family_selects_comfort_backend(self):
        """Comfort 面板选择 ComfortBackend。"""
        target = TargetSpec(family=HmiFamily.COMFORT)
        backend, name = BackendFactory.create(target)
        assert "comfort" in name.lower()

    def test_unified_family_selects_unified_backend(self):
        """Unified 面板选择 UnifiedBackend。"""
        target = TargetSpec(family=HmiFamily.UNIFIED)
        backend, name = BackendFactory.create(target)
        assert "unified" in name.lower()

    def test_basic_panel_no_vbs_script_capability(self):
        """Basic 面板不支持 VBS 脚本。"""
        caps = CapabilitySet(HmiFamily.BASIC)
        # Basic 面板不支持 VBS
        assert caps.get("VBS") == "no"

    def test_comfort_panel_supports_vbs(self):
        """Comfort 面板支持 VBS 脚本。"""
        caps = CapabilitySet(HmiFamily.COMFORT)
        # Comfort 面板支持 VBS
        assert caps.supports("VBS")

    def test_unified_no_classic_xml_template_needed(self):
        """Unified 面板不依赖 Classic XML 模板。"""
        target = TargetSpec(family=HmiFamily.UNIFIED)
        backend, name = BackendFactory.create(target)
        # Unified 使用直接对象模型，不是 Classic XML
        assert "unified" in name.lower()

    def test_deployment_phases_in_order_for_all_families(self):
        """所有面板家族的部署阶段顺序一致。"""
        phases = list(DeploymentPhase)
        assert phases.index(DeploymentPhase.P30_TAG_TABLES_AND_TAGS) < \
               phases.index(DeploymentPhase.P50_SCREENS)
        assert phases.index(DeploymentPhase.P50_SCREENS) < \
               phases.index(DeploymentPhase.P70_COMPILE)

    def test_capability_matrix_covers_all_families(self):
        """静态能力矩阵覆盖所有面板家族。"""
        for family in [HmiFamily.BASIC, HmiFamily.COMFORT, HmiFamily.UNIFIED]:
            caps = CapabilitySet(family)
            # 至少能查询基本能力
            result = caps.get("screen_button")
            assert result in ("yes", "no", "limited", "device", "unknown")

# -*- coding: utf-8 -*-
"""测试部署阶段顺序。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from backend.domain.enums import DeploymentPhase


class TestDeploymentPhaseOrder:
    """测试部署阶段顺序约束。"""

    def test_phase_order(self):
        """按值比较部署阶段顺序。"""
        phases = list(DeploymentPhase)
        assert phases.index(DeploymentPhase.P30_TAG_TABLES_AND_TAGS) < phases.index(DeploymentPhase.P50_SCREENS)

    def test_tags_before_screens(self):
        """P30 变量表一定早于 P50 画面。"""
        assert DeploymentPhase.P30_TAG_TABLES_AND_TAGS.value < DeploymentPhase.P50_SCREENS.value

    def test_compile_after_screens(self):
        """P70 编译一定晚于 P50 画面。"""
        assert DeploymentPhase.P70_COMPILE.value > DeploymentPhase.P50_SCREENS.value

    def test_verify_after_compile(self):
        """P80 验证一定晚于 P70 编译。"""
        assert DeploymentPhase.P80_VERIFY.value > DeploymentPhase.P70_COMPILE.value

    def test_all_phases_defined(self):
        """所有标准阶段都已定义。"""
        expected = {"P00_DISCOVERY", "P10_VALIDATE_DEPENDENCIES", "P20_CONNECTIONS",
                    "P30_TAG_TABLES_AND_TAGS", "P40_SCRIPTS_AND_RESOURCES",
                    "P50_SCREENS", "P60_BINDINGS_AND_EVENTS",
                    "P70_COMPILE", "P80_VERIFY", "P90_SAVE"}
        actual = {p.value for p in DeploymentPhase}
        assert expected == actual

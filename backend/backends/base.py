# -*- coding: utf-8 -*-
"""HMI Backend 抽象基类 — 方案文档 §8.2 对齐。"""
from __future__ import annotations
from abc import ABC, abstractmethod
from backend.domain.ir_v2 import HmiProjectSpec, TargetSpec
from backend.domain.deployment_plan import DeploymentPlan
from backend.domain.deployment_result import DeploymentResult, VerificationResult


class HmiBackend(ABC):
    """HMI 部署后端统一接口。"""

    @abstractmethod
    def supports(self, target: TargetSpec) -> bool:
        """判断是否支持目标设备。"""
        ...

    @abstractmethod
    def build_plan(self, spec: HmiProjectSpec, context: dict | None = None) -> DeploymentPlan:
        """构建部署计划。"""
        ...

    @abstractmethod
    def execute(self, plan: DeploymentPlan, context: dict | None = None) -> DeploymentResult:
        """执行部署。"""
        ...

    @abstractmethod
    def verify(self, spec: HmiProjectSpec, context: dict | None = None) -> VerificationResult:
        """验证部署结果。"""
        ...

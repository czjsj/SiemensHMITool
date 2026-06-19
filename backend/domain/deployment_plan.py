# -*- coding: utf-8 -*-
"""
部署计划与步骤模型。

不依赖 Flask、pythonnet 或 Siemens DLL。
方案文档 §8 对齐。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .enums import DeploymentPhase
from .ir_v2 import TargetSpec
from .diagnostics import Diagnostic


class DeploymentStep(BaseModel):
    """单个部署步骤。"""

    id: str = Field(..., description="步骤唯一标识")
    phase: str = Field(..., description="部署阶段代号")
    operation: str = Field(
        ..., description="操作名称，如 create, update, skip, verify"
    )
    target_type: str = Field(..., description="目标对象类型")
    target_name: str = Field(default="", description="目标对象名称")
    depends_on: list[str] = Field(
        default_factory=list, description="依赖的步骤 ID 列表"
    )
    payload: dict[str, Any] = Field(
        default_factory=dict, description="操作所需数据"
    )
    rollback: dict[str, Any] | None = Field(
        default=None, description="回滚信息"
    )


class DeploymentPlan(BaseModel):
    """部署计划 — 包含所有步骤和诊断。"""

    plan_id: str = Field(..., description="计划唯一标识")
    target: TargetSpec = Field(
        default_factory=TargetSpec, description="目标设备"
    )
    capabilities: dict[str, Any] = Field(
        default_factory=dict, description="目标设备能力摘要"
    )
    steps: list[DeploymentStep] = Field(
        default_factory=list, description="部署步骤列表"
    )
    diagnostics: list[Diagnostic] = Field(
        default_factory=list, description="关联诊断信息"
    )
    dry_run: bool = Field(
        default=True, description="是否为试运行模式"
    )

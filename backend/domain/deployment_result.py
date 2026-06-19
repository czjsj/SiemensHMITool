# -*- coding: utf-8 -*-
"""
部署结果与验证结果模型。

不依赖 Flask、pythonnet 或 Siemens DLL。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .diagnostics import Diagnostic


class ObjectCountSummary(BaseModel):
    """对象计数摘要。"""

    expected: int = Field(default=0, description="预期数量")
    found: int = Field(default=0, description="实际发现数量")
    failed: list[str] = Field(
        default_factory=list, description="失败对象名称列表"
    )


class CompileResult(BaseModel):
    """编译结果。"""

    errors: int = Field(default=0, description="编译错误数")
    warnings: int = Field(default=0, description="编译警告数")
    messages: list[str] = Field(
        default_factory=list, description="编译消息列表"
    )


class VerificationResult(BaseModel):
    """验证结果 — 部署后查询目标项目所得。"""

    success: bool = Field(default=False, description="验证是否全部通过")
    tags: ObjectCountSummary = Field(
        default_factory=ObjectCountSummary, description="变量验证"
    )
    screens: ObjectCountSummary = Field(
        default_factory=ObjectCountSummary, description="画面验证"
    )
    events: ObjectCountSummary = Field(
        default_factory=ObjectCountSummary, description="事件验证"
    )
    bindings: ObjectCountSummary = Field(
        default_factory=ObjectCountSummary, description="绑定验证"
    )
    scripts: ObjectCountSummary = Field(
        default_factory=ObjectCountSummary, description="脚本验证"
    )
    compile: CompileResult = Field(
        default_factory=CompileResult, description="编译结果"
    )


class DeploymentResult(BaseModel):
    """部署结果 — API 返回给前端的结构化摘要。"""

    success: bool = Field(default=False, description="部署是否全部成功")
    plan_id: str = Field(default="", description="对应的部署计划 ID")
    backend: str = Field(default="", description="使用的后端名称")

    # 计数摘要
    connections_created: int = Field(default=0)
    tags_created: int = Field(default=0)
    tags_skipped: int = Field(default=0)
    scripts_created: int = Field(default=0)
    screens_created: int = Field(default=0)
    bindings_created: int = Field(default=0)
    events_created: int = Field(default=0)

    # 诊断
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    # 编译与验证
    compile_errors: int = Field(default=0)
    compile_warnings: int = Field(default=0)
    verification: VerificationResult | None = Field(
        default=None, description="验证阶段结果"
    )

    # 额外细节
    details: dict[str, Any] = Field(default_factory=dict)

# -*- coding: utf-8 -*-
"""
部署结果与验证结果模型。

不依赖 Flask、pythonnet 或 Siemens DLL。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .diagnostics import Diagnostic
from .enums import DeploymentStatus


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
    status: DeploymentStatus = Field(
        default=DeploymentStatus.NOT_CONNECTED, description="部署状态机当前状态"
    )
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


# ---------------------------------------------------------------------------
# ActualProjectSnapshot — 从真实 TIA 项目查询得到的对象快照
# ---------------------------------------------------------------------------


class TagSnapshot(BaseModel):
    """从 TIA 项目查询到的变量快照。"""
    name: str = ""
    data_type: str = ""
    connection: str = ""
    scope: str = "internal"
    controller_tag: str = ""


class ScreenItemSnapshot(BaseModel):
    """从 TIA 项目查询到的控件快照。"""
    name: str = ""
    item_type: str = ""
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    properties: dict[str, Any] = Field(default_factory=dict)
    dynamizations: list[dict[str, Any]] = Field(default_factory=list)
    event_handlers: list[dict[str, Any]] = Field(default_factory=list)


class ScreenSnapshot(BaseModel):
    """从 TIA 项目查询到的画面快照。"""
    name: str = ""
    width: int = 0
    height: int = 0
    items: list[ScreenItemSnapshot] = Field(default_factory=list)


class ScriptSnapshot(BaseModel):
    """从 TIA 项目查询到的脚本快照。"""
    name: str = ""
    language: str = ""
    body_length: int = 0


class ActualProjectSnapshot(BaseModel):
    """从真实 TIA 项目查询到的完整对象快照。

    VerificationService 只能接受此类型数据作为 found 数据。
    禁止用 expected spec 构造 found 数据。
    """
    tags: list[dict[str, Any]] = Field(default_factory=list)
    screens: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    bindings: list[dict[str, Any]] = Field(default_factory=list)
    scripts: list[dict[str, Any]] = Field(default_factory=list)
    compile: dict[str, Any] = Field(default_factory=dict)
    raw_tags: list[TagSnapshot] = Field(default_factory=list)
    raw_screens: list[ScreenSnapshot] = Field(default_factory=list)
    raw_scripts: list[ScriptSnapshot] = Field(default_factory=list)

    def to_query_dict(self) -> dict[str, Any]:
        return {
            "tags": self.tags,
            "screens": self.screens,
            "events": self.events,
            "bindings": self.bindings,
            "scripts": self.scripts,
            "compile": self.compile,
        }

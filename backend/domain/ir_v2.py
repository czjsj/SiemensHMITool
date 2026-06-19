# -*- coding: utf-8 -*-
"""
HMI IR V2 数据模型 — 完整工程语义 IR。

使用 Pydantic v2 定义，不依赖 Flask、pythonnet 或 Siemens DLL。

方案文档 §6 完整对齐。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .enums import (
    BindingKind,
    ButtonBehavior,
    ConflictPolicy,
    ConnectionKind,
    HmiFamily,
    IndicatorMode,
    MissingDependencyPolicy,
    ScriptLanguage,
    SemanticEvent,
    SemanticActionType,
    ScreenItemType,
    TagDirection,
    TagScope,
    UnsupportedFeaturePolicy,
)
from .diagnostics import Diagnostic


# ---------------------------------------------------------------------------
# 部署策略
# ---------------------------------------------------------------------------


class DeploymentPolicies(BaseModel):
    """部署策略配置。"""

    conflict_policy: ConflictPolicy = Field(
        default=ConflictPolicy.RENAME, description="对象名称冲突时的处理策略"
    )
    unsupported_feature: UnsupportedFeaturePolicy = Field(
        default=UnsupportedFeaturePolicy.ERROR,
        description="遇到目标设备不支持功能时的策略",
    )
    missing_dependency: MissingDependencyPolicy = Field(
        default=MissingDependencyPolicy.ERROR,
        description="遇到缺失依赖时的策略",
    )
    compile_after_deploy: bool = Field(
        default=True, description="部署完成后是否触发编译"
    )
    save_after_deploy: bool = Field(
        default=False, description="部署完成后是否保存项目"
    )


# ---------------------------------------------------------------------------
# 项目元数据
# ---------------------------------------------------------------------------


class ProjectMetadata(BaseModel):
    """项目元信息。"""

    project_name: str = Field(default="", description="项目名称")
    author: str = Field(default="", description="作者")
    description: str = Field(default="", description="项目描述")
    created_at: str = Field(default="", description="创建时间（ISO 8601）")
    version: str = Field(default="1.0", description="项目版本号")
    extra: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")


# ---------------------------------------------------------------------------
# 目标设备
# ---------------------------------------------------------------------------


class TargetSpec(BaseModel):
    """目标 HMI 设备规格。"""

    family: HmiFamily = Field(
        default=HmiFamily.AUTO, description="目标面板家族"
    )
    tia_version: str | None = Field(
        default=None, description="TIA Portal 版本，如 V18"
    )
    device_name: str | None = Field(
        default=None, description="目标设备在项目中的名称，如 HMI_1"
    )
    device_type: str | None = Field(
        default=None, description="设备型号，如 TP1200 Comfort"
    )
    resolution: str | None = Field(
        default=None, description="目标分辨率，如 1280x800"
    )
    language: str = Field(
        default="zh-CN", description="默认语言"
    )


# ---------------------------------------------------------------------------
# 连接模型
# ---------------------------------------------------------------------------


class ConnectionSpec(BaseModel):
    """HMI 连接规格。"""

    name: str = Field(..., description="连接名称，在 HMI 内唯一")
    kind: ConnectionKind = Field(
        default=ConnectionKind.INTEGRATED, description="连接类型"
    )
    driver: str | None = Field(default=None, description="驱动名称")
    partner_device: str | None = Field(
        default=None, description="伙伴设备（PLC 名称）"
    )
    address: str | None = Field(default=None, description="连接地址")
    create_if_missing: bool = Field(
        default=False, description="缺失时是否自动创建"
    )


# ---------------------------------------------------------------------------
# 变量模型
# ---------------------------------------------------------------------------


class TagSpec(BaseModel):
    """HMI 变量规格。"""

    name: str = Field(..., description="变量名称")
    table: str = Field(default="AI_Generated", description="所属变量表")
    scope: TagScope = Field(default=TagScope.EXTERNAL, description="作用域")
    data_type: str = Field(default="Bool", description="数据类型")
    connection: str | None = Field(default=None, description="关联连接名称")
    controller_tag: str | None = Field(
        default=None, description="PLC 控制器标签"
    )
    address: str | None = Field(default=None, description="PLC 地址")
    acquisition_cycle: str | None = Field(
        default=None, description="采集周期"
    )
    initial_value: Any | None = Field(default=None, description="初始值")
    comment: dict[str, str] = Field(
        default_factory=dict, description="多语言注释"
    )
    read_only: bool = Field(default=False, description="是否只读")
    # V4.0 新增
    direction: TagDirection = Field(
        default=TagDirection.READ_WRITE, description="变量读写方向"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="扩展元数据（如 pending_mapping）"
    )

    @model_validator(mode="after")
    def _check_external_tag_constraints(self):
        if self.scope == TagScope.EXTERNAL:
            if not self.connection and not self.address:
                # 外部变量必须有连接或地址；这在 plan 阶段校验，
                # 模型本身宽松接受以兼容部分生成场景。
                pass
        return self


# ---------------------------------------------------------------------------
# 几何模型
# ---------------------------------------------------------------------------


class GeometrySpec(BaseModel):
    """控件几何信息。"""

    x: int = Field(default=0, ge=0, description="左上角 X 坐标")
    y: int = Field(default=0, ge=0, description="左上角 Y 坐标")
    width: int = Field(default=100, ge=1, description="宽度")
    height: int = Field(default=40, ge=1, description="高度")
    radius: int | None = Field(default=None, description="半径（圆形控件专用）")


# ---------------------------------------------------------------------------
# 动态绑定模型
# ---------------------------------------------------------------------------


class BindingSpec(BaseModel):
    """动态属性绑定。"""

    property: str = Field(..., description="绑定目标属性名")
    kind: BindingKind = Field(
        default=BindingKind.DIRECT_TAG, description="绑定类型"
    )
    source_tag: str | None = Field(default=None, description="源变量名")
    config: dict[str, Any] = Field(
        default_factory=dict, description="绑定配置（阈值、状态映射等）"
    )
    fallback: Any | None = Field(default=None, description="绑定失败时的回退值")
    # V4.0 新增: 变量连接属性
    tag: str | None = Field(
        default=None, description="绑定的变量名（语义级，如 BTN_Motor_Start）"
    )
    direction: TagDirection = Field(
        default=TagDirection.READ_WRITE, description="变量方向"
    )
    connection: str | None = Field(
        default=None, description="关联 HMI 连接名"
    )
    plc_address: str | None = Field(
        default=None, description="PLC 地址（如 DB10.DBX0.0）"
    )


# ---------------------------------------------------------------------------
# 事件与动作模型
# ---------------------------------------------------------------------------


class ActionSpec(BaseModel):
    """语义动作。不允许直接写死 VBS 或 JavaScript。"""

    type: SemanticActionType = Field(..., description="动作类型")
    tag: str | None = Field(default=None, description="目标变量名")
    value: Any | None = Field(default=None, description="目标值")
    screen: str | None = Field(default=None, description="目标画面名")
    script: str | None = Field(default=None, description="目标脚本名")
    arguments: list[Any] = Field(default_factory=list, description="脚本参数")
    expression: str | None = Field(default=None, description="表达式文本")


class EventSpec(BaseModel):
    """事件规格。"""

    event: SemanticEvent = Field(..., description="事件类型")
    actions: list[ActionSpec] = Field(
        default_factory=list, description="关联动作列表"
    )


# ---------------------------------------------------------------------------
# 脚本模型
# ---------------------------------------------------------------------------


class ScriptSpec(BaseModel):
    """脚本规格。"""

    name: str = Field(..., description="脚本名称")
    language: ScriptLanguage = Field(
        default=ScriptLanguage.SEMANTIC, description="脚本语言"
    )
    body: str = Field(..., description="脚本体")
    parameters: list[str] = Field(
        default_factory=list, description="参数名列表"
    )
    target_families: list[HmiFamily] = Field(
        default_factory=list, description="适用的目标面板家族"
    )


# ---------------------------------------------------------------------------
# 资源模型
# ---------------------------------------------------------------------------


class ResourceSpec(BaseModel):
    """资源规格（文本列表、图形列表等）。"""

    name: str = Field(..., description="资源名称")
    kind: Literal["text_list", "graphic_list"] = Field(
        default="text_list", description="资源类型"
    )
    entries: list[dict[str, Any]] = Field(
        default_factory=list, description="资源条目"
    )


# ---------------------------------------------------------------------------
# 画面对象模型
# ---------------------------------------------------------------------------


class ScreenItemSpec(BaseModel):
    """画面控件规格。"""

    id: str = Field(..., description="控件唯一标识")
    name: str = Field(..., description="控件显示名称")
    type: ScreenItemType = Field(..., description="控件类型")
    geometry: GeometrySpec = Field(
        default_factory=GeometrySpec, description="几何信息"
    )
    properties: dict[str, Any] = Field(
        default_factory=dict, description="静态属性"
    )
    text: dict[str, str] = Field(
        default_factory=dict, description="多语言文本"
    )
    tag_binding: str | None = Field(
        default=None, description="主变量绑定（兼容旧格式 process_tag）"
    )
    bindings: list[BindingSpec] = Field(
        default_factory=list, description="动态绑定列表"
    )
    events: list[EventSpec] = Field(
        default_factory=list, description="事件列表"
    )
    # V4.0 新增: 模板绑定字段
    template_ref: str | None = Field(
        default=None, description="模板原型引用（如 BTN_MOMENTARY_TEMPLATE）"
    )
    prototype_role: str | None = Field(
        default=None, description="原型角色（如 momentary_button/alarm_indicator）"
    )
    behavior: ButtonBehavior | None = Field(
        default=None, description="按钮行为模式"
    )
    indicator_mode: IndicatorMode | None = Field(
        default=None, description="指示灯模式"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="扩展元数据（如 pending_mapping）"
    )


# ---------------------------------------------------------------------------
# 画面模型
# ---------------------------------------------------------------------------


class ScreenSpec(BaseModel):
    """画面规格。"""

    name: str = Field(..., description="画面名称")
    folder: str | None = Field(default=None, description="所属文件夹")
    width: int = Field(default=1280, description="画面宽度")
    height: int = Field(default=800, description="画面高度")
    background_color: str = Field(
        default="#D9DEE5", description="背景色"
    )
    template: str | None = Field(
        default=None, description="模板画面引用"
    )
    items: list[ScreenItemSpec] = Field(
        default_factory=list, description="控件列表"
    )
    events: list[EventSpec] = Field(
        default_factory=list, description="画面级事件"
    )


# ---------------------------------------------------------------------------
# 顶层项目模型
# ---------------------------------------------------------------------------


class HmiProjectSpec(BaseModel):
    """HMI 工程完整语义 IR — 顶层模型。"""

    schema_version: Literal["2.0"] = "2.0"
    metadata: ProjectMetadata = Field(
        default_factory=ProjectMetadata, description="项目元数据"
    )
    target: TargetSpec = Field(
        default_factory=TargetSpec, description="目标设备"
    )
    connections: list[ConnectionSpec] = Field(
        default_factory=list, description="连接列表"
    )
    tags: list[TagSpec] = Field(
        default_factory=list, description="变量列表"
    )
    scripts: list[ScriptSpec] = Field(
        default_factory=list, description="脚本列表"
    )
    resources: list[ResourceSpec] = Field(
        default_factory=list, description="资源列表（文本列表等）"
    )
    screens: list[ScreenSpec] = Field(
        default_factory=list, description="画面列表"
    )
    policies: DeploymentPolicies = Field(
        default_factory=DeploymentPolicies, description="部署策略"
    )

    # 兼容旧格式的诊断列表（plan/validate 阶段汇聚于此）
    diagnostics: list[Diagnostic] = Field(
        default_factory=list, description="关联诊断信息"
    )

# Siemens HMI Assistant V3.0 完整项目完善方案

**用途**：交付给 Claude Code 作为工程改造与实现规范  
**项目基础**：Siemens HMI Assistant V2.3  
**目标平台**：TIA Portal Openness，Basic Panel、Comfort Panel、WinCC Unified  
**文档版本**：1.0  
**日期**：2026-06-19  

---

## 目录

| 章节 | 内容 |
|---|---|
| 0 | Claude Code 必读说明 |
| 1 | 项目背景与当前问题 |
| 2 | 项目目标与非目标 |
| 3 | 关键架构决策 |
| 4 | 目标总体架构 |
| 5 | 推荐目录结构 |
| 6 | HMI IR V2 数据模型 |
| 7 | 设备能力矩阵 |
| 8 | 部署计划模型 |
| 9 | Basic Panel 完整实现方案 |
| 10 | Comfort Panel 完整实现方案 |
| 11 | Unified 完整实现方案 |
| 12 | 黄金参考工程与 XML Fragment Catalog |
| 13 | Classic XML 核心组件 |
| 14 | 对现有模块的具体改造 |
| 15 | API 设计 |
| 16 | 配置文件升级 |
| 17 | 错误和诊断模型 |
| 18 | 事务、回滚与安全 |
| 19 | 测试策略 |
| 20 | 验证闭环 |
| 21 | 分阶段实施计划 |
| 22 | Claude Code 任务拆分清单 |
| 23 | 编码规则 |
| 24 | Definition of Done |
| 25 | 第一批最小可交付场景 |
| 26 | 实施时的风险清单 |
| 27 | 官方能力依据与实现边界 |
| 28 | 交付物清单 |
| 29 | Claude Code 开始执行时的建议命令 |
| 30 | 禁止 Claude Code 采用的捷径 |
| 31 | 推荐的首个 Claude Code 指令 |
| 32 | 文档结论 |

---

## 0. Claude Code 必读说明

本文件是实现规范，不是讨论稿。执行时必须遵守以下原则：

1. 不要把 Basic、Comfort、Unified 当成同一种导入格式。
2. 不要继续让 `VariableEngine` 直接生成 VBS；它必须生成与设备无关的语义动作。
3. Basic/Comfort 使用“目标 TIA 版本真实导出 XML 模板 + 受控改写 + Openness Import”。
4. Unified 优先使用 `Siemens.Engineering.HmiUnified` 强类型对象模型直接创建变量、画面、控件、动态化和事件。
5. 变量、连接、脚本和资源必须先于画面部署。
6. 所有经典 HMI XML 节点、枚举和值必须来自目标版本导出的黄金参考工程，不允许凭经验伪造。
7. 导入成功不等于功能成功；最终必须编译并验证变量引用、事件、动态化和脚本。
8. 每一个阶段都要保持旧接口可回滚，禁止一次性推翻现有项目。
9. 对无法确认的 Openness 类型名、属性名或枚举，必须通过当前加载 DLL 的反射发现，禁止硬编码猜测。
10. 任何“跳过不支持功能”的行为都必须返回结构化 warning/error，不能静默忽略。

---

# 1. 项目背景与当前问题

## 1.1 当前能力

现有 V2.3 项目已经具备：

- Flask Web 服务和 SSE 流式生成；
- LLM 生成 HMI 画面 IR；
- IR 校验、归一化和自动排版；
- VariableEngine 自动生成变量名称及部分 VBS；
- SimaticML/模板 XML 生成；
- TIA Portal Openness 连接；
- Basic/Comfort 画面 XML 导入；
- Unified 的部分直接创建逻辑；
- 视觉审查与预览；
- `/api/openness/sync-tags` 变量同步入口。

## 1.2 当前症状

当前项目“画面可以导入，但变量、事件和属性没有完整进入 TIA 工程”，根因不是单一 bug，而是架构缺口：

1. 当前 IR 主要描述画面对象和几何信息，没有形成完整的工程语义模型。
2. `VariableEngine` 直接输出 VBS 文本，导致 Basic、Comfort、Unified 三种目标无法正确适配。
3. 画面导入和变量同步是分离的，且顺序偏向“先画面、后变量”。
4. 目前通用 `<Connection><ProcessTag>` 形式更接近项目内部格式，不一定对应 TIA 真正可解析的 `LinkList/TargetID/OpenLink` 引用结构。
5. 事件没有转成 Classic HMI 的 FunctionList/VBS 调用节点，或 Unified 的 EventHandler/JavaScript。
6. 动态属性没有转成 Classic XML 中真实动态化节点，或 Unified 的 Dynamization 对象。
7. 缺少目标面板能力矩阵和版本适配层。
8. 缺少“导入后编译 + 反向读取验证”的闭环。
9. `openness_manager.py` 职责过重，连接、模板、导入、变量、Unified 创建、错误处理全部混合。
10. 缺少黄金参考工程和跨版本 fixture，导致 XML 生成依赖猜测。

## 1.3 核心判断

项目必须从“AI 画面 XML 生成器”升级为“设备感知的 HMI 工程部署器”。

完整部署对象至少包括：

- HMI 连接；
- HMI 变量表；
- HMI 变量；
- 文本列表和图形列表；
- VBS/JavaScript；
- 画面；
- 画面控件；
- 静态属性；
- 动态属性；
- 事件和动作；
- 依赖检查；
- 编译和结果验证。

---

# 2. 项目目标与非目标

## 2.1 必须达到的目标

### G1：三种目标设备独立适配

- Basic Panel：经典 XML + FunctionList，不依赖 VBS。
- Comfort Panel：经典 XML + FunctionList，复杂动作支持 VBS。
- Unified：直接 Openness 对象模型 + JavaScript + Dynamization。

### G2：完整工程语义

同一个 IR 必须能描述：

- 变量定义；
- 变量来源；
- 静态属性；
- 动态绑定；
- 事件；
- 事件动作；
- 脚本；
- 资源依赖；
- 目标设备能力约束。

### G3：正确部署顺序

```text
发现目标设备
→ 读取版本和能力
→ 验证 PLC/连接依赖
→ 创建或导入连接
→ 创建或导入变量和变量表
→ 创建或导入脚本/资源
→ 创建或导入画面
→ 创建动态化和事件
→ 编译
→ 验证
```

### G4：结果可解释

每次部署返回：

- 请求数量；
- 成功数量；
- 失败数量；
- 跳过数量；
- 具体失败对象；
- TIA 编译错误；
- 不支持能力；
- 可回滚信息。

### G5：兼容当前项目

旧的：

- `/api/generate`；
- `/api/build`；
- `/api/openness/import`；
- 现有 IR 字段；

在迁移期内继续可用，并通过适配器转换到新模型。

## 2.2 暂不作为第一阶段目标

以下功能不应阻塞 V3.0 核心交付：

- 报警系统完整自动生成；
- 配方、趋势、用户管理全功能；
- Faceplate 类型自动创建；
- Unified Custom Web Control 自动生成；
- 任意 TIA 版本百分之百兼容；
- RT Professional；
- 自动创建复杂 PLC 程序；
- 未经参考工程验证的控件类型。

这些功能应使用扩展点预留，但不在第一阶段承诺。

---

# 3. 关键架构决策

## ADR-001：使用统一语义 IR，不使用统一导出格式

统一的是业务含义，不统一最终实现。

```text
HMI IR V2
   ├── BasicCompiler      → Classic XML + FunctionList
   ├── ComfortCompiler    → Classic XML + FunctionList/VBS
   └── UnifiedCompiler    → HmiUnified object model + JavaScript
```

## ADR-002：事件使用语义动作

禁止在核心 IR 中直接写死 VBS 或 JavaScript。

正确：

```json
{
  "event": "press",
  "actions": [
    {"type": "set_bit", "tag": "Motor_Start"}
  ]
}
```

错误：

```json
{
  "event": "press",
  "vbs": "SmartTags(\"Motor_Start\") = 1"
}
```

脚本仅用于无法用标准动作表达的复杂逻辑。

## ADR-003：经典 HMI 使用黄金模板，不从零猜 XML

Basic/Comfort 的 XML 必须从目标 TIA 版本和目标设备人工创建的参考画面中导出。

生成器只能：

- 克隆节点；
- 替换已登记的字段；
- 分配 ID；
- 修复引用；
- 校验依赖；
- 执行受控合并。

## ADR-004：Unified 使用强类型对象模型

Unified 主要使用：

- `HmiSoftware.Screens.Create()`；
- `ScreenItems.Create<T>()`；
- `Tags.Create()`；
- `Dynamizations.Create()`；
- `EventHandlers.Create()`；
- JavaScript；
- WinCC ML 变量表批量导入作为可选优化。

## ADR-005：部署是事务化计划

先构建 `DeploymentPlan`，再执行。所有变更可预览、可追踪、可校验。

## ADR-006：版本能力必须运行时发现

- 静态能力矩阵用于快速判断；
- 当前 DLL 反射用于最终确认；
- 目标设备导出 fixture 用于最终结构确认。

## ADR-007：导入后必须编译

部署完成标准不是 API 无异常，而是：

- 对象存在；
- 引用解析；
- 事件存在；
- 动态化存在；
- 脚本通过语法检查；
- HMI 编译无 error。

---

# 4. 目标总体架构

```text
┌──────────────────────────────────────────────────────────────┐
│ Web/API Layer                                                │
│ generate / validate / plan / deploy / verify / diagnostics   │
└───────────────────────────────┬──────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────┐
│ HMI IR V2 + Legacy IR Adapter                                │
│ ScreenSpec / TagSpec / BindingSpec / EventSpec / ActionSpec  │
└───────────────────────────────┬──────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────┐
│ Deployment Planner                                           │
│ dependency graph / capabilities / ordering / conflict policy │
└─────────────┬─────────────────┬─────────────────┬────────────┘
              │                 │                 │
┌─────────────▼──────┐ ┌────────▼─────────┐ ┌────▼─────────────┐
│ Basic Backend      │ │ Comfort Backend  │ │ Unified Backend  │
│ Classic XML        │ │ Classic XML/VBS  │ │ HmiUnified API   │
│ FunctionList       │ │ FunctionList     │ │ JavaScript       │
└─────────────┬──────┘ └────────┬─────────┘ └────┬─────────────┘
              │                 │                 │
┌─────────────▼─────────────────▼─────────────────▼────────────┐
│ Openness Runtime                                             │
│ session / device discovery / import / compile / diagnostics  │
└──────────────────────────────────────────────────────────────┘
```

---

# 5. 推荐目录结构

```text
backend/
├── domain/
│   ├── __init__.py
│   ├── ir_v2.py
│   ├── enums.py
│   ├── validation.py
│   ├── legacy_adapter.py
│   ├── deployment_plan.py
│   ├── deployment_result.py
│   └── diagnostics.py
│
├── capabilities/
│   ├── __init__.py
│   ├── static_matrix.py
│   ├── runtime_discovery.py
│   ├── version_policy.py
│   └── capability_service.py
│
├── planners/
│   ├── __init__.py
│   ├── deployment_planner.py
│   ├── dependency_graph.py
│   ├── conflict_resolver.py
│   └── name_allocator.py
│
├── backends/
│   ├── __init__.py
│   ├── base.py
│   │
│   ├── classic/
│   │   ├── __init__.py
│   │   ├── common.py
│   │   ├── basic_backend.py
│   │   ├── comfort_backend.py
│   │   ├── tag_xml_builder.py
│   │   ├── screen_xml_builder.py
│   │   ├── function_list_builder.py
│   │   ├── dynamic_xml_builder.py
│   │   ├── vbs_builder.py
│   │   ├── xml_fragment_catalog.py
│   │   ├── xml_id_registry.py
│   │   ├── link_resolver.py
│   │   └── classic_validator.py
│   │
│   └── unified/
│       ├── __init__.py
│       ├── unified_backend.py
│       ├── tag_builder.py
│       ├── screen_builder.py
│       ├── property_builder.py
│       ├── binding_builder.py
│       ├── event_builder.py
│       ├── js_builder.py
│       ├── reflection_adapter.py
│       ├── version_adapter.py
│       └── unified_validator.py
│
├── openness/
│   ├── __init__.py
│   ├── session_manager.py
│   ├── assembly_loader.py
│   ├── device_discovery.py
│   ├── project_lock.py
│   ├── compiler.py
│   ├── object_query.py
│   ├── transaction_log.py
│   └── exception_mapper.py
│
├── references/
│   ├── manifest.py
│   ├── catalog_service.py
│   ├── fingerprint.py
│   └── normalizer.py
│
├── services/
│   ├── generation_service.py
│   ├── planning_service.py
│   ├── deployment_service.py
│   ├── verification_service.py
│   └── export_reference_service.py
│
├── hmi_ir.py                     # 迁移期兼容入口
├── variable_engine.py            # 改为语义变量/动作推断
├── simaticml_generator.py        # 标记 legacy，不再承担 Unified
├── template_xml_generator.py     # 逐步迁移到 classic/
├── openness_manager.py           # 迁移期 façade
└── import_engine.py              # 迁移到 deployment_service
```

新增目录：

```text
reference_catalog/
├── V16/
│   ├── Basic/
│   └── Comfort/
├── V18/
│   ├── Basic/
│   ├── Comfort/
│   └── Unified/
├── V19/
└── V20/
```

测试目录：

```text
tests/
├── unit/
├── integration/
├── golden/
├── fixtures/
├── contract/
└── tia_manual/
```

---

# 6. HMI IR V2 数据模型

建议使用 Pydantic v2。旧 IR 通过 `LegacyIrAdapter` 转换。

## 6.1 顶层模型

```python
from pydantic import BaseModel, Field
from typing import Literal, Any

class HmiProjectSpec(BaseModel):
    schema_version: Literal["2.0"] = "2.0"
    metadata: "ProjectMetadata"
    target: "TargetSpec"
    connections: list["ConnectionSpec"] = []
    tags: list["TagSpec"] = []
    scripts: list["ScriptSpec"] = []
    resources: list["ResourceSpec"] = []
    screens: list["ScreenSpec"] = []
    policies: "DeploymentPolicies" = Field(default_factory=lambda: DeploymentPolicies())
```

## 6.2 目标设备

```python
class TargetSpec(BaseModel):
    family: Literal["basic", "comfort", "unified", "auto"]
    tia_version: str | None = None
    device_name: str | None = None
    device_type: str | None = None
    resolution: str | None = None
    language: str = "zh-CN"
```

## 6.3 连接模型

```python
class ConnectionSpec(BaseModel):
    name: str
    kind: Literal["integrated", "non_integrated", "opcua", "internal"]
    driver: str | None = None
    partner_device: str | None = None
    address: str | None = None
    create_if_missing: bool = False
```

规则：

- 集成连接默认只验证，不自动猜测创建。
- 非集成连接允许使用参考 XML 导入或 Unified API 创建。
- 连接名称必须在目标 HMI 内唯一。

## 6.4 变量模型

```python
class TagSpec(BaseModel):
    name: str
    table: str = "AI_Generated"
    scope: Literal["internal", "external"]
    data_type: str
    connection: str | None = None
    controller_tag: str | None = None
    address: str | None = None
    acquisition_cycle: str | None = None
    initial_value: Any | None = None
    comment: dict[str, str] = {}
    read_only: bool = False
```

外部变量约束：

```text
scope=external 时：
connection 必须存在；
controller_tag 或 address 至少一个存在；
集成连接优先使用 controller_tag；
不允许同名外部变量分散在多个变量表。
```

## 6.5 画面模型

```python
class ScreenSpec(BaseModel):
    name: str
    folder: str | None = None
    width: int
    height: int
    background_color: str = "#D9DEE5"
    template: str | None = None
    items: list["ScreenItemSpec"] = []
    events: list["EventSpec"] = []
```

## 6.6 画面对象模型

```python
class ScreenItemSpec(BaseModel):
    id: str
    name: str
    type: Literal[
        "text", "button", "io_field", "symbolic_io_field",
        "indicator", "rectangle", "ellipse", "switch",
        "slider", "graphic_view", "screen_window"
    ]
    geometry: "GeometrySpec"
    properties: dict[str, Any] = {}
    text: dict[str, str] = {}
    tag_binding: str | None = None
    bindings: list["BindingSpec"] = []
    events: list["EventSpec"] = []
```

## 6.7 动态绑定

```python
class BindingSpec(BaseModel):
    property: str
    kind: Literal[
        "direct_tag", "discrete", "range", "linear",
        "flashing", "resource_list", "expression", "script"
    ]
    source_tag: str | None = None
    config: dict[str, Any] = {}
    fallback: Any | None = None
```

示例：

```json
{
  "property": "background_color",
  "kind": "discrete",
  "source_tag": "Motor_State",
  "config": {
    "states": [
      {"value": 0, "output": "#808080"},
      {"value": 1, "output": "#00C853"},
      {"value": 2, "output": "#D50000"}
    ]
  }
}
```

## 6.8 事件和动作

```python
class EventSpec(BaseModel):
    event: Literal[
        "click", "press", "release", "change",
        "loaded", "unloaded", "activate", "deactivate"
    ]
    actions: list["ActionSpec"]

class ActionSpec(BaseModel):
    type: Literal[
        "set_bit", "reset_bit", "toggle_bit", "set_value",
        "increment", "decrement", "activate_screen",
        "open_popup", "close_popup", "acknowledge_alarm",
        "call_script", "write_expression"
    ]
    tag: str | None = None
    value: Any | None = None
    screen: str | None = None
    script: str | None = None
    arguments: list[Any] = []
    expression: str | None = None
```

## 6.9 脚本模型

```python
class ScriptSpec(BaseModel):
    name: str
    language: Literal["semantic", "vbs", "javascript"] = "semantic"
    body: str
    parameters: list[str] = []
    target_families: list[str] = []
```

默认不允许 LLM 直接为所有设备生成任意脚本。脚本生成应经过：

- 语义动作优先；
- 目标语言模板；
- 变量白名单；
- 语法检查；
- 危险 API 检查。

---

# 7. 设备能力矩阵

能力矩阵由两部分组成：

1. 静态配置：项目已验证能力；
2. 运行时反射：当前 DLL 暴露能力。

示例矩阵：

| 能力 | Basic | Comfort | Unified |
|---|---:|---:|---:|
| 画面导入/创建 | 是 | 是 | 是 |
| HMI 变量表导入/创建 | 是 | 是 | 是 |
| 外部变量 | 是 | 是 | 是 |
| 系统 FunctionList | 是 | 是 | 不适用 |
| VBS | 禁止 | 是 | 否 |
| JavaScript | 否 | 否 | 是 |
| 标签动态化 | 受限 | 是 | 是 |
| 离散颜色动态 | 是，模板验证后 | 是 | 是 |
| 闪烁动态 | 设备相关 | 是 | 是 |
| 动态可操作性 | 常有限制 | 是 | 是 |
| Popup/Slide-in | 通常不支持或受限 | 设备相关 | 是 |
| Faceplate | 受限 | 是 | 是，模型不同 |
| 直接强类型创建 ScreenItem | 否 | 否 | 是 |

注意：矩阵不能代替目标设备和目标版本实际验证。

接口：

```python
class CapabilityService:
    def resolve(self, target: TargetSpec, runtime: "RuntimeMetadata") -> "CapabilitySet": ...
    def validate_project(self, spec: HmiProjectSpec) -> list["Diagnostic"]: ...
```

不支持策略：

```yaml
policies:
  unsupported_feature: error       # error | warn_and_skip | emulate
  missing_tag: error
  missing_connection: error
  name_conflict: rename            # override | rename | error
```

默认值必须偏安全：`error`。

---

# 8. 部署计划模型

## 8.1 DeploymentPlan

```python
class DeploymentStep(BaseModel):
    id: str
    phase: str
    operation: str
    target_type: str
    target_name: str
    depends_on: list[str] = []
    payload: dict = {}
    rollback: dict | None = None

class DeploymentPlan(BaseModel):
    plan_id: str
    target: TargetSpec
    capabilities: dict
    steps: list[DeploymentStep]
    diagnostics: list["Diagnostic"]
    dry_run: bool = False
```

阶段固定为：

```text
P00_DISCOVERY
P10_VALIDATE_DEPENDENCIES
P20_CONNECTIONS
P30_TAG_TABLES_AND_TAGS
P40_SCRIPTS_AND_RESOURCES
P50_SCREENS
P60_BINDINGS_AND_EVENTS
P70_COMPILE
P80_VERIFY
P90_SAVE
```

## 8.2 后端统一接口

```python
from abc import ABC, abstractmethod

class HmiBackend(ABC):
    @abstractmethod
    def supports(self, target: TargetSpec) -> bool: ...

    @abstractmethod
    def build_plan(self, spec: HmiProjectSpec, context: "DeploymentContext") -> DeploymentPlan: ...

    @abstractmethod
    def execute(self, plan: DeploymentPlan, context: "DeploymentContext") -> "DeploymentResult": ...

    @abstractmethod
    def verify(self, spec: HmiProjectSpec, context: "DeploymentContext") -> "VerificationResult": ...
```

## 8.3 幂等性

重复部署同一份 IR 时必须满足：

- 不重复创建同名变量；
- 不重复插入同一事件；
- 不产生无限增长的脚本副本；
- `override` 策略下替换目标对象；
- `rename` 策略下使用确定性后缀，而不是随机名称；
- plan 中明确显示将创建、更新、跳过或重命名的对象。

---

# 9. Basic Panel 完整实现方案

## 9.1 技术路线

```text
IR V2
→ BasicCapabilityValidator
→ BasicClassicCompiler
→ Tag XML / Resource XML / Screen XML
→ Openness Import
→ Compile + Verify
```

Basic 不使用 VBS。复杂业务必须：

- 转为 PLC 逻辑；
- 拆成 FunctionList；
- 或返回不支持错误。

## 9.2 变量部署

### 外部变量

要求目标工程已经存在：

- PLC；
- PLC Tag/DB 成员；
- 集成连接。

生成或改写 HMI Tag XML 时必须保留真实导出结构中的：

- `AttributeList`；
- `LinkList`；
- `Connection` 链接；
- `ControllerTag` 链接；
- `AcquisitionCycle` 链接；
- `TargetID`/`CompositionName`；
- 目标版本命名空间。

### 内部变量

由真实导出的内部变量模板克隆。不要假设内部变量与外部变量只是少几个字段。

### 导入顺序

```text
确保 Tag Table 存在
→ 导入内部变量
→ 导入外部变量
→ 查询目标变量确认存在
→ 画面 XML 才允许引用
```

## 9.3 事件实现

Basic 事件全部映射到 FunctionList 模板。

建议动作映射：

| ActionSpec | Basic 实现 |
|---|---|
| set_bit | SetBit 类型系统函数模板 |
| reset_bit | ResetBit 类型系统函数模板 |
| toggle_bit | InvertBit 类型系统函数模板 |
| set_value | SetTag/SetValue 类型系统函数模板 |
| increment | IncreaseTag 类型模板 |
| decrement | DecreaseTag 类型模板 |
| activate_screen | ActivateScreen 类型模板 |
| call_script | 不支持，报错 |
| write_expression | 默认不支持，报错 |

实际函数类型名必须从目标版本黄金 XML 中读取。

## 9.4 动态属性

实现第一批白名单：

- `visible`；
- `background_color`；
- `foreground_color`；
- `text`/文本列表；
- `position_x`；
- `position_y`；
- `width`；
- `height`；
- `flashing`，仅当目标 fixture 已验证。

每种属性都对应独立 fragment：

```text
Dynamics/
├── Visible_DirectTag.xmlfrag
├── BackColor_Discrete.xmlfrag
├── ForeColor_Discrete.xmlfrag
├── PositionX_Linear.xmlfrag
├── PositionY_Linear.xmlfrag
└── Flashing_Tag.xmlfrag
```

## 9.5 Basic 编译器接口

```python
class BasicBackend(HmiBackend):
    def build_plan(self, spec, context): ...
    def compile_connections(self, connections): ...
    def compile_tags(self, tags): ...
    def compile_resources(self, resources): ...
    def compile_screen(self, screen): ...
    def compile_event(self, event): ...
    def compile_binding(self, binding): ...
```

## 9.6 Basic 验收场景

必须在真实设备项目中验证：

1. 启动按钮按下置位、释放复位；
2. 模式按钮点击取反；
3. 指示灯颜色跟随 Bool；
4. IO Field 显示 Real；
5. 可见性跟随 Bool；
6. 画面切换按钮；
7. 内部变量写入；
8. 外部变量链接 PLC DB；
9. 重复部署不重复创建对象；
10. 编译 error=0。

---

# 10. Comfort Panel 完整实现方案

## 10.1 技术路线

```text
IR V2
→ ComfortCapabilityValidator
→ ComfortClassicCompiler
→ Tag XML + VBS XML + Resource XML + Screen XML
→ Openness Import
→ Compile + Verify
```

Comfort 与 Basic 共用 Classic 基础设施，但不能直接共用全部 fragment。

## 10.2 动作选择策略

优先级：

```text
标准系统函数
→ 可组合 FunctionList
→ 已审核 VBS 模板
→ 不支持错误
```

简单逻辑必须使用 FunctionList，避免不必要 VBS。

## 10.3 VBS 生成与导入

### 使用场景

- 多条件判断；
- 多变量联动；
- 复杂计算；
- FunctionList 无法表达的逻辑。

### 禁止事项

- 不允许直接执行外部程序；
- 不允许文件系统任意写入；
- 不允许 Shell；
- 不允许用户输入直接拼接代码；
- 不允许 LLM 生成的未审核脚本直接部署。

### 流程

```text
ActionSpec/ScriptSpec
→ VbsBuilder
→ 安全扫描
→ 语法和变量引用校验
→ 生成/改写 VBS XML
→ 导入脚本
→ 查询脚本存在
→ 画面事件引用脚本
```

### 示例生成器

```python
class VbsBuilder:
    def build_toggle(self, tag: str) -> str:
        safe = self.quote_smarttag(tag)
        return f'SmartTags("{safe}") = Not SmartTags("{safe}")'

    def build_set_by_condition(self, condition, target, true_value, false_value): ...
```

## 10.4 Comfort 动态属性

第一批支持：

- Basic 全部白名单；
- `enabled`/可操作性；
- 离散和范围动态；
- 颜色、闪烁；
- 文本列表和图形列表；
- Popup/Slide-in，仅在目标设备支持并有 fixture 时；
- Faceplate instance，仅作为后续里程碑。

## 10.5 Comfort 模板隔离

目录必须按版本、设备和对象类型隔离：

```text
reference_catalog/V20/Comfort/TP1200/
├── manifest.yaml
├── screens/base_screen.xml
├── controls/button.xmlfrag
├── controls/io_field.xmlfrag
├── events/set_bit.xmlfrag
├── events/reset_bit.xmlfrag
├── events/call_vbs.xmlfrag
├── dynamics/visible.xmlfrag
├── dynamics/backcolor_discrete.xmlfrag
├── tags/internal_bool.xmlfrag
├── tags/external_real.xmlfrag
└── scripts/vbs_template.xmlfrag
```

## 10.6 Comfort 验收场景

除 Basic 全部场景外，还需：

1. 复杂 VBS 调用；
2. 动态可操作性；
3. 文本列表；
4. 图形列表；
5. 多动作 FunctionList 顺序正确；
6. 脚本先导入、画面后导入；
7. 事件引用脚本可解析；
8. 编译 error=0。

---

# 11. Unified 完整实现方案

## 11.1 技术路线

```text
IR V2
→ UnifiedCapabilityValidator
→ Unified Direct Builder
→ HmiUnified object model
→ JavaScript/EventHandlers/Dynamizations
→ Compile + Verify
```

不再让 `simaticml_generator.py` 承担 Unified 的最终创建。

## 11.2 DLL 加载

需要加载并记录：

- `Siemens.Engineering.dll`；
- 对应版本的 HmiUnified 程序集；
- 版本号；
- 文件路径；
- 公开类型列表；
- 目标项目版本。

```python
class AssemblyLoader:
    def load(self, tia_version: str) -> AssemblyMetadata: ...
```

必须防止混用不同版本 DLL。

## 11.3 运行时反射适配

由于不同版本类型名和属性可能变化，使用反射适配：

```python
class UnifiedReflectionAdapter:
    def find_type(self, candidates: list[str]): ...
    def get_enum_values(self, enum_type): ...
    def has_property(self, obj, name: str) -> bool: ...
    def set_first_supported(self, obj, names: list[str], value): ...
    def create_screen_item(self, composition, type_key: str, name: str): ...
```

反射结果缓存到：

```text
runtime_cache/<tia-version>/<assembly-hash>.json
```

## 11.4 Unified 变量

支持两种模式：

### Direct API

适合少量和动态变量：

```text
TagTable.Create
→ Tags.Create
→ 设置 DataType
→ 设置 Connection
→ 设置 ExternalTag/Address/ControllerTag
→ 查询错误服务
```

### WinCC ML

适合批量变量：

```text
TagSpec[]
→ WinCC ML/YAML builder
→ TagTable.Tags.Import
→ 查询创建结果
```

配置：

```yaml
unified:
  tag_deployment_mode: auto  # direct | wincc_ml | auto
  wincc_ml_threshold: 200
```

## 11.5 Unified 画面和对象

```python
class UnifiedScreenBuilder:
    def create_screen(self, spec: ScreenSpec): ...
    def create_item(self, screen, item: ScreenItemSpec): ...
    def apply_static_properties(self, item_obj, item_spec): ...
```

对象类型映射不允许直接硬编码 .NET 类型对象，应通过版本 adapter：

```python
UNIFIED_TYPE_KEYS = {
    "button": ["HmiButton"],
    "io_field": ["HmiIOField", "HmiIoField"],
    "text": ["HmiTextBox"],
    "rectangle": ["HmiRectangle"],
    "ellipse": ["HmiEllipse"],
    "switch": ["HmiSwitch"]
}
```

候选名只是搜索条件，运行时必须确认类型存在。

## 11.6 静态属性

属性映射通过白名单：

```python
PROPERTY_ALIASES = {
    "left": ["Left", "X"],
    "top": ["Top", "Y"],
    "width": ["Width"],
    "height": ["Height"],
    "visible": ["Visible"],
    "enabled": ["Enabled", "Operability"],
    "background_color": ["BackColor", "BackgroundColor"],
    "foreground_color": ["ForeColor", "ForegroundColor"]
}
```

颜色和多语言文本必须使用版本适配器，不允许简单传入任意字符串后假定成功。

## 11.7 Unified 动态化

映射：

| BindingSpec | Unified |
|---|---|
| direct_tag | TagDynamization |
| discrete | TagDynamization + mapping/formula，依版本适配 |
| range | TagDynamization/Expression |
| flashing | FlashingDynamization |
| resource_list | ResourceListDynamization |
| expression | ScriptDynamization 或表达式动态 |
| script | ScriptDynamization |

接口：

```python
class UnifiedBindingBuilder:
    def create(self, target_obj, binding: BindingSpec, context): ...
    def syntax_check(self, dynamization_obj): ...
```

必须验证：

- `PropertyName` 存在；
- 该属性支持相应动态化类型；
- source tag 存在；
- script dynamization 通过 SyntaxCheck；
- trigger 配置有效。

## 11.8 Unified 事件

```python
class UnifiedEventBuilder:
    def create_event_handler(self, item_obj, event: EventSpec): ...
    def resolve_event_enum(self, item_obj, semantic_event: str): ...
    def build_javascript(self, actions: list[ActionSpec]): ...
```

事件枚举必须通过当前 DLL 的公开枚举值匹配，使用候选语义词：

```text
press: Pressed / PointerDown / OnPress
release: Released / PointerUp / OnRelease
click: Clicked / Click / Tapped
change: Changed / ValueChanged
```

如果无法唯一匹配，必须报错并输出当前版本支持的枚举列表。

JavaScript 构建器只允许白名单 API 和模板。

## 11.9 Unified 验收场景

1. 创建变量表；
2. 创建内部 Bool；
3. 创建外部 Real；
4. 创建画面；
5. 创建按钮、文本、IO Field、矩形和指示对象；
6. 设置多语言文本；
7. 标签动态化；
8. 离散颜色动态；
9. 闪烁动态；
10. 点击/按下/释放事件；
11. JavaScript 语法检查；
12. 重复部署幂等；
13. 编译 error=0。

---

# 12. 黄金参考工程与 XML Fragment Catalog

## 12.1 每个目标组合必须有黄金项目

组合键：

```text
TIA 主版本 + HMI 家族 + 具体设备型号 + 分辨率
```

例如：

```text
V16 / Basic / KTP700 Basic / 800x480
V18 / Comfort / TP1200 Comfort / 1280x800
V20 / Unified / Unified Comfort Panel / 1280x800
```

## 12.2 黄金工程内容

每个 Classic 黄金画面至少包含：

- 静态文本；
- Button；
- IO Field；
- Symbolic IO Field；
- 状态指示对象；
- Bool 内部变量；
- Real 外部变量；
- 按下置位；
- 释放复位；
- 点击取反；
- 切换画面；
- 可见性动态；
- 离散颜色动态；
- 闪烁动态；
- 文本列表；
- Comfort 的 VBS 调用。

## 12.3 Catalog manifest

```yaml
catalog_version: 1
key:
  tia_version: V20
  family: comfort
  device_type: TP1200 Comfort
  resolution: 1280x800
source:
  exported_at: 2026-06-19
  project_name: HMI_Golden_V20
fragments:
  controls.button: controls/button.xmlfrag
  controls.io_field: controls/io_field.xmlfrag
  events.set_bit: events/set_bit.xmlfrag
  events.reset_bit: events/reset_bit.xmlfrag
  events.call_vbs: events/call_vbs.xmlfrag
  dynamics.visible: dynamics/visible.xmlfrag
  dynamics.backcolor_discrete: dynamics/backcolor_discrete.xmlfrag
```

## 12.4 Fragment 处理原则

- 片段必须包含上下文元数据；
- 不允许简单字符串 replace；
- 使用 XML DOM/XPath；
- 所有 ID 由 `XmlIdRegistry` 统一分配；
- 所有引用由 `LinkResolver` 统一重写；
- 每个 fragment 有 schema fingerprint；
- TIA 版本不匹配默认拒绝。

---

# 13. Classic XML 核心组件

## 13.1 XmlIdRegistry

```python
class XmlIdRegistry:
    def allocate(self, logical_key: str) -> str: ...
    def register_existing(self, xml_root): ...
    def rewrite_subtree(self, subtree) -> dict[str, str]: ...
    def assert_unique(self, root): ...
```

要求确定性 ID：同一个部署输入在同一目标下生成稳定结果。

## 13.2 LinkResolver

```python
class LinkResolver:
    def bind_tag(self, node, tag_name, table_name): ...
    def bind_script(self, node, script_name): ...
    def bind_screen(self, node, screen_name): ...
    def bind_text_list(self, node, list_name): ...
    def validate_links(self, root, symbol_table): ...
```

## 13.3 FunctionListBuilder

```python
class FunctionListBuilder:
    def build(self, event: EventSpec, target: ClassicTarget) -> list[XmlFragment]: ...
    def build_action(self, action: ActionSpec) -> XmlFragment: ...
```

必须保持动作顺序。

## 13.4 DynamicXmlBuilder

```python
class DynamicXmlBuilder:
    def build(self, binding: BindingSpec, item_type: str) -> XmlFragment: ...
```

必须在 manifest 中登记“哪些属性、哪些控件类型验证过”。

## 13.5 ClassicValidator

导入前检查：

- XML 可解析；
- 命名空间匹配；
- ID 唯一；
- 引用目标存在；
- 画面尺寸匹配；
- 对象名称唯一；
- 变量名称存在；
- FunctionList 参数完整；
- 不包含目标设备不支持对象；
- 不包含未登记 fragment。

---

# 14. 对现有模块的具体改造

## 14.1 `backend/hmi_ir.py`

### 保留

- 当前布局校验；
- 分辨率缩放；
- 几何边界处理；
- 对象重叠修复。

### 新增

- `validate_ir_v2()`；
- tag、binding、event、action 交叉引用校验；
- capability-aware validation；
- 旧 IR 到 V2 转换入口。

### 禁止

- 在此文件中生成设备特定 XML 或脚本。

## 14.2 `backend/variable_engine.py`

### 当前问题

直接生成 VBS，无法支持 Basic/Unified。

### 改造后职责

- 推断 TagSpec；
- 推断数据类型；
- 推断内部/外部变量；
- 推断 EventSpec；
- 推断 ActionSpec；
- 推断 BindingSpec；
- 生成命名建议；
- 不生成最终 VBS/JavaScript/XML。

### 新接口

```python
class VariableEngine:
    def enrich(self, legacy_or_v2_ir: dict, target_hint: str | None = None) -> HmiProjectSpec: ...
```

## 14.3 `backend/simaticml_generator.py`

### 处理方式

- 标记为 Legacy；
- 仅保留旧模式和测试兼容；
- 不作为 Unified 的正式后端；
- 逐步将 Classic 模板逻辑迁移到 `backends/classic`。

## 14.4 `backend/template_xml_generator.py`

拆分到：

- `screen_xml_builder.py`；
- `tag_xml_builder.py`；
- `function_list_builder.py`；
- `dynamic_xml_builder.py`；
- `xml_id_registry.py`；
- `link_resolver.py`。

## 14.5 `backend/openness_manager.py`

最终只保留 façade：

```python
class OpennessManager:
    def connect(self, ...): ...
    def discover(self, ...): ...
    def plan(self, spec, ...): ...
    def deploy(self, plan, ...): ...
    def verify(self, ...): ...
    def close(self): ...
```

内部委托：

- SessionManager；
- DeviceDiscovery；
- DeploymentService；
- Compiler；
- VerificationService。

## 14.6 `backend/import_engine.py`

迁移为 `DeploymentService`，负责：

- 选择后端；
- 执行步骤；
- 进度事件；
- 错误转换；
- 事务日志；
- 结果聚合。

## 14.7 `app.py`

新增接口：

```text
POST /api/hmi/validate
POST /api/hmi/plan
POST /api/hmi/deploy
POST /api/hmi/verify
GET  /api/hmi/capabilities
GET  /api/hmi/runtime-metadata
POST /api/hmi/reference/export
POST /api/hmi/reference/register
```

旧接口保留并内部转发。

---

# 15. API 设计

## 15.1 生成部署计划

`POST /api/hmi/plan`

请求：

```json
{
  "project": {"schema_version": "2.0"},
  "options": {
    "dry_run": true,
    "conflict_policy": "rename",
    "compile_after_deploy": true
  }
}
```

响应：

```json
{
  "plan_id": "plan_...",
  "backend": "comfort_classic",
  "steps": [],
  "diagnostics": [],
  "summary": {
    "connections": 1,
    "tags": 12,
    "scripts": 1,
    "screens": 2,
    "bindings": 8,
    "events": 6
  }
}
```

## 15.2 部署

`POST /api/hmi/deploy`

支持 SSE：

```text
plan_started
dependency_check
connection_deployed
tag_deployed
script_deployed
screen_deployed
binding_deployed
event_deployed
compile_started
compile_result
verification_result
deployment_done
```

## 15.3 能力查询

`GET /api/hmi/capabilities`

返回当前连接的：

- TIA 版本；
- DLL 版本；
- 设备类型；
- 目标后端；
- 支持控件；
- 支持事件；
- 支持动态化；
- 已安装 catalog。

---

# 16. 配置文件升级

```yaml
openness:
  tia_version: auto
  dll_path: null
  attach_mode: running_instance
  project_name: null
  hmi_device: HMI_1
  save_after_deploy: true
  compile_after_deploy: true
  exclusive_access: true

hmi_deployment:
  backend: auto
  conflict_policy: rename
  missing_dependency_policy: error
  unsupported_feature_policy: error
  enable_legacy_simaticml: false
  dry_run_by_default: true

classic:
  catalog_root: reference_catalog
  require_exact_tia_version: true
  allow_minor_device_match: false
  validate_xml_before_import: true
  basic:
    allow_vbs: false
  comfort:
    allow_vbs: true
    script_security_scan: true

unified:
  min_recommended_tia_version: V18
  tag_deployment_mode: auto
  wincc_ml_threshold: 200
  reflection_cache: runtime_cache
  javascript_security_scan: true
  syntax_check: true

verification:
  verify_object_counts: true
  verify_tag_references: true
  verify_events: true
  verify_dynamizations: true
  fail_on_compile_warning: false
  fail_on_compile_error: true
```

---

# 17. 错误和诊断模型

```python
class Diagnostic(BaseModel):
    code: str
    severity: Literal["info", "warning", "error"]
    phase: str
    object_type: str | None = None
    object_name: str | None = None
    message: str
    details: dict = {}
    remediation: str | None = None
```

错误代码示例：

```text
CAP_UNSUPPORTED_EVENT
CAP_UNSUPPORTED_BINDING
DEP_MISSING_CONNECTION
DEP_MISSING_CONTROLLER_TAG
CLASSIC_FRAGMENT_NOT_FOUND
CLASSIC_SCHEMA_MISMATCH
CLASSIC_BROKEN_LINK
UNIFIED_TYPE_NOT_FOUND
UNIFIED_EVENT_ENUM_AMBIGUOUS
UNIFIED_PROPERTY_NOT_SUPPORTED
SCRIPT_SECURITY_REJECTED
SCRIPT_SYNTAX_FAILED
IMPORT_TIA_EXCEPTION
COMPILE_ERROR
VERIFY_TAG_MISSING
VERIFY_EVENT_MISSING
VERIFY_BINDING_MISSING
```

不要把 .NET 异常原样直接返回前端；保留内部 stack trace，并输出清晰诊断。

---

# 18. 事务、回滚与安全

## 18.1 事务日志

每个步骤记录：

- 开始时间；
- 结束时间；
- 目标对象；
- 创建/更新前状态；
- 创建/更新后状态；
- 生成文件；
- TIA 返回结果；
- rollback 信息。

## 18.2 回滚策略

TIA Openness 不保证所有操作原子事务，因此采用补偿式回滚：

- 新建对象：失败时删除；
- 覆盖对象：部署前导出备份；
- 画面覆盖：保留原画面 XML；
- 脚本覆盖：保留原脚本 XML；
- 变量覆盖：记录原属性或导出变量表；
- 保存项目只在全部验证通过后执行。

配置：

```yaml
rollback:
  enabled: true
  backup_root: deployment_backups
  save_only_on_success: true
```

## 18.3 脚本安全

VBS 和 JavaScript 均需：

- AST 或词法扫描；
- 白名单 API；
- 禁止 Shell/FileSystem/网络访问；
- 限制长度；
- 限制循环；
- 限制动态代码执行；
- 所有 tag 名通过安全转义；
- 保存源脚本 hash。

---

# 19. 测试策略

## 19.1 单元测试

- IR V2 模型；
- Legacy Adapter；
- Tag 推断；
- Action 推断；
- Capability 验证；
- Dependency Graph；
- ID 分配；
- Link 重写；
- FunctionList fragment 生成；
- VBS/JS 安全扫描；
- 版本反射适配。

## 19.2 Golden XML 测试

对 Classic XML：

1. 输入固定 IR；
2. 生成 XML；
3. XML 归一化；
4. 与黄金 XML 比较；
5. 忽略允许变化的 ID/时间戳；
6. 引用关系必须一致。

## 19.3 Contract 测试

每个 catalog manifest 必须通过：

- fragment 文件存在；
- XPath 可找到替换点；
- schema fingerprint 匹配；
- 版本/设备元数据完整；
- 必需变量和参数定义完整。

## 19.4 TIA 集成测试

由于 CI 通常没有 TIA，分两层：

### 自动 CI

- 所有纯 Python 测试；
- XML 校验；
- fixture 对比；
- 反射测试使用 mock assembly metadata。

### Windows/TIA 手工或专用 Runner

- 启动指定 TIA 版本；
- 打开测试项目；
- 部署；
- 编译；
- 导出回读；
- 对比；
- 清理项目。

## 19.5 回归测试矩阵

| 版本 | Basic | Comfort | Unified |
|---|---|---|---|
| V16 | 必测 | 必测 | 有限模式 |
| V18 | 选测 | 必测 | 必测 |
| V19 | 选测 | 必测 | 必测 |
| V20 | 必测 | 必测 | 必测 |

实际支持范围由团队拥有的许可证和设备决定。

---

# 20. 验证闭环

## 20.1 部署后查询

验证服务必须查询目标项目，不只检查本地生成文件。

```python
class VerificationService:
    def verify_tags(self, expected): ...
    def verify_screens(self, expected): ...
    def verify_events(self, expected): ...
    def verify_bindings(self, expected): ...
    def verify_scripts(self, expected): ...
    def verify_compile(self): ...
```

## 20.2 结果格式

```json
{
  "success": true,
  "objects": {
    "tags": {"expected": 12, "found": 12, "failed": []},
    "screens": {"expected": 2, "found": 2, "failed": []},
    "events": {"expected": 6, "found": 6, "failed": []},
    "bindings": {"expected": 8, "found": 8, "failed": []}
  },
  "compile": {
    "errors": 0,
    "warnings": 1,
    "messages": []
  }
}
```

## 20.3 Classic 反向导出验证

对 Basic/Comfort，部署后可选择重新导出画面/变量 XML并归一化比较，以验证：

- 事件存在；
- 变量链接存在；
- 动态化存在；
- 对象属性保存成功。

---

# 21. 分阶段实施计划

## Phase 0：基线保护与诊断（必须首先完成）

### 目标

不改变现有功能，建立测试和运行时诊断。

### 任务

- 为当前主分支打 tag；
- 添加现有 API 回归测试；
- 将真实项目的最小 IR、XML、日志存为 fixture；
- 拆出 AssemblyLoader；
- 增加 RuntimeMetadata；
- 增加设备发现和版本日志；
- 增加 dry-run API 框架。

### DoD

- 旧画面导入功能不退化；
- 能输出 TIA 版本、DLL 版本、设备类型；
- 测试可重复运行。

## Phase 1：IR V2 与 Legacy Adapter

### 任务

- 新增 Pydantic 模型；
- 实现 LegacyIrAdapter；
- 重构 VariableEngine 输出 TagSpec/EventSpec/ActionSpec/BindingSpec；
- 更新 prompts，让 LLM 输出 V2 或兼容转换；
- 增加交叉引用校验。

### DoD

- 现有 Few-shot 输入可转成 V2；
- 不再由 VariableEngine 直接生成 VBS；
- IR 中变量、绑定、事件可完整表达。

## Phase 2：Deployment Planner 与能力矩阵

### 任务

- 实现 CapabilityService；
- 实现 DeploymentPlan；
- 实现 dependency graph；
- 实现冲突策略；
- 实现 `/api/hmi/plan`。

### DoD

- Basic 输入复杂 VBS 动作时在 plan 阶段报错；
- 计划顺序保证变量先于画面；
- dry-run 能准确列出部署内容。

## Phase 3：Comfort Classic 完整链路

先实现 Comfort，因为它覆盖 Classic 的大部分能力。

### 任务

- 建立一个明确版本和设备的黄金项目；
- 导出 tag、script、screen fixtures；
- 实现 XmlFragmentCatalog；
- 实现 ID 和 Link 处理；
- 实现 Tag XML；
- 实现 FunctionList；
- 实现 VBS 导入和调用；
- 实现核心动态化；
- 实现编译验证。

### DoD

Comfort 最小完整场景通过，编译 error=0。

## Phase 4：Basic Classic 裁剪后端

### 任务

- 复用 Classic common；
- 建立 Basic 独立 catalog；
- 禁用 VBS；
- 增加 Basic 能力检查；
- 实现 Basic 支持的 FunctionList；
- 实现核心动态化。

### DoD

Basic 最小完整场景通过，编译 error=0，所有不支持功能在 plan 阶段明确报错。

## Phase 5：Unified Direct Backend

### 任务

- 拆分 Unified 直接创建逻辑；
- 加入反射适配；
- 实现 Tag/Table；
- 实现 Screen/ScreenItem；
- 实现 Property；
- 实现 Dynamization；
- 实现 EventHandler/JavaScript；
- 实现 SyntaxCheck；
- 实现 verify。

### DoD

Unified 最小完整场景通过，编译 error=0。

## Phase 6：事务、回滚、前端和可观测性

### 任务

- 步骤日志；
- 部署备份；
- 失败补偿；
- 前端显示 plan 和 diagnostics；
- SSE 显示各阶段；
- 导出部署报告。

### DoD

用户可以在部署前看到变更，在失败后看到准确原因，并可恢复被覆盖的 Classic 对象。

## Phase 7：扩展控件和工程对象

按业务优先级逐步添加：

- Text/Graphic List；
- Popup；
- Slide-in；
- Faceplate；
- Alarm Control；
- Trend Control；
- Recipe；
- 用户管理。

每个新增能力必须先有黄金 fixture 和验收用例。

---

# 22. Claude Code 任务拆分清单

建议按以下顺序提交独立 PR。

## PR-01：领域模型和兼容适配

- [ ] 新增 `backend/domain/ir_v2.py`
- [ ] 新增枚举和诊断模型
- [ ] 新增 LegacyIrAdapter
- [ ] 添加单元测试
- [ ] 不修改现有部署行为

## PR-02：VariableEngine 语义化

- [ ] 移除核心逻辑对 VBS 的依赖
- [ ] 输出 TagSpec
- [ ] 输出 BindingSpec
- [ ] 输出 EventSpec/ActionSpec
- [ ] 保留旧字段兼容序列化

## PR-03：能力和部署计划

- [ ] CapabilityService
- [ ] DeploymentPlanner
- [ ] `/api/hmi/plan`
- [ ] dry-run
- [ ] diagnostics

## PR-04：Openness 拆分

- [ ] AssemblyLoader
- [ ] SessionManager
- [ ] DeviceDiscovery
- [ ] Compiler
- [ ] ExceptionMapper
- [ ] `OpennessManager` façade

## PR-05：Classic Catalog 基础设施

- [ ] manifest schema
- [ ] catalog loader
- [ ] fragment cloning
- [ ] XmlIdRegistry
- [ ] LinkResolver
- [ ] ClassicValidator

## PR-06：Comfort tags + screen

- [ ] tag table/import
- [ ] internal/external tag
- [ ] screen item binding
- [ ] static properties
- [ ] integration test checklist

## PR-07：Comfort events + dynamics + VBS

- [ ] FunctionListBuilder
- [ ] DynamicXmlBuilder
- [ ] VbsBuilder
- [ ] VBS import
- [ ] event script reference
- [ ] compile verify

## PR-08：Basic backend

- [ ] Basic catalog
- [ ] capability restrictions
- [ ] FunctionList
- [ ] dynamics
- [ ] no-VBS enforcement

## PR-09：Unified core

- [ ] reflection adapter
- [ ] tags
- [ ] screens/items
- [ ] static properties

## PR-10：Unified dynamics + events

- [ ] tag dynamization
- [ ] flashing/resource/script dynamization
- [ ] event enum resolution
- [ ] JS builder
- [ ] syntax check

## PR-11：Verification and report

- [ ] object query
- [ ] compile result parser
- [ ] reverse-export compare
- [ ] deployment report

## PR-12：Frontend workflow

- [ ] validate
- [ ] plan preview
- [ ] deploy progress
- [ ] diagnostics panel
- [ ] compile and verification report

---

# 23. 编码规则

## 23.1 Python

- Python 3.10+；
- 新代码必须有类型注解；
- Pydantic v2；
- 不在业务模块直接访问 Flask global；
- .NET 对象只能在 Openness runtime 层流动；
- domain 模型不得依赖 pythonnet；
- 每个外部异常转换为 Diagnostic；
- 日志不得包含 API Key 或敏感路径。

## 23.2 XML

- 使用 `lxml.etree`；
- 禁止正则直接修改 XML；
- 禁止全局字符串 replace ID；
- 保留命名空间；
- 输出前 canonicalize；
- 所有 fragment 记录来源版本。

## 23.3 .NET/Openness

- 所有 DLL 加载必须显式版本检查；
- 所有写操作在 exclusive access 下执行；
- 操作前检查对象是否存在；
- 创建后立即查询；
- 对动态化和脚本调用语法检查服务；
- 不硬编码未知枚举整数。

## 23.4 LLM

- LLM 只生成业务 IR；
- 不允许 LLM 生成未经模板约束的 Classic XML；
- 不允许 LLM 直接提供 .NET 类型名作为可信输入；
- 所有名称经过 sanitizer；
- 所有脚本经过安全扫描。

---

# 24. Definition of Done

V3.0 核心版本只有在以下条件全部满足时才完成：

## 公共条件

- [ ] IR V2 可表达变量、属性、动态化、事件和动作；
- [ ] 旧 IR 自动转换；
- [ ] VariableEngine 不再直接绑定 VBS；
- [ ] 部署顺序为依赖优先；
- [ ] dry-run 可用；
- [ ] 部署结果结构化；
- [ ] 编译 error=0 才算成功；
- [ ] 重复部署幂等；
- [ ] 不支持功能不静默丢失。

## Basic

- [ ] 内部/外部变量创建或导入；
- [ ] IO Field 变量绑定；
- [ ] Set/Reset/Toggle；
- [ ] 画面切换；
- [ ] 可见性和颜色动态；
- [ ] 无 VBS；
- [ ] 编译 error=0。

## Comfort

- [ ] Basic 全部功能；
- [ ] VBS 导入和调用；
- [ ] 动态可操作性；
- [ ] 多动作事件；
- [ ] 编译 error=0。

## Unified

- [ ] 变量表和变量；
- [ ] Screen/ScreenItem；
- [ ] 静态属性；
- [ ] Tag/Flashing/Script Dynamization；
- [ ] EventHandler；
- [ ] JavaScript SyntaxCheck；
- [ ] 编译 error=0。

---

# 25. 第一批最小可交付场景

使用同一个业务需求生成三种面板：

> 电机控制画面：启动、停止、复位、自动/手动切换；运行和故障指示；速度设定和实际速度显示；故障时红色闪烁；自动模式下速度设定可操作，手动模式下禁用；可跳转到报警画面。

变量：

```text
Motor_Start       Bool external
Motor_Stop        Bool external
Motor_Reset       Bool external
Motor_AutoMode    Bool external
Motor_Running     Bool external
Motor_Fault       Bool external
Motor_SpeedSP     Real external
Motor_SpeedPV     Real external
Screen_Enable     Bool internal
```

事件：

```text
启动 press  → set Motor_Start
启动 release→ reset Motor_Start
停止 press  → set Motor_Stop
停止 release→ reset Motor_Stop
复位 press  → set Motor_Reset
复位 release→ reset Motor_Reset
模式 click  → toggle Motor_AutoMode
报警 click  → activate AlarmScreen
```

动态：

```text
运行灯颜色       ← Motor_Running
故障灯颜色/闪烁  ← Motor_Fault
速度设定 enabled ← Motor_AutoMode
主控件 visible   ← Screen_Enable
```

适配：

- Basic 若不支持动态 enabled，则 plan 阶段报错或根据策略改为 visible/PLC 联锁，不允许静默忽略；
- Comfort 使用 FunctionList，复杂逻辑可用 VBS；
- Unified 使用 EventHandler + JavaScript 和 Dynamization。

---

# 26. 实施时的风险清单

## 高风险

1. TIA 版本与 XML schema 不一致；
2. 设备型号支持能力不同；
3. Classic XML 引用 ID 断裂；
4. Integrated Connection 无法通过变量 XML自动创建；
5. Unified API 在不同版本中类型或属性变化；
6. 事件枚举名称变化；
7. 导入成功但编译失败；
8. 覆盖现有工程对象造成数据丢失。

## 控制措施

- 精确版本 catalog；
- 运行时反射；
- 部署前导出备份；
- dry-run；
- 依赖验证；
- 编译闭环；
- 反向导出；
- 小步 PR；
- 每个功能先黄金 fixture 后实现。

---

# 27. 官方能力依据与实现边界

本方案基于以下官方能力边界：

1. Classic HMI 的 Screen、HMI Tag Table、单个 Tag、Connection、VB Script 等对象可通过 TIA Portal Openness 的导入/导出接口处理，实际支持对象取决于面板类型。
2. 集成连接的外部 HMI 变量导出文件保存的是 PLC Tag 链接；导入前 PLC、PLC Tag 和集成连接必须已存在。
3. Unified 公开 Screens、ScreenItems、Tags、TagTables、EventHandlers、PropertyEventHandlers、Dynamization 和 ScriptDynamization 等对象模型能力。
4. Unified 的变量表可使用基于 YAML 的 WinCC ML 格式通过 Openness 在变量表层级导入/导出。
5. 不同 TIA 主版本的 API 和 schema 可能变化，因此必须使用对应版本文档、DLL 和参考导出文件。

Claude Code 不应根据本文件中的示意类型名直接假定某个 DLL 必然存在该类型，最终以目标环境反射结果为准。

---

# 28. 交付物清单

最终代码库应包含：

```text
1. IR V2 schema 和 JSON 示例
2. Legacy IR Adapter
3. Capability Matrix
4. Deployment Planner
5. Basic Backend
6. Comfort Backend
7. Unified Backend
8. Classic Reference Catalog
9. Runtime Reflection Cache
10. Deployment/Verification API
11. Compile + Verify 报告
12. 单元测试和 Golden 测试
13. 三类设备手工验收说明
14. 配置迁移文档
15. 旧接口兼容说明
16. 部署备份和回滚说明
```

---

# 29. Claude Code 开始执行时的建议命令

第一步不要直接改大量代码。先执行：

```text
1. 阅读 PROJECT_SUMMARY.md 和当前目录树。
2. 读取 hmi_ir.py、variable_engine.py、openness_manager.py、import_engine.py、simaticml_generator.py。
3. 输出“实际代码与本方案的差异报告”。
4. 运行现有测试，记录基线。
5. 创建 feature/hmi-ir-v2 分支。
6. 只实现 PR-01，不同时实现后端。
```

每个 PR 完成后必须输出：

```text
修改文件列表
新增公共接口
兼容性影响
测试结果
未解决问题
下一 PR 建议
```

---

# 30. 禁止 Claude Code 采用的捷径

- 禁止用一个“通用 XML”覆盖三类设备。
- 禁止仅在画面 XML 中写变量名而不创建 HMI Tag。
- 禁止在画面导入后才创建关键变量依赖。
- 禁止 Basic 使用 VBS。
- 禁止 Unified 继续依赖 Classic XML 节点。
- 禁止硬编码未验证的 TIA 枚举数字。
- 禁止通过字符串替换修改 XML ID。
- 禁止忽略导入异常后继续保存项目。
- 禁止以“画面在项目树出现”作为成功标准。
- 禁止在没有黄金参考 fixture 的情况下增加新 Classic 控件或事件。
- 禁止自动保存失败或未验证的工程变更。

---

# 31. 推荐的首个 Claude Code 指令

```text
你现在负责将 Siemens HMI Assistant V2.3 按《Siemens HMI Assistant V3.0 完整项目完善方案》升级。

首先不要实现 Basic/Comfort/Unified 后端。请完成 Phase 0 和 PR-01：
1. 检查项目真实目录和现有模块；
2. 运行测试并记录基线；
3. 新增 backend/domain 下的 IR V2、枚举、诊断和部署结果模型；
4. 新增 LegacyIrAdapter，把当前 IR 转成 HmiProjectSpec；
5. 为所有新模型编写单元测试；
6. 不改变现有 API 行为；
7. 不删除旧代码；
8. 输出差异报告、修改文件、测试结果和下一阶段风险。

重要约束：
- 新 domain 层不得依赖 Flask、pythonnet 或 Siemens DLL；
- VariableEngine 暂时不重构，只为后续留接口；
- 所有模型使用明确类型和 Pydantic v2；
- 对不确定的现有字段使用兼容映射，不要猜测删除。
```

---

# 32. 文档结论

项目完善的关键不是继续增加更多 XML 字段，而是建立：

```text
统一语义模型
+ 三种目标后端
+ 真实版本模板/反射
+ 依赖优先部署
+ 编译验证闭环
```

Basic、Comfort 和 Unified 可以共享业务 IR，但不能共享最终事件、脚本、动态化和对象创建机制。完成本方案后，系统应能够把自然语言需求稳定转换为真正可运行、可编译、可验证的 HMI 工程，而不是只有视觉画面的导入结果。

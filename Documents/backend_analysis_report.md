# SiemensHmi Assistant 后端模块分析报告

> 生成日期：2026-06-21
> 分析范围：`backend/` 目录全部 Python 模块（70+ 文件）

---

## 目录

1. [文件全景](#1-文件全景)
2. [各模块分层详解](#2-各模块分层详解)
   - [2.1 核心编排层](#21-核心编排层core)
   - [2.2 LLM/AI 客户端层](#22-llmai-客户端层)
   - [2.3 领域模型层](#23-领域模型层domain)
   - [2.4 变量与标签工程](#24-变量与标签工程)
   - [2.5 五层文本→XML→导入管线](#25-五层文本xml导入管线)
   - [2.6 面板族后端（Backends）](#26-面板族后端backends)
   - [2.7 Openness 层](#27-openness-层tia-portal-互操作)
   - [2.8 规划器与服务层](#28-规划器与服务层)
   - [2.9 其他模块](#29-其他模块)
3. [调用关系总图](#3-调用关系总图)
4. [模块依赖矩阵](#4-模块依赖矩阵)
5. [架构关键结论](#5-架构关键结论)

---

## 1. 文件全景

```
backend/
├── __init__.py
│
├── pipeline_orchestrator.py         # ▶ 管线编排器（入口）
├── hmi_ir.py                        # HMI IR 校验/归一化
├── variable_engine.py               # 变量引擎
├── openness_manager.py              # Openness 连接门面
├── template_xml_generator.py        # 模板 XML 重写
├── simaticml_generator.py           # SimaticML 生成
├── tag_binding_normalizer.py        # 标签绑定归一化
├── generation_summary.py            # 生成摘要
├── preview_renderer.py              # 预览渲染（PNG）
├── config_manager.py                # 配置管理
├── screen_number_allocator.py       # 画面号分配
├── multilingual_text_builder.py     # 多语言文本构建
├── import_engine.py                 # TIA XML 导入
├── xml_validator.py                 # XML 预导入校验
├── text_normalizer.py               # 文本清洗
├── tia_text_sanitizer.py            # 文本清理兼容层
├── llm_client.py                    # LLM API 客户端
├── mimo_client.py                   # MiMo 视觉 API
├── prompts.py                       # 生成用提示词
├── review_prompts.py                # 审查用提示词
│
├── domain/                          # 📦 领域模型（纯Pydantic）
│   ├── __init__.py
│   ├── enums.py                     # 枚举
│   ├── diagnostics.py               # 诊断模型
│   ├── ir_v2.py                     # V2 IR 核心模型
│   ├── validation.py                # 交叉验证
│   ├── legacy_adapter.py            # 旧版IR→V2适配
│   ├── deployment_plan.py           # 部署计划
│   └── deployment_result.py         # 部署结果
│
├── backends/                        # 🏭 面板族后端
│   ├── __init__.py
│   ├── base.py                      # HmiBackend ABC
│   ├── classic/                     # WinCC Basic / Comfort
│   │   ├── __init__.py
│   │   ├── basic_backend.py
│   │   ├── comfort_backend.py
│   │   ├── common.py                # 共享聚合
│   │   ├── tag_xml_builder.py
│   │   ├── screen_xml_builder.py
│   │   ├── function_list_builder.py
│   │   ├── dynamic_xml_builder.py
│   │   ├── vbs_builder.py
│   │   ├── classic_screen_reference_rewriter.py
│   │   ├── link_resolver.py
│   │   ├── xml_id_registry.py
│   │   ├── classic_validator.py
│   │   └── xml_fragment_catalog.py
│   └── unified/                     # WinCC Unified
│       ├── __init__.py
│       ├── unified_backend.py
│       ├── tag_builder.py
│       ├── screen_builder.py
│       ├── binding_builder.py
│       ├── event_builder.py
│       ├── js_builder.py
│       ├── property_builder.py
│       └── reflection_adapter.py
│
├── openness/                        # 🔌 TIA Portal Openness API
│   ├── __init__.py
│   ├── session_manager.py
│   ├── assembly_loader.py
│   ├── device_discovery.py
│   ├── compiler.py
│   ├── exception_mapper.py
│   ├── classic_executor.py
│   ├── unified_executor.py
│   ├── object_query_service.py
│   ├── diagnostics_utils.py
│   ├── runtime_contract.py
│   └── reflection_utils.py
│
├── planners/                        # 📋 部署规划
│   ├── __init__.py
│   ├── deployment_planner.py
│   └── dependency_graph.py
│
├── services/                        # ⚙️ 服务层
│   ├── __init__.py
│   ├── deployment_service.py        # 统一部署状态机
│   └── verification_service.py      # 部署后验证
│
├── capabilities/                    # ✅ 能力描述
│   ├── __init__.py
│   ├── static_matrix.py
│   └── capability_service.py
│
├── template/                        # 📐 模板系统（Classic专用）
│   ├── __init__.py
│   ├── template_profile.py
│   ├── prototype_extractor.py
│   ├── prototype_registry.py
│   ├── xml_utils.py
│   ├── xml_rewrite_rules.py
│   ├── event_pattern_extractor.py
│   ├── binding_pattern_extractor.py
│   └── template_binding_validator.py
│
├── validation/                      # 🛡️ 验证关口
│   ├── __init__.py
│   └── tag_binding_gate.py
│
├── utils/                           # 🔧 工具
│   ├── __init__.py
│   └── tag_prefix_utils.py
│
├── references/                      # 📎 参考目录
│   ├── __init__.py
│   └── catalog_service.py
│
└── debug/                           # 🐛 调试
    ├── __init__.py
    └── tag_pipeline_debug.py
```

---

## 2. 各模块分层详解

### 2.1 核心编排层（Core）

| 模块 | 一句话作用 | 内部调用 |
|------|-----------|----------|
| **`pipeline_orchestrator.py`** | 多阶段生成管线编排：LLM 生成 → IR 校验 → 预览 → MiMo 审查 → 迭代修正，输出 SSE 事件流 | `llm_client`, `hmi_ir`, `prompts`, `preview_renderer`, `mimo_client`, `review_prompts`, `tia_text_sanitizer`, `variable_engine` |
| **`hmi_ir.py`** | 校验/归一化 LLM 输出的 IR JSON，执行布局优化、对象类型校验、分辨率适配 | `utils.tag_prefix_utils` |
| **`generation_summary.py`** | 构建 V4.0 API 响应摘要（理解总结、标签表、绑定表、部署结果分阶段 P30/P50/P80） | `domain.ir_v2`, `domain.enums` |
| **`config_manager.py`** | 线程安全读写 `config.yaml`，管理 LLM/Openness/HMI 默认配置 | 无（独立模块） |

### 2.2 LLM/AI 客户端层

| 模块 | 一句话作用 | 内部调用 |
|------|-----------|----------|
| **`llm_client.py`** | OpenAI 兼容 `/chat/completions` 流式客户端，支持 thinking depth 和 reasoning_effort | 无（仅 `requests`） |
| **`mimo_client.py`** | MiMo 多模态视觉 API 客户端，支持 brief/detailed/ocr/ui 等多种输出模式 | 无（仅 `requests`） |
| **`prompts.py`** | LLM 系统提示词 + IR 完整 JSON Schema + 文本/标签/布局约定 + few-shot 示例（电机控制画面） | 无 |
| **`review_prompts.py`** | 视觉审查 6 维评价提示词 + 西门子色彩标准参考 + 图像分析任务模板 | 无 |

### 2.3 领域模型层（Domain）

这是系统的**数据核心**——纯 Pydantic v2 模型，零外部依赖，只向内导入。

```
enums.py ← diagnostics.py ← ir_v2.py ← validation.py
              ↕                          ↕
       deployment_plan.py      legacy_adapter.py
       deployment_result.py
```

| 模块 | 一句话作用 | 依赖 |
|------|-----------|------|
| **`domain/enums.py`** | 全部枚举定义：`HmiFamily`, `ScreenItemType`, `BindingKind`, `TagScope`, `DeploymentPhase` 等 | 无 |
| **`domain/diagnostics.py`** | `Diagnostic` 模型：错误码、严重级别、阶段、修复建议 | `enums` |
| **`domain/ir_v2.py`** | **核心**：`HmiProjectSpec`, `ScreenSpec`, `ScreenItemSpec`, `TagSpec`, `BindingSpec`, `EventSpec`, `ActionSpec` 等全部数据模型 | `enums`, `diagnostics` |
| **`domain/validation.py`** | `HmiProjectSpec` 交叉验证：schema 版本、屏幕/标签唯一性、交叉引用 | `ir_v2`, `diagnostics`, `enums` |
| **`domain/legacy_adapter.py`** | V2.3 遗留 IR dict → V2 `HmiProjectSpec` 转换器 | `enums`, `ir_v2`, `diagnostics` |
| **`domain/deployment_plan.py`** | `DeploymentPlan`, `DeploymentStep`（步骤排序/依赖/回滚） | `enums`, `ir_v2`, `diagnostics` |
| **`domain/deployment_result.py`** | `DeploymentResult`, `VerificationResult`, `CompileResult`, `ObjectCountSummary` | `diagnostics`, `enums` |

### 2.4 变量与标签工程

| 模块 | 一句话作用 | 内部调用 |
|------|-----------|----------|
| **`variable_engine.py`** | **核心引擎**：自动将 IR 屏幕对象映射为工程标签，含命名规则（BTN_/MEM_/STS_/LMP_/IO_/SIO_）、按钮行为推断、指示灯绑定推断、IOField 类型推断、标签冲突检测 | `domain.ir_v2`, `domain.enums`, `domain.legacy_adapter`, `domain.diagnostics`, `tag_binding_normalizer`, `validation.tag_binding_gate`, `utils.tag_prefix_utils` |
| **`tag_binding_normalizer.py`** | 归一化历史 IR 中的标签绑定字段（解决 process_tag/tag_binding/binding.tag/tags[] 不统一问题），提供 tag 名推断和完整性断言 | 无（独立，仅 `copy`, `re`） |
| **`validation/tag_binding_gate.py`** | 部署前关口：标签名称唯一性、item→tag 绑定存在性、数据类型适配性、未决 PLC 地址映射 | `domain.ir_v2`, `domain.diagnostics`, `domain.enums` |
| **`utils/tag_prefix_utils.py`** | 标签前缀字符串操作：strip/ensure/check 已知前缀 | 无 |

### 2.5 五层文本→XML→导入管线

严格层次结构，每一层只依赖前一层，不可跳过：

```
Layer 1: text_normalizer.py         ── HTML/Markdown/控制字符清洗
            ↓
Layer 2: multilingual_text_builder.py ── MultilingualText XML 片段构建
            ↓
Layer 3: screen_number_allocator.py ── 唯一画面号分配（compact / max_plus_one）
            ↓
Layer 4: xml_validator.py           ── 预导入 XML 校验（HTML污染/MultilingualText结构/禁止模式）
            ↓
Layer 5: import_engine.py           ── TIA Portal Openness API 导入
```

**并行路径：**
- **`simaticml_generator.py`**：从 IR 直接生成 SimaticML 命名空间 XML，依赖 Layer 1-4
- **`template_xml_generator.py`**：基于黄金模板 XML + IR 进行安全字段重写，依赖 `tia_text_sanitizer`（Layer 1-4 兼容层）
- **`tia_text_sanitizer.py`**：兼容 shim，封装 TextNormalizer/MultilingualTextBuilder/XmlValidator 为旧版 API

| 模块 | 作用 |
|------|------|
| **`text_normalizer.py`** | 清洗文本中的 HTML/Markdown 标签和控制字符，提供 `normalize()` 和 `normalize_ir()` |
| **`multilingual_text_builder.py`** | 构建 TIA 兼容 MultilingualText XML片段（避免 `<ID>` 子元素） |
| **`screen_number_allocator.py`** | 分配唯一画面号，支持 compact（填最小空缺）和 max_plus_one 策略 |
| **`xml_validator.py`** | 预导入 XML 校验，支持 V16/Comfort 和通用 XML 结构 |
| **`import_engine.py`** | 通过 Openness `screen.Import(FileInfo, ImportOptions.Override)` 导入 |
| **`simaticml_generator.py`** | 生成 SimaticML 命名空间 XML，处理 TIA 版本差异 |
| **`template_xml_generator.py`** | 基于黄金模板 XML 重写字段（模板引用/ID/名称前缀匹配） |
| **`tia_text_sanitizer.py`** | 兼容 shim，将 L1-L4 封装为 `sanitize_tia_text()` 等旧版 API |

### 2.6 面板族后端（Backends）

```
HmiBackend (ABC)                          backends/base.py
│   supports(), build_plan(), execute(), verify()
│
├── BasicBackend                          backends/classic/basic_backend.py
│   │  Basic Panel（无 VBS），生成 XML → Openness API
│   │  部署步骤：标签→文本列表→画面引用重写→导入→编译→6点验证
│   └── ClassicCommon 聚合：
│       ├── TagXmlBuilder                 ── 标签 XML 生成
│       ├── ScreenXmlBuilder              ── 画面 XML 生成
│       ├── FunctionListBuilder           ── 语义动作 → FunctionList XML
│       ├── DynamicXmlBuilder             ── 绑定 → 动态属性 XML
│       ├── ClassicScreenReferenceRewriter ── 模板变量泄漏重写
│       ├── LinkResolver                  ── 引用解析
│       ├── ClassicValidator              ── 预导入校验
│       └── XmlIdRegistry                 ── 确定性 hex ID 分配
│
├── ComfortBackend                        backends/classic/comfort_backend.py
│   │  Comfort Panel（支持 VBS），扩展 BasicBackend
│   │  额外部署步骤：VBS 脚本生成
│   └── ClassicCommon + VbsBuilder        ── VBS 脚本生成（SmartTags API 白名单）
│
└── UnifiedBackend                        backends/unified/unified_backend.py
    │  WinCC Unified（不走 XML，直接 Openness API 参数）
    │  部署步骤：Tag → Screen → Binding → Event → Script
    └── 子 builder：
        ├── UnifiedTagBuilder             ── Tag 创建参数
        ├── UnifiedScreenBuilder          ── Screen 创建规格
        ├── UnifiedBindingBuilder         ── Dynamization 参数
        ├── UnifiedEventBuilder           ── EventHandler 参数
        ├── JsBuilder                     ── JavaScript 生成（白名单安全扫描）
        ├── UnifiedPropertyBuilder        ── 属性名映射 + ARGB 转换
        └── UnifiedReflectionAdapter      ── 运行时反射类型解析
```

**关键区别：**
| 维度 | Classic (Basic/Comfort) | Unified |
|------|------------------------|---------|
| XML 策略 | 生成 XML → `screen.Import()` | 不生成 XML，直接构造 API 参数 |
| 脚本 | VBScript（Comfort 专属） | JavaScript |
| 绑定 | 动态属性 XML | Dynamization 对象 |
| 模板 | 使用 `template/` 模块重写 | 不适用 |

### 2.7 Openness 层（TIA Portal 互操作）

| 模块 | 一句话作用 | 内部调用 |
|------|-----------|----------|
| **`openness_manager.py`** | **门面**：统一 TIA Portal Openness 连接入口，支持 Windows 诊断模式 | 委托给所有 `openness.*` 子模块 |
| **`session_manager.py`** | 连接/断开 TIA Portal 实例，打开项目，诊断环境 | 无 |
| **`assembly_loader.py`** | 加载 `Siemens.Engineering.dll`，记录版本和公开类型 | 无 |
| **`device_discovery.py`** | 遍历 TIA 项目定位 HMI 设备，识别家族（Basic/Comfort/Unified） | 无 |
| **`compiler.py`** | 触发 `ICompilable.Compile()` 并递归收集 CompilerResult | 无 |
| **`exception_mapper.py`** | .NET/Openness 异常 → 结构化 `Diagnostic` 错误码 | `domain.diagnostics`, `domain.enums` |
| **`classic_executor.py`** | Classic Openness API 调用：连接导入/标签表/文本列表/画面导入/编译/回读验证 | `domain.diagnostics`, `domain.enums`, `diagnostics_utils` |
| **`unified_executor.py`** | Unified Openness API 调用：Tags/Screens 集合操作/Dynamization/EventHandlers/ScriptCode | `domain.diagnostics`, `domain.enums` |
| **`object_query_service.py`** | 只读对象查询（标签/画面/脚本），无副作用，持久化 JSON | 无 |
| **`diagnostics_utils.py`** | 异常链收集、.NET 对象描述、标签枚举、XML 结构检查 | 无 |
| **`runtime_contract.py`** | 探测当前 DLL 的 Unified 类型/Create 方法/属性/枚举，缓存为 JSON | 无 |
| **`reflection_utils.py`** | .NET 反射安全包装（类型探测、方法探测、属性获取） | 无 |

### 2.8 规划器与服务层

| 模块 | 一句话作用 | 内部调用 |
|------|-----------|----------|
| **`planners/deployment_planner.py`** | 从 `HmiProjectSpec` 生成有序部署计划，含依赖检查和能力验证 | `domain.*`（ir_v2, deployment_plan, diagnostics, enums, validation）, `capabilities.capability_service` |
| **`planners/dependency_graph.py`** | 有向无环图拓扑排序，检测循环依赖 | 无 |
| **`services/deployment_service.py`** | **V3.2 统一部署状态机**：DRY_RUN→NOT_CONNECTED→BLOCKED→DEPLOYING→DEPLOYED/FAILED。通过 `BackendFactory` 创建后端，执行 build→plan→execute→verify 全周期 | `domain.*`, `tag_binding_normalizer`, `validation.tag_binding_gate`, `planners.deployment_planner`, `backends.*` |
| **`services/verification_service.py`** | 部署后语义验证：对比真实 TIA 对象查询结果（标签/画面/绑定/事件/脚本） | `domain.ir_v2`, `domain.deployment_result`, `domain.diagnostics`, `domain.enums` |

### 2.9 其他模块

| 模块 | 作用 | 内部调用 |
|------|------|----------|
| **`capabilities/static_matrix.py`** | 静态能力矩阵：每面板族（Basic/Comfort/Unified）的 yes/no/limited/device 能力分级 | 无 |
| **`capabilities/capability_service.py`** | 静态矩阵 + 可选运行时反射 → CapabilitySet，验证 HmiProjectSpec 可行性 | `domain.*`, `static_matrix` |
| **`template/template_profile.py`** | 模板概要数据类：`TemplateProfile`, `ControlPrototype`, `EventPattern` 等 | 无 |
| **`template/prototype_extractor.py`** | 分析模板画面 XML，提取可复用控件原型到 TemplateProfile | `template_profile`, `xml_utils`, 各 pattern extractor |
| **`template/prototype_registry.py`** | 将 IR 控件与最合适的模板原型配对 | `template_profile` |
| **`template/xml_utils.py`** | 命名空间感知 XML 节点操作 | 无 |
| **`template/xml_rewrite_rules.py`** | 重写规则引擎：控件名/位置/文本/标签引用/事件变量 | `xml_utils` |
| **`template/event_pattern_extractor.py`** | 从控件 XML 提取事件模式（Click/Press/Release/SetBit/ResetBit 等） | `template_profile`, `xml_utils` |
| **`template/binding_pattern_extractor.py`** | 从控件 XML 提取绑定模式（ProcessValue/ColorAnimation/FlashAnimation/Visibility） | `template_profile`, `xml_utils` |
| **`template/template_binding_validator.py`** | 生成后画面 XML 校验：ID 唯一性、模板变量泄漏 | `xml_utils` |
| **`references/catalog_service.py`** | 扫描 manifest.yaml 发现和加载黄金参考工程目录 | `backends.classic.xml_fragment_catalog` |
| **`debug/tag_pipeline_debug.py`** | 15 个记录点的管线诊断日志 | `tag_binding_normalizer`（延迟） |
| **`preview_renderer.py`** | Pillow 渲染 IR 为 PNG（5 种控件类型：Text/IOField/SymbolicIOField/Button/Indicator） | 无（仅 PIL） |

---

## 3. 调用关系总图

```
                        ┌──────────────────────────────────────────┐
                        │        pipeline_orchestrator.py          │
                        │        (SSE 事件流生成管线)               │
                        │  图像分析→LLM生成→IR校验→预览→审查→迭代  │
                        └──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──────────┘
         ┌─────────────────┘  │  │  │  │  │  │  │  │  │
         ▼                    ▼  ▼  ▼  ▼  ▼  ▼  ▼  ▼  ▼
  ┌──────────────────────┐
  │  deployment_service  │  ┌─ llm_client.py ─── prompts.py
  │  (V3.2 统一部署状态机) │  ├─ hmi_ir.py ───── preview_renderer.py ── mimo_client.py
  └───┬─────┬────────────┘  ├─ tia_text_sanitizer.py → text_normalizer.py
      │     │               ├─ variable_engine.py → tag_binding_normalizer
      │     │               │                    └─→ validation.tag_binding_gate
      │     │               ├─ review_prompts.py
      │     │               └─ generation_summary.py
      │     │
      ▼     ▼
  ┌──────────────────────────────────────────────────┐
  │  planners/deployment_planner.py                   │
  │    ↓ 依赖检查、能力验证                             │
  │    capability_service → static_matrix             │
  │    domain.validation → validate_ir_v2             │
  └───────────────────────┬──────────────────────────┘
                          │
                          ▼
  ┌──────────────────────────────────────────────────┐
  │  BackendFactory → HmiBackend                      │
  │                                                   │
  │  ┌────────────────────┐  ┌────────────────────┐  │
  │  │ BasicBackend       │  │ UnifiedBackend     │  │
  │  │ ComfortBackend     │  │ (API参数模式)       │  │
  │  │ (XML生成模式)       │  └────────┬───────────┘  │
  │  └───────┬────────────┘           │              │
  └──────────┼────────────────────────┼──────────────┘
             │                        │
             ▼                        ▼
  ┌────────────────────┐  ┌────────────────────────┐
  │ ClassicOpennessExec│  │ UnifiedOpennessExec    │
  │  ↓ Openness API    │  │  ↓ Openness API        │
  │ screen.Import()    │  │ Tags.Add()             │
  │ tags.Export()      │  │ Screens.Add()          │
  │ Compile()          │  │ Dynamizations          │
  │ ReadBack()         │  │ EventHandlers          │
  └────────┬───────────┘  └───────────┬────────────┘
           │                          │
           ▼                          ▼
    ┌────────────────── TIA Portal ──────────────────┐
    │            Siemens.Engineering.dll              │
    │  TIA Portal v16 / v17 / v18 / v19              │
    └────────────────────────────────────────────────┘

    五层文本→XML→导入管线（独立于上述架构，被多处调用）：
    text_normalizer.py
         ↓
    multilingual_text_builder.py
         ↓
    screen_number_allocator.py
         ↓
    xml_validator.py
         ↓
    import_engine.py  ──→ TIA Portal Openness API
```

---

## 4. 模块依赖矩阵

| 模块 | 类别 | 依赖的内部模块 |
|------|------|---------------|
| **pipeline_orchestrator** | Core | `llm_client`, `hmi_ir`, `prompts`, `preview_renderer`, `mimo_client`, `review_prompts`, `tia_text_sanitizer`, `variable_engine` |
| **variable_engine** | Core | `domain.ir_v2`, `domain.enums`, `domain.legacy_adapter`, `domain.diagnostics`, `tag_binding_normalizer`, `validation.tag_binding_gate`, `utils.tag_prefix_utils` |
| **hmi_ir** | Core | `utils.tag_prefix_utils` |
| **generation_summary** | Core | `domain.ir_v2`, `domain.enums` |
| **deployment_service** | Service | `domain.*`, `tag_binding_normalizer`, `validation.tag_binding_gate`, `planners.deployment_planner`, `backends.*` |
| **deployment_planner** | Service | `domain.*`, `capabilities.capability_service` |
| **verification_service** | Service | `domain.ir_v2`, `domain.deployment_result`, `domain.diagnostics`, `domain.enums` |
| **capability_service** | Service | `domain.*`, `capabilities.static_matrix` |
| **BasicBackend** | Backend | `backends.base`, `domain.*`, `ClassicCommon`（7个子模块） |
| **ComfortBackend** | Backend | `backends.base`, `domain.*`, `ClassicCommon`, `VbsBuilder` |
| **UnifiedBackend** | Backend | `backends.base`, `domain.*`, 7 个 unified builder |
| **ClassicOpennessExecutor** | Openness | `domain.diagnostics`, `domain.enums`, `diagnostics_utils` |
| **UnifiedOpennessExecutor** | Openness | `domain.diagnostics`, `domain.enums` |
| **exception_mapper** | Openness | `domain.diagnostics`, `domain.enums` |
| **template_xml_generator** | Tooling | `tia_text_sanitizer` |
| **simaticml_generator** | Tooling | `text_normalizer`, `multilingual_text_builder`, `xml_validator` |
| **tag_binding_normalizer** | Tooling | 无 |
| **validation/tag_binding_gate** | Validation | `domain.ir_v2`, `domain.diagnostics`, `domain.enums` |
| **preview_renderer** | Tooling | 无（仅 PIL） |
| **config_manager** | Infrastructure | 无 |
| **llm_client** | Infrastructure | 无（仅 requests） |
| **mimo_client** | Infrastructure | 无（仅 requests） |
| **prompts** | Infrastructure | 无 |
| **review_prompts** | Infrastructure | 无 |
| **所有 domain/\*** | Domain | 仅 domain 内部 |
| **所有 template/\*** | Template | 仅 template 内部 + 各自的下级模块 |
| **所有 openness/\*** | Openness | 仅 `domain.diagnostics`, `domain.enums`（部分无依赖） |
| **text_normalizer** | Tooling | 无 |
| **multilingual_text_builder** | Tooling | `text_normalizer` |
| **screen_number_allocator** | Tooling | 无 |
| **xml_validator** | Tooling | 无 |
| **import_engine** | Tooling | 无 |
| **tia_text_sanitizer** | Tooling | `text_normalizer` |
| **tag_prefix_utils** | Utils | 无 |

---

## 5. 架构关键结论

### 5.1 两条部署路径并行存在

| 路径 | 入口 | 架构 | 状态 |
|------|------|------|------|
| **V3.2 新路径** | `deployment_service.py` → `planners/` → `backends/*` → `openness/executors` | 状态机 + 抽象后端（HmiBackend ABC） | 活跃/推荐 |
| **遗留路径** | `pipeline_orchestrator.py` → `variable_engine.py` + `hmi_ir.py` → 直接调用 `classic_executor` 或 `import_engine` | 流程式编排 | 兼容/遗留 |

`deployment_service.py` 是两者之间的桥接层，两种路径共享 domain 数据模型和 openness 执行器。

### 5.2 四种 XML 生成策略

| 策略 | 方式 | 所在模块 | 适用 |
|------|------|---------|------|
| 模板 XML 重写 | 基于黄金模板 XML + IR 字段重写 | `template_xml_generator.py` + `template/` | Classic |
| 从零 SimaticML | 直接生成 SimaticML 命名空间 XML | `simaticml_generator.py` | Classic |
| Classic 片段构建 | 每个控件类型独立 XML 片段 | `backends/classic/*_builder.py` | Classic |
| Unified API 参数 | 不生成 XML，直接构造 dict 调用 Openness API | `backends/unified/*_builder.py` | Unified |

### 5.3 Domain 包的纯模型设计

`domain/` 包是纯 Pydantic v2 数据模型，**零外部依赖**（仅依赖 stdlib），且严格只向内导入：

```
enums.py              （无依赖）
    ↓
diagnostics.py        （依赖 enums）
    ↓
ir_v2.py              （依赖 enums + diagnostics）
    ↓
validation.py         （依赖 ir_v2 + diagnostics + enums）
 ↓         ↓
deployment_plan.py    deployment_result.py
legacy_adapter.py
```

这种设计避免了循环依赖风险，所有外部模块只能单向依赖 domain 包。

### 5.4 五层严格管线

从文本清洗到 TIA 导入是一个不可跳过的层次结构：

```
text_normalizer → multilingual_text_builder → screen_number_allocator → xml_validator → import_engine
```

`import_engine.py` 明确标注了"严格阻止未经验证的 XML"。

### 5.5 模板系统仅用于 Classic

`template/` 包（8 个模块）是 Classic HMI（Basic/Comfort）专用的模板重写系统。Unified 路径不走 XML 模板重写，而是通过 Openness API 直接操作对象模型。

### 5.6 最高耦合模块

| 模块 | 被依赖次数（估计） | 说明 |
|------|-------------------|------|
| **`domain/ir_v2.py`** | 最高 | 几乎所有核心/后端/服务模块都导入 HmiProjectSpec |
| **`variable_engine.py`** | 高 | pipeline_orchestrator, deployment_service, generation_summary 都依赖它 |
| **`backends/classic/common.py`** | 高 | 聚合了 Classic 全部子 builder，被 BasicBackend 和 ComfortBackend 共用 |
| **`domain/enums.py`** | 高 | 被所有 domain 子模块、backends、openness 导入 |

### 5.7 外部库依赖总结

| 外部库 | 用途 | 使用模块 |
|--------|------|---------|
| `requests` | HTTP 客户端 | `llm_client.py`, `mimo_client.py` |
| `PIL (Pillow)` | 图像渲染 | `preview_renderer.py` |
| `pyyaml` | YAML 解析 | `config_manager.py`, `xml_fragment_catalog.py` |
| `lxml` | XML 处理 | `template/` 各模块、`xml_validator.py` |
| `pydantic` v2 | 数据模型 | `domain/` 全部模块 |
| `pythonnet` (clr) | .NET 互操作 | `openness/` 全部模块 |

---

> 本报告由 Claude Code 自动分析生成，涵盖 `backend/` 全部 70+ Python 文件。

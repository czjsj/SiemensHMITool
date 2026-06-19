# Siemens HMI Assistant — 后端架构总览

> 版本：V3.3 | 语言：Python 3.10+ | 框架：Flask | AI 模型：DeepSeek/OpenAI 兼容 API

---

## 一、项目简介

**Siemens HMI Assistant** 是一个基于 AI 大模型的西门子 WinCC / TIA Portal HMI 画面自动生成与部署工具。用户输入中文自然语言画面需求，系统自动生成 HMI 画面 IR（中间表示 JSON）、经 MiMo 视觉模型审查修正后，通过 TIA Portal Openness API 直接导入到博途项目中。

### 核心能力

- **AI 驱动画面生成**：中文需求 → LLM → HMI IR（JSON）→ 5 类 HMI 控件（IO域/符号IO域/按钮/指示灯/文本）
- **视觉审查与自修正**：渲染预览 PNG → MiMo 视觉模型审查 → 反馈循环修正 → 直至合格
- **TIA Portal 直接部署**：通过 Openness API 将生成的 XML 或对象模型直接导入博途
- **多面板兼容**：Basic (KTP) / Comfort / Unified 三类 HMI 均支持
- **双路线生成**：经典模板 XML 改写 + Unified 直接对象模型绘制

---

## 二、整体架构

```
用户浏览器 (Vue.js SPA)
       │
       ▼ SSE 流式事件
  ┌──────────────────────────────────────┐
  │            app.py (Flask)            │
  │   路由: /api/generate, /api/config,  │
  │        /api/openness/*, /api/export  │
  └──────────┬───────────────────────────┘
             │
  ┌──────────▼───────────────────────────┐
  │   pipeline_orchestrator.py           │
  │   ┌─────────────────────────────┐    │
  │   │ 1. LLM 生成 → HMI IR       │    │
  │   │ 2. validate_ir() 校验 +     │    │
  │   │    布局优化                  │    │
  │   │ 3. sanitize_ir_text() 清洗  │    │
  │   │ 4. VariableEngine 变量绑定  │    │
  │   │ 5. Preview 渲染 → MiMo 审查 │    │
  │   │ 6. 修正循环 (≤3轮)         │    │
  │   └─────────────────────────────┘    │
  └──────────┬───────────────────────────┘
             │
  ┌──────────▼───────────────────────────┐
  │     部署路由 (import_or_generate)     │
  │  ┌───────────────────────────────┐    │
  │  │ Classic HMI (Basic/Comfort)   │    │
  │  │  └→ template_xml_generator    │    │
  │  │     → import_engine           │    │
  │  │                                │    │
  │  │ Unified HMI                    │    │
  │  │  └→ unified_executor          │    │
  │  │     (直接对象模型)             │    │
  │  │                                │    │
  │  │ 通用备选                       │    │
  │  │  └→ simaticml_generator       │    │
  │  │     → Screens.Import()        │    │
  │  └───────────────────────────────┘    │
  └──────────┬───────────────────────────┘
             │
  ┌──────────▼───────────────────────────┐
  │      TIA Portal Openness API         │
  │  (Siemens.Engineering.dll via        │
  │   pythonnet CLR bridge)              │
  └──────────────────────────────────────┘
```

---

## 三、模块详解

### 3.1 核心流水线（Pipeline Layer）

| 文件 | 职责 |
|------|------|
| `pipeline_orchestrator.py` | 多阶段 SSE 流水线编排：LLM 生成 → IR 校验 → 文本清洗 → 变量绑定 → 预览渲染 → MiMo 审查 → 修正循环。所有阶段通过 `yield (event_name, data)` 返回给前端。 |
| `llm_client.py` | 大模型客户端（OpenAI 兼容接口）。支持 DeepSeek/OpenAI/兼容网关。**流式输出**：`reasoning_content` 作为 thinking 事件，正文作为 content 事件。三种推理模式：关闭/低/中/高（映射 reasoning_effort），无原生推理时降级为 `<thinking>` 诱导模式。 |
| `mimo_client.py` | MiMo 视觉 API 客户端。支持 path/url/base64 三种图片输入，自动缩放、MIME 推断。提供 8 种 output_schema（brief/detailed/ocr/chart/table/ui/drawing/compare），用于审查 HMI 预览图和分析参考图。 |
| `hmi_ir.py` | HMI IR（中间表示）校验与归一化。核心函数 `validate_ir()`：结构检查 → 补默认值 → 交叉引用校验 → 自动补全 tags → 轻量布局优化（重叠修复、间距对齐、边界裁剪）。支持分辨率缩放 `scale_ir_to_resolution()`。 |
| `variable_engine.py` | HMI 变量引擎。自动变量命名（BTN_/MEM_/STS_/LMP_/IO_ 前缀规则）、按钮行为检测（momentary/toggle）、指示灯颜色/闪烁绑定、IOField 数据类型推断、完整 Tag Table 生成。V3.0 新增语义模型 `HmiProjectSpec` 路线。 |
| `prompts.py` | LLM 系统提示词。包含 IR JSON Schema 文档、文字规范、变量绑定规范、VBS 规范、布局排版硬性规范、Few-shot 示例、修正模式提示词。`build_messages()` 组装对话。 |
| `review_prompts.py` | MiMo 审查任务模板。定义 6 个评估维度（布局对齐/组件尺寸/颜色规范/文字可读性/元素完整性/专业质量），Siemens 标准色参考。`build_review_feedback_text()` 将审查结果转为修正反馈。 |
| `preview_renderer.py` | HMI 预览渲染器。使用 Pillow 将 IR 直接绘制为 PNG：5 种对象（Text/IOField/SymbolicIOField/Button/Indicator），支持 CJK 字体、标签标注、脚本标记、blink 虚线环等视觉特性。 |
| `config_manager.py` | YAML 配置读写。线程安全的 `load_config()` / `save_config()`，Deep Merge 默认值补全。涵盖 LLM、Openness、HMI 默认值、MiMo、Server 五大配置域。 |

### 3.2 TIA Portal 集成层（Openness Layer）

| 文件 | 职责 |
|------|------|
| `openness_manager.py` | Openness Façade — 向后兼容入口。**核心功能**：连接/断开 TIA Portal（`connect()`/`disconnect()`）、HMI 设备查找与类型识别（Basic/Comfort/Unified）、导出参考画面 XML、导入画面（`import_screen()`/`import_screen_xml()`）、Unified 直接对象模型创建（`create_unified_screen_from_ir()`）、统一路由（`import_or_generate_from_ir()` → 自动选 unified_direct/classic_template_xml/simaticml）、HMI 变量表同步（`sync_tags()`）。**XML 预处理管线**：文本清洗 → MultilingualText DOM 重建 → Screen Number 删除 → 画面尺寸对齐 → 名称冲突检测 → XmlValidator 校验。 |

**Openness 子模块：**

| 文件 | 职责 |
|------|------|
| `openness/session_manager.py` | TIA Portal 会话管理：连接/断开/诊断 |
| `openness/device_discovery.py` | HMI 设备发现与类型识别（遍历 DeviceItems、SoftwareContainer、HmiUnified 探测） |
| `openness/classic_executor.py` | Classic HMI (Basic/Comfort) 真实 Openness 执行器。按顺序执行：connections → tags → text_lists → scripts → screens → compile → verify。使用官方 Composition.Import 模式。 |
| `openness/unified_executor.py` | WinCC Unified 真实 Openness 执行器。直接操作 hmiSoftware.Tags/Screens/ScreenItems、Dynamizations、EventHandlers、ScriptCode。执行前加载 RuntimeContract 验证 API 可用性。 |
| `openness/compiler.py` | TIA 编译触发 |
| `openness/exception_mapper.py` | .NET 异常 → Diagnostic 映射 |
| `openness/assembly_loader.py` | Siemens.Engineering.dll 加载与版本元数据 |
| `openness/runtime_contract.py` | Runtime API 契约验证 |
| `openness/object_query_service.py` | 对象查询服务 |
| `openness/diagnostics_utils.py` | 诊断工具函数 |

### 3.3 XML 导入管线（Import Pipeline — 5 层）

```
TextNormalizer → MultilingualTextBuilder → ScreenNumberAllocator
  → XmlValidator（闸门） → ImportEngine（终端）
```

| 层级 | 文件 | 职责 |
|------|------|------|
| 第1层 | `text_normalizer.py` | 文本规范化。9 步处理：HTML 实体解码 → 数字实体解码 → 注释移除 → 已知 HTML 标签移除 → 非法控制字符移除 → 空白统一 → Trim。`normalize_xml_content()` 安全清洗完整 XML（保留 TIA 合法富文本 `<body><p>`）。 |
| 第2层 | `multilingual_text_builder.py` | DOM 级 MultilingualText 标准构建。兼容通用结构（`<MultilingualText><Text Language="zh-CN">`）和 TIA V16/Comfort 结构（`ObjectList/MultilingualTextItem/AttributeList`）。禁止生成 `<ID>` 子元素。可见文本自动使用 `<body><p>` 富文本格式。 |
| 第3层 | `screen_number_allocator.py` | Screen Number 分配器。支持 compact（最小空缺）和 max_plus_one 两种策略。`remove_number_nodes()` 删除 XML 中 `<Number>` 节点。`detect_conflicts()` 检测号码冲突。 |
| 第4层 | `xml_validator.py` | Pre-Import 校验闸门。5 项检查：HTML 标签检测、MultilingualText 结构完整性（V16 和通用）、非法控制字符、Number 节点存在性、根元素完整性。**Fail Fast**：校验不通过则阻断导入。 |
| 第5层 | `import_engine.py` | 导入引擎。完整管线执行：预处理 → 校验 → `Screens.Import(FileInfo, ImportOptions.Override)`。唯一允许的导入方式，禁止任何 hack。 |

**兼容层：** `tia_text_sanitizer.py` — 旧 API 兼容委托（`sanitize_tia_text()` → `TextNormalizer.normalize()`，`lint_xml_content()` → `XmlValidator.validate()`）。

### 3.4 XML/代码生成器

| 文件 | 职责 |
|------|------|
| `template_xml_generator.py` | 经典模板 XML 改写器。入口 `generate_from_template_xml(ir, template_xml)`。**匹配策略**：template_ref → id → 名称前缀（TXT_/BTN_/IO_/SIO_/LMP_）→ 按 XML 标签类型映射 → 模糊前缀。**克隆机制**：同类型控件数量不足时自动深拷贝模板控件并分配新 SimaticML ID。**改写内容**：画面名、控件名、位置尺寸、文本、变量连接、颜色、脚本事件。 |
| `simaticml_generator.py` | SimaticML 生成器。`generate_simaticml(ir, tia_version, reference_xml)` — 从零生成带 SimaticML 命名空间的完整 XML。**5 种对象生成函数**：`_io_field_lines()` / `_symbolic_io_field_lines()` / `_button_lines()`（区分 momentary/toggle 事件） / `_indicator_lines()`（ColorAnimation + FlashAnimation） / `_text_lines()`。**模板信息提取**：`_extract_template_info()` 从参考 XML 提取命名空间、Screen 父级标签链、对象容器名。Basic 模式自动屏蔽 VBS 脚本输出。 |

### 3.5 领域模型层（Domain Layer — V3.0 新增）

| 文件 | 职责 |
|------|------|
| `domain/ir_v2.py` | IR V2 语义数据模型（Pydantic v2）。`HmiProjectSpec`（项目规格）、`ScreenSpec`（画面规格）、`ScreenItemSpec`（控件规格，含 GeometrySpec/BindingSpec/EventSpec/ActionSpec）、`TagSpec`（变量规格）、`ScriptSpec`、`DeploymentPolicies`。不依赖 Flask/pythonnet/Siemens DLL。 |
| `domain/enums.py` | 完整枚举体系。`HmiFamily`（basic/comfort/unified）、`ScreenItemType`（10种控件类型）、`BindingKind`（8种动画绑定）、`SemanticEvent`/`SemanticActionType`（语义事件/动作）、`DeploymentPhase`（P00-P90 9阶段）、`DeploymentStatus`（8状态状态机）等。 |
| `domain/validation.py` | IR V2 跨引用校验。检查 schema_version、screens 非空、tag/screen/script/resource 名称唯一性、外部变量连接存在性、控件 tag_binding 目标存在、事件动作引用完整性。 |
| `domain/legacy_adapter.py` | 旧 IR → HmiProjectSpec 适配器。已知字段严格映射，不确定字段保留在 metadata.extra 中。 |
| `domain/deployment_plan.py` | 部署计划模型。`DeploymentPlan` + `DeploymentStep`（含依赖关系、payload、rollback）。 |
| `domain/deployment_result.py` | 部署结果模型。`DeploymentResult`、`VerificationResult`、`CompileResult`、`ObjectCountSummary`。 |
| `domain/diagnostics.py` | 诊断模型。`Diagnostic`（含 code/severity/message/phase） + `DiagnosticCodes`。 |

### 3.6 后端执行器（Backends Layer）

| 文件 | 职责 |
|------|------|
| `backends/base.py` | 抽象基类 `HmiBackend`。定义 4 个统一接口：`supports()` / `build_plan()` / `execute()` / `verify()`。 |
| `backends/classic/` | **经典 HMI (Basic/Comfort) XML 后端**。含：`basic_backend.py` / `comfort_backend.py`（设备适配）、`xml_fragment_catalog.py`（XML 片段目录）、`xml_id_registry.py`（ID 注册）、`classic_validator.py`（校验器）、`function_list_builder.py`（函数列表）、`dynamic_xml_builder.py` / `screen_xml_builder.py` / `tag_xml_builder.py`（各类 XML 构建器）、`link_resolver.py`（连接解析）、`vbs_builder.py`（VBS 构建）、`classic_screen_reference_rewriter.py`（画面引用改写）、`common.py`（公共工具）。 |
| `backends/unified/` | **WinCC Unified 后端**。含：`unified_backend.py`（总后端）、`screen_builder.py`（画面构建）、`property_builder.py`（属性设置）、`binding_builder.py`（动态绑定）、`event_builder.py`（事件处理）、`js_builder.py`（JS 脚本）、`tag_builder.py`（变量构建）、`reflection_adapter.py`（反射适配）。 |

### 3.7 服务与计划层

| 文件 | 职责 |
|------|------|
| `services/deployment_service.py` | 统一部署服务。状态机：`DRY_RUN → NOT_CONNECTED → BLOCKED → DEPLOYING → DEPLOYED/FAILED`。调用链：Legacy IR → VariableEngine.enrich → validate_ir_v2 → BackendFactory → backend.build_plan → backend.execute → backend.verify → compile。`BackendFactory` 根据 TargetSpec 自动选择后端。 |
| `services/verification_service.py` | 部署后验收服务。 |
| `planners/deployment_planner.py` | 部署计划器。从 `HmiProjectSpec` 构建 `DeploymentPlan`，按依赖顺序（P00→P90）生成步骤，检查能力并汇聚诊断。 |
| `planners/dependency_graph.py` | 依赖图分析。 |

### 3.8 能力与引用服务

| 文件 | 职责 |
|------|------|
| `capabilities/static_matrix.py` | 静态设备能力对照表。覆盖 Basic/Comfort/Unified 三大面板家族的 30+ 项能力（控件类型、绑定类型、脚本语言、事件、资源、限制等）。 |
| `capabilities/capability_service.py` | 能力服务。`CapabilitySet` 查询能力值（yes/no/limited/device），`CapabilityService.validate()` 校验项目可行性。 |
| `references/catalog_service.py` | 引用目录服务。管理 HMI 设计模式的参考库。 |

---

## 四、数据流

```
用户输入 (中文需求)
      │
      ▼
prompts.py ── build_messages() ──→ LLM (DeepSeek/OpenAI)
      │                                  │
      │                          流式输出 (SSE)
      ▼                                  │
extract_json() ◄─────────────────────────┘
      │
      ▼
validate_ir() ──→ 结构校验 + 默认值 + 布局优化
      │
      ▼
sanitize_ir_text_fields() ──→ 文本清洗
      │
      ▼
VariableEngine.generate() ──→ 变量绑定 + VBS 生成
      │
      ▼  (若 MiMo 启用)
render_ir_to_png() ──→ MiMo 视觉审查 ──→ 得分 ≥70? ──→ 通过
      │                                    │ <70
      │                                    ▼
      │                              修正 feedback
      │                                    │
      │                                    ▼
      │                              LLM 重新生成
      │                                    │
      └────────────────────────────────────┘
      │ (审查通过 或 达到最大迭代次数)
      ▼
部署路由 import_or_generate_from_ir()
      │
      ├── Unified HMI ──→ create_unified_screen_from_ir() ──→ 直接对象模型创建
      │
      ├── Classic (有模板) ──→ generate_from_template_xml() ──→ import_screen_xml()
      │
      └── 通用备选 ──→ generate_simaticml() ──→ import_screen()
                              │
                              ▼
                    TIA Portal 画面已导入
```

---

## 五、关键技术决策

1. **IR 作为中间表示**：LLM 输出结构化 JSON（而非直接 XML），解耦生成与部署，便于校验、优化、审查。
2. **MiMo 视觉审查闭环**：渲染预览 → 视觉模型评分 → 反馈修正，最多 3 轮迭代。显著提升生成质量。
3. **Fail Fast 导入管线**：5 层顺序处理，XmlValidator 作为闸门，任何不合法 XML 直接阻断。
4. **双路线部署**：Classic HMI 走模板 XML 改写（安全保留原始结构），Unified 走直接对象模型 API。
5. **变量引擎自动化**：根据对象类型和关键词自动推断变量名、数据类型、按钮行为、指示灯语义。
6. **V3.0 语义模型演进**：从 dict-based IR 向 Pydantic v2 `HmiProjectSpec` 迁移，提升类型安全和校验能力。

---

## 六、模块依赖关系图

```
                            ┌─────────────┐
                            │   app.py    │ (Flask 路由)
                            └──────┬──────┘
                                   │
                    ┌──────────────┼──────────────┐
                    ▼              ▼              ▼
          ┌────────────────┐ ┌──────────┐ ┌──────────────┐
          │pipeline_       │ │config_   │ │openness_     │
          │orchestrator    │ │manager   │ │manager       │
          └───────┬────────┘ └──────────┘ └──────┬───────┘
                  │                               │
    ┌─────────────┼─────────────┐       ┌─────────┼─────────┐
    ▼             ▼             ▼       ▼         ▼         ▼
┌───────┐  ┌───────────┐  ┌────────┐ ┌────────┐ ┌──────────┐
│llm_   │  │hmi_ir     │  │preview │ │openness│ │import_   │
│client │  │validate_ir│  │renderer│ │submods │ │engine    │
└───┬───┘  └─────┬─────┘  └───┬────┘ └────────┘ └────┬─────┘
    │            │             │                      │
    ▼            ▼             ▼          ┌───────────┼───────────┐
┌───────┐  ┌───────────┐  ┌────────┐     ▼           ▼           ▼
│prompts│  │variable_  │  │mimo_   │ ┌────────┐ ┌────────┐ ┌────────┐
│       │  │engine     │  │client  │ │template│ │simaticml│ │xml_    │
│review │  └─────┬─────┘  └────────┘ │_xml_gen│ │_generator│ │validator│
│prompts│        │                   └───┬────┘ └────────┘ └───┬────┘
└───────┘        ▼                       │                      │
          ┌──────────────┐               ▼                      ▼
          │domain/       │    ┌────────────────────┐  ┌──────────────┐
          │ir_v2, enums, │    │text_normalizer,    │  │screen_number_│
          │validation,   │    │multilingual_text_  │  │allocator     │
          │legacy_adapter│    │builder, tia_text_  │  └──────────────┘
          └──────┬───────┘    │sanitizer           │
                 │            └────────────────────┘
    ┌────────────┼────────────┐
    ▼            ▼            ▼
┌────────┐ ┌──────────┐ ┌──────────────┐
│backends│ │planners  │ │capabilities/ │
│classic/│ │deployment│ │services/     │
│unified/│ │_planner  │ │references/   │
└────────┘ └──────────┘ └──────────────┘
```

---

## 七、文件清单

```
backend/
├── __init__.py
├── config_manager.py              # YAML 配置管理
├── hmi_ir.py                      # IR 校验/归一化/布局优化
├── import_engine.py               # TIA 导入引擎 (5层管线终端)
├── llm_client.py                  # LLM 流式客户端
├── mimo_client.py                 # MiMo 视觉 API 客户端
├── multilingual_text_builder.py   # MultilingualText DOM 构建器
├── openness_manager.py            # Openness Façade (核心)
├── pipeline_orchestrator.py       # SSE 流水线编排
├── preview_renderer.py            # IR → PNG 预览渲染
├── prompts.py                     # LLM 系统提示词
├── review_prompts.py              # MiMo 审查任务提示词
├── screen_number_allocator.py     # Screen Number 分配器
├── simaticml_generator.py         # SimaticML XML 生成器
├── template_xml_generator.py      # 模板 XML 改写器
├── text_normalizer.py             # 文本安全清洗器
├── tia_text_sanitizer.py          # 兼容层
├── variable_engine.py             # 变量引擎
├── xml_validator.py               # XML 校验闸门
│
├── backends/                      # 后端执行器
│   ├── __init__.py
│   ├── base.py                    # 抽象基类
│   ├── classic/                   # Basic/Comfort 经典后端
│   │   ├── __init__.py
│   │   ├── basic_backend.py
│   │   ├── comfort_backend.py
│   │   ├── classic_screen_reference_rewriter.py
│   │   ├── classic_validator.py
│   │   ├── common.py
│   │   ├── dynamic_xml_builder.py
│   │   ├── function_list_builder.py
│   │   ├── link_resolver.py
│   │   ├── screen_xml_builder.py
│   │   ├── tag_xml_builder.py
│   │   ├── vbs_builder.py
│   │   ├── xml_fragment_catalog.py
│   │   └── xml_id_registry.py
│   └── unified/                   # WinCC Unified 后端
│       ├── __init__.py
│       ├── binding_builder.py
│       ├── event_builder.py
│       ├── js_builder.py
│       ├── property_builder.py
│       ├── reflection_adapter.py
│       ├── screen_builder.py
│       ├── tag_builder.py
│       └── unified_backend.py
│
├── capabilities/                  # 能力矩阵
│   ├── __init__.py
│   ├── capability_service.py
│   └── static_matrix.py
│
├── domain/                        # 领域模型 (V3.0)
│   ├── __init__.py
│   ├── deployment_plan.py
│   ├── deployment_result.py
│   ├── diagnostics.py
│   ├── enums.py
│   ├── ir_v2.py
│   ├── legacy_adapter.py
│   └── validation.py
│
├── openness/                      # Openness 子模块
│   ├── __init__.py
│   ├── assembly_loader.py
│   ├── classic_executor.py
│   ├── compiler.py
│   ├── device_discovery.py
│   ├── diagnostics_utils.py
│   ├── exception_mapper.py
│   ├── object_query_service.py
│   ├── runtime_contract.py
│   ├── session_manager.py
│   └── unified_executor.py
│
├── planners/                      # 部署计划
│   ├── __init__.py
│   ├── dependency_graph.py
│   └── deployment_planner.py
│
├── references/                    # 引用目录
│   ├── __init__.py
│   └── catalog_service.py
│
└── services/                      # 服务层
    ├── __init__.py
    ├── deployment_service.py
    └── verification_service.py
```

**总计：60+ 个 Python 文件，覆盖从 AI 生成到工业部署的完整链路。**

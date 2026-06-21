# Siemens HMI Assistant 后端架构完整分析

## 目录

1. [项目概述](#1-项目概述)
2. [总体架构](#2-总体架构)
3. [模块分层详解](#3-模块分层详解)
4. [调用关系图](#4-调用关系图)
5. [数据流分析](#5-数据流分析)
6. [关键设计模式](#6-关键设计模式)
7. [各模块代码规模统计](#7-各模块代码规模统计)
8. [核心流程时序](#8-核心流程时序)

---

## 1. 项目概述

### 1.1 项目定位

Siemens HMI Assistant 是一个基于人工智能的自然语言驱动的 HMI（人机界面）画面生成辅助工具。它面向西门子 TIA Portal 工程平台，将用户的中文自然语言需求转化为可直接导入 TIA Portal 的 HMI 画面，覆盖从需求描述到最终部署的完整链路。

### 1.2 核心解决的问题

- **传统 HMI 开发效率低**：工程师需要手动拖拽控件、配置变量绑定、编写脚本、生成 XML，工序繁琐
- **跨平台兼容性复杂**：TIA Portal 支持 Basic Panel、Comfort Panel、WinCC Unified 等多种 HMI 家族，每种家族的 API、XML 格式、能力约束各不相同
- **变量绑定繁琐**：画面控件（按钮、指示灯、IO 域等）需要与 PLC 过程变量进行绑定，手工操作易出错且难以维护
- **Openness API 调用门槛高**：TIA Portal Openness 基于 .NET 原生接口，通过 pythonnet/CLR 调用时类型反射、异常处理、方法重载解析等均需额外适配层

### 1.3 整体能力

| 能力维度 | 说明 |
|---------|------|
| AI 画面生成 | 通过 LLM（DeepSeek / OpenAI 兼容 API）将自然语言需求转化为结构化的 HMI 中间表示（IR） |
| 视觉评审 | 可选 MiMo 多模态模型对渲染画面进行可视化审核，支持多轮修正 |
| XML 生成 | 支持 SimaticML（标准 TIA 导入格式）和模板 XML（基于已有画面克隆）两种路线 |
| 变量引擎 | 自动识别控件类型，推断变量名、数据类型、PLC 地址映射，生成完整的 Tag 表和 VBS 脚本 |
| TIA Portal 集成 | 通过西门子 Openness API（.NET / pythonnet）实现连接、导入、编译、验证全流程 |
| 后端工厂 | 根据 HMI 家族自动选择对应后端（Basic / Comfort / Unified），统一部署管线 |
| 部署管线 | V3 统一部署管线：验证 -> 规划 -> 执行 -> 验证 -> 编译，状态机驱动 |

### 1.4 技术栈

| 技术 | 用途 |
|------|------|
| Python 3.10 | 后端运行时 |
| Flask | Web 框架，提供 REST API + SSE 流式响应 |
| Flask-CORS | 跨域支持 |
| Pydantic v2 | IR V2 领域模型定义与验证 |
| Pillow | 画面预览渲染（PNG） |
| pythonnet / CLR | .NET 互操作，调用西门子 Openness API |
| LLM API | DeepSeek / OpenAI 兼容 API（/chat/completions） |
| MiMo API | 多模态视觉分析（画面评审与参考图分析） |

---

## 2. 总体架构

### 2.1 分层架构图

```
================================================================================
=                         SIEMENS HMI ASSISTANT 后端架构                        =
================================================================================

   ┌─────────────────────────────────────────────────────────────────────┐
   │                         L1: 接入层 (API)                           │
   │  ┌───────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────────┐   │
   │  │ Page路由  │ │ Config  │ │ Generate│ │  Openness API     │   │
   │  │  GET /    │ │ API     │ │ SSE     │ │  /api/openness/*   │   │
   │  └───────────┘ └──────────┘ └──────────┘ └───────────────────┘   │
   │  ┌───────────┐ ┌──────────┐ ┌────────────────────────────────┐   │
   │  │ Build API │ │ HMI API │ │   Debug API                    │   │
   │  │ /api/build│ │ /api/hmi│ │   /api/hmi/debug/import-tag    │   │
   │  └───────────┘ └──────────┘ └────────────────────────────────┘   │
   └─────────────────────────────────────────────────────────────────────┘
                                    │
   ┌─────────────────────────────────────────────────────────────────────┐
   │                     L2: 管线层 (Orchestration)                      │
   │  ┌──────────────────┐  ┌──────────────────┐  ┌───────────────┐    │
   │  │ PipelineOrch.   │  │ DeploymentSvc   │  │ ImportEngine  │    │
   │  │ (AI生成管线)    │  │ (V3部署管线)    │  │ (XML导入管线) │    │
   │  └──────────────────┘  └──────────────────┘  └───────────────┘    │
   └─────────────────────────────────────────────────────────────────────┘
                                    │
   ┌─────────────────────────────────────────────────────────────────────┐
   │                    L3: 领域模型层 (Domain)                          │
   │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐ │
   │  │ ir_v2   │ │ enums    │ │diagnostics│ │deploy_   │ │deploy_  │ │
   │  │HmiProj  │ │(枚举定义)│ │(诊断代码) │ │ment_plan │ │ment_res │ │
   │  │ectSpec  │ │          │ │          │ │          │ │ult      │ │
   │  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └─────────┘ │
   │  ┌──────────┐ ┌──────────┐                                       │
   │  │validation│ │legacy_   │                                       │
   │  │          │ │adapter   │                                       │
   │  └──────────┘ └──────────┘                                       │
   └─────────────────────────────────────────────────────────────────────┘
                                    │
   ┌─────────────────────────────────────────────────────────────────────┐
   │                    L4: 后端层 (Backend / Strategy)                  │
   │  ┌────────────┐  ┌──────────────┐  ┌─────────────────────────┐   │
   │  │ HmiBackend │  │BasicBackend  │  │ ComfortBackend          │   │
   │  │ (抽象基类) │  │(Basic Panel) │  │ (Comfort Panel + VBS)   │   │
   │  └────────────┘  └──────────────┘  └─────────────────────────┘   │
   │  ┌────────────────────────────┐  ┌──────────────────────────┐    │
   │  │ UnifiedBackend             │  │ Classic 子装配器:        │    │
   │  │ (WinCC Unified)            │  │  TagXmlBuilder,          │    │
   │  └────────────────────────────┘  │  ScreenXmlBuilder,       │    │
   │                                  │  DynamicXmlBuilder,      │    │
   │                                  │  FunctionListBuilder,    │    │
   │                                  │  VbsBuilder, ...         │    │
   │                                  └──────────────────────────┘    │
   └─────────────────────────────────────────────────────────────────────┘
                                    │
   ┌─────────────────────────────────────────────────────────────────────┐
   │              L5: Openness 层 (.NET 互操作 / TIA Portal)             │
   │  ┌─────────────┐ ┌──────────────┐ ┌──────────┐ ┌──────────────┐  │
   │  │OpennessMgr  │ │SessionMgr   │ │Device    │ │ HmiCompiler  │  │
   │  │(统一门面)   │ │(会话管理)   │ │Discovery │ │ (编译触发)   │  │
   │  └─────────────┘ └──────────────┘ └──────────┘ └──────────────┘  │
   │  ┌──────────────┐ ┌──────────────┐ ┌──────────┐ ┌────────────┐  │
   │  │ClassicExec.  │ │UnifiedExec. │ │Exception │ │Assembly    │  │
   │  │(Classic HMI) │ │(Unified)    │ │Mapper    │ │Loader      │  │
   │  └──────────────┘ └──────────────┘ └──────────┘ └────────────┘  │
   │  ┌──────────────┐ ┌──────────────┐                               │
   │  │ObjectQuerySvc│ │RuntimeCtrt  │                               │
   │  │(只读查询)    │ │(运行时合同)  │                               │
   │  └──────────────┘ └──────────────┘                               │
   └─────────────────────────────────────────────────────────────────────┘
                                    │
   ┌─────────────────────────────────────────────────────────────────────┐
   │         L6: 基础设施层 (AI / XML / 工具)                            │
   │  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐  │
   │  │LLMClient│ │MiMoClient│ │Prompts   │ │Review    │ │Config   │  │
   │  │(AI流式) │ │(视觉分析) │ │(提示词)  │ │Prompts   │ │Manager  │  │
   │  └─────────┘ └──────────┘ └──────────┘ └──────────┘ └─────────┘  │
   │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐ │
   │  │Variable  │ │TagBind   │ │SimaticML │ │Template  │ │XmlVali- │ │
   │  │Engine    │ │Normalizer│ │Generator │ │XmlGen    │ │dator    │ │
   │  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └─────────┘ │
   │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐    │
   │  │Text     │ │MultiLin │ │Screen    │ │PreviewRenderer │    │
   │  │Normalizer│ │gualText │ │NumberAll │ │(Pillow渲染)     │    │
   │  │          │ │Builder  │ │ocator    │ │                  │    │
   │  └──────────┘ └──────────┘ └──────────┘ └──────────────────┘    │
   └─────────────────────────────────────────────────────────────────────┘
```

### 2.2 整体数据流概览

```
用户请求 (Web/API)
    │
    ▼
┌──────────────────────────────────────────┐
│           Flask 路由分发 (app.py)         │
│  根据 path + method 分派到对应 handler     │
└──────────────────────────────────────────┘
    │
    ├─ /api/generate ────────────────────┐
    │   AI 生成管线                      │
    │   1. 构建 messages (prompts)        │
    │   2. LLM 流式生成 IR (JSON)         │
    │   3. IR 验证 + 缩放 + 清洗          │
    │   4. VariableEngine 变量绑定         │
    │   5. (可选) MiMo 视觉评审循环        │
    │   6. 返回最终 IR + 绑定信息          │
    └─────────────────────────────────────┘
    │
    ├─ /api/build ───────────────────────┐
    │   XML 生成管线                      │
    │   1. IR 提取 + 验证                 │
    │   2. VariableEngine 变量绑定         │
    │   3. SimaticML XML 生成              │
    │   4. 写入 .xml + .json 文件          │
    │   5. 返回预览数据                    │
    └─────────────────────────────────────┘
    │
    ├─ /api/hmi/deploy ─────────────────┐
    │   V3 统一部署管线                   │
    │   1. validate (IR V2 校验)          │
    │   2. BackendFactory (选后端)        │
    │   3. build_plan (生成计划)           │
    │   4. execute (执行步骤)              │
    │   5. verify (后置验证)               │
    │   6. compile (触发编译)             │
    └─────────────────────────────────────┘
    │
    ├─ /api/openness/import ────────────┐
    │   TIA 导入管线                      │
    │   1. IR + mode 路由决策             │
    │   2. unified_direct / classic_     │
    │      template_xml / simaticml      │
    │   3. 预处理 (TextNormalizer ->      │
    │      MultilingualTextBuilder ->     │
    │      ScreenNumberAllocator ->       │
    │      XmlValidator)                  │
    │   4. Screens.Import 导入 TIA       │
    └─────────────────────────────────────┘
    │
    └─ /api/openness/sync-tags ─────────┐
        Tag 同步管线                      │
        1. 检测 HMI 家族                  │
        2. 解析 Tag 容器路径              │
        3. 区分已有/新增 Tag              │
        4. Classic: XML + Import          │
           Unified: create_tags           │
        5. 后置验证                       │
        └─────────────────────────────────┘
```

---

## 3. 模块分层详解

### 3.1 接入层 (API / app.py)

**文件**: `app.py` (1097 行)

**职责**: Flask 应用主入口，注册所有 HTTP 路由、CORS 配置、SSE 流式响应支持。

**路由汇总**:

| 分组 | 路由 | 方法 | 说明 |
|------|------|------|------|
| 页面 | `/` | GET | 前端 SPA 主页 (index.html) |
| 配置 | `/api/config` | GET/POST | 读取/保存结构化配置 |
| 配置 | `/api/config/raw` | POST | 保存原始 YAML 配置 |
| AI 生成 | `/api/generate` | POST | 流式 AI 生成 HMI 画面 IR (SSE) |
| AI 生成 | `/api/generate/with_review` | POST | 多阶段管线：AI 生成 + MiMo 视觉评审 |
| 构建 | `/api/build` | POST | IR 验证 -> 变量绑定 -> XML 生成 -> 写盘 |
| 构建 | `/api/build/template-xml` | POST | 基于模板 XML 重写生成 |
| 构建 | `/api/build/template-v4` | POST | V4 模板管线（克隆 + 变量替换） |
| Openness | `/api/openness/diagnose` | GET | 诊断 Openness 环境 |
| Openness | `/api/openness/status` | GET | TIA Portal 连接状态 |
| Openness | `/api/openness/connect` | POST | 连接 TIA Portal |
| Openness | `/api/openness/disconnect` | POST | 断开 TIA Portal |
| Openness | `/api/openness/export-reference` | POST | 导出参考画面 XML |
| Openness | `/api/openness/capabilities` | GET | HMI 设备能力信息 |
| Openness | `/api/openness/export-template` | POST | 导出模板 XML |
| Openness | `/api/openness/import` | POST | 导入画面到 TIA Portal |
| Openness | `/api/openness/sync-tags` | POST | 同步 Tag 到 TIA |
| HMI | `/api/hmi/plan` | POST | 构建部署计划（空跑） |
| HMI | `/api/hmi/capabilities` | GET | 查询 HMI 设备能力矩阵 |
| HMI | `/api/hmi/runtime-metadata` | GET | 运行时元数据 |
| HMI | `/api/hmi/validate` | POST | 验证 HmiProjectSpec |
| HMI | `/api/hmi/summary` | POST | 生成部署总结报告 |
| HMI | `/api/hmi/deploy` | POST | 执行 V3 统一部署管线 |
| HMI | `/api/hmi/verify` | POST | 后置部署验证 |
| HMI | `/api/hmi/compile` | POST | 触发 HMI 编译 |
| HMI | `/api/hmi/debug/import-tag` | POST | 独立 Tag 导入诊断 |

**导入依赖**:

```
backend.config_manager
backend.prompts
backend.llm_client
backend.hmi_ir
backend.simaticml_generator
backend.openness_manager
backend.openness.classic_executor
backend.openness.diagnostics_utils
backend.template_xml_generator
backend.pipeline_orchestrator
backend.variable_engine
backend.domain.ir_v2
backend.domain.deployment_plan
backend.planners.deployment_planner
backend.capabilities.capability_service
backend.domain.enums
backend.services.deployment_service
backend.generation_summary
backend.openness.device_discovery
backend.openness.compiler
pdfplumber
```

---

### 3.2 配置管理 (Config Manager)

**文件**: `backend/config_manager.py` (141 行)

**说明**: 纯函数模块（无类），负责 YAML 配置文件的读写和深层合并。

**核心函数**:

| 函数 | 签名 | 说明 |
|------|------|------|
| `load_config()` | `() -> dict` | 从 `config.yaml` 加载配置，与 `DEFAULT_CONFIG` 深层合并 |
| `save_config(new_config)` | `(dict) -> dict` | 保存结构化配置（保留未知键） |
| `save_raw_yaml(text)` | `(str) -> dict` | 直接保存原始 YAML 文本并加载验证 |
| `get_raw_yaml()` | `() -> str` | 读取 `config.yaml` 原始文本 |
| `_deep_merge(base, override)` | `(dict, dict) -> dict` | 递归深层合并两个字典 |

**配置项分组**:

| 分组 | 关键键 | 说明 |
|------|--------|------|
| `llm.*` | `active_provider`, `thinking_depth`, `stream`, `providers` | LLM 提供商配置（DeepSeek / OpenAI 兼容） |
| `openness.*` | `tia_version`, `dll_path`, `project_path`, `hmi_device`, `generation_mode` | TIA Portal 连接与应用配置 |
| `openness.classic_template.*` | `enabled`, `template_screen_name`, `template_xml_path`, `import_option` | Classic 模板模式 |
| `openness.unified_direct.*` | `enabled`, `update_existing_screen`, `unsupported_object_policy` | Unified 直连模式 |
| `hmi_defaults.*` | `resolution`, `hmi_type`, `background_color`, `font_family` | HMI 默认值 |
| `mimo.*` | `enabled`, `api_key`, `base_url`, `model`, `max_iterations` | MiMo 多模态视觉评审配置 |
| `server.*` | `host`, `port`, `debug` | Flask 服务器配置 |
| `output.*` | `export_dir`, `encoding` | 输出配置 |

---

### 3.3 管线编排层 (Pipeline Orchestrator)

**文件**: `backend/pipeline_orchestrator.py` (353 行)

**说明**: 纯函数模块，编排 AI 生成 + 视觉评审的多阶段管线。

**核心函数**:

| 函数 | 可见性 | 签名 | 说明 |
|------|--------|------|------|
| `run_pipeline` | public | `(requirement, extra_text, uploaded_images, config) -> Generator[Tuple[str, Any]]` | 主入口：多阶段生成管线，产出 SSE 事件元组 |
| `_target_resolution_from_config` | private | `(config) -> str` | 从配置链提取目标分辨率 |
| `_adapt_ir_to_target_resolution` | private | `(ir, config) -> dict` | 将 IR 缩放到目标 HMI 坐标系 |
| `_analyze_uploaded_images` | private | `(images, requirement, mimo_cfg) -> str` | 通过 MiMo 分析最多 3 张参考图 |
| `_safe_review` | private | `(ir, mimo_cfg) -> dict` | 渲染 IR 为 PNG，调用 MiMo 视觉评审 |
| `_summarize_review_for_sse` | private | `(review_result) -> dict` | 压缩评审结果为前端友好格式 |

**管线步骤 (13 步)**:

```
 Step 1:  pipeline_start (发送 max_iterations)
    │
 Step 2:  [可选] image_analysis_start + image_analysis_result
    │         上传参考图时触发 MiMo 分析
    │
 Step 3:  generate_start (requirement + extra_text → LLM)
    │
 Step 4:  [流式] thinking / content / error (LLM 响应令牌流)
    │
 Step 5:  parsed_ok / parse_warn (JSON 提取)
    │
 Step 6:  IR 验证 (validate_ir), 失败则 error + pipeline_done
    │
 Step 7:  IR 分辨率缩放 (_adapt_ir_to_target_resolution)
    │
 Step 8:  IR 文本清洗 (sanitize_ir_text_fields)
    │
 Step 9:  variable_bind (VariableEngine.generate → 变量绑定)
    │
 Step 10: [门控] MiMo 未启用 → pipeline_done 直接返回
    │
 Step 11: [循环开始] review_start → rendering → analyzing → review_result
    │          MiMo 视觉评审
    │
 Step 12: [门控] 通过 → review_pass + pipeline_done
    │          超限 → pipeline_done (passed=False)
    │
 Step 13: [再生] regenerate_start → LLM → 解析 → 验证 → 缩放 → 清洗 → 绑定 → 回到 Step 11
```

**依赖关系**:

| 依赖模块 | 符号 | 用途 |
|----------|------|------|
| `.llm_client` | `LLMClient`, `extract_json` | LLM 流式调用 |
| `.hmi_ir` | `validate_ir`, `IRValidationError`, `scale_ir_to_resolution` | IR 验证与缩放 |
| `.prompts` | `build_messages` | 构建 LLM 消息数组 |
| `.preview_renderer` | `render_ir_to_png` | 渲染 IR 为 PNG |
| `.mimo_client` | `analyze_with_mimo` | MiMo 视觉分析 |
| `.review_prompts` | `HMI_REVIEW_TASK`, `IMAGE_ANALYSIS_TASK` | 评审提示词 |
| `.tia_text_sanitizer` | `sanitize_ir_text_fields` | 文本清洗 |
| `.variable_engine` | `VariableEngine` | 变量绑定 |

---

### 3.4 领域模型层 (Domain)

**目录**: `backend/domain/`

#### 3.4.1 IR V2 模型 (`backend/domain/ir_v2.py`, 392 行)

使用 Pydantic v2 定义的完整 HMI 中间表示（IR）语义模型。

| 类 | 说明 |
|----|------|
| `DeploymentPolicies` | 部署策略（冲突处理、不支持特性、缺失依赖） |
| `ProjectMetadata` | 项目元数据（名称、描述、版本、作者等） |
| `TargetSpec` | 目标设备规格（HMI 家族、分辨率、型号等） |
| `ConnectionSpec` | 连接定义（PLC 连接、通信参数） |
| `TagSpec` | 变量定义（名称、数据类型、地址、方向、范围） |
| `GeometrySpec` | 控件几何信息（X、Y、宽度、高度、Z-order） |
| `BindingSpec` | 动态绑定（绑定类型、目标属性、关联 Tag、配置参数） |
| `ActionSpec` | 动作定义（动作类型、目标、参数） |
| `EventSpec` | 事件定义（触发事件、动作列表） |
| `ScriptSpec` | 脚本定义（语言、代码内容、安全扫描结果） |
| `ResourceSpec` | 资源定义（图片、字体等外部资源引用） |
| `ScreenItemSpec` | 画面项规格（类型、几何、外观、绑定、事件） |
| `ScreenSpec` | 画面规格（名称、编号、尺寸、背景、项列表） |
| `HmiProjectSpec` | 顶层规格（项目元数据、目标、连接、Tag、脚本、资源、画面列表） |

#### 3.4.2 枚举定义 (`backend/domain/enums.py`, 188 行)

| 枚举 | 说明 |
|------|------|
| `HmiFamily` | HMI 面板家族（BASIC / COMFORT / UNIFIED / CLASSIC / UNKNOWN） |
| `TagScope` | 变量作用域（GLOBAL / LOCAL / EXTERNAL） |
| `ConnectionKind` | 连接类型（PLC / HMI / OPC_UA 等） |
| `ScreenItemType` | 画面项类型（BUTTON / INDICATOR / IO_FIELD / TEXT 等） |
| `BindingKind` | 绑定类型（DIRECT / STATE / RANGE / FLASH / EXPRESSION） |
| `SemanticEvent` | 语义事件（CLICK / PRESS / RELEASE / CHANGE 等） |
| `SemanticActionType` | 语义动作（SET_BIT / RESET_BIT / TOGGLE_BIT / SET_VALUE / ACTIVATE_SCREEN 等） |
| `ScriptLanguage` | 脚本语言（VBS / JAVASCRIPT） |
| `DiagnosticSeverity` | 诊断严重级别（INFO / WARNING / ERROR / CRITICAL） |
| `DeploymentPhase` | 部署阶段（VALIDATE / PLAN / EXECUTE / VERIFY / COMPILE） |
| `DeploymentStatus` | 部署状态（DRY_RUN / NOT_CONNECTED / BLOCKED / DEPLOYING / DEPLOYED / FAILED 等） |
| `ButtonBehavior` | 按钮行为（MOMENTARY / TOGGLE / SET / RESET） |
| `IndicatorMode` | 指示灯模式（STATUS / ALARM / CUSTOM） |
| `TagDirection` | 变量方向（INPUT / OUTPUT / INOUT） |

#### 3.4.3 诊断模型 (`backend/domain/diagnostics.py`, 171 行)

| 类 | 说明 |
|----|------|
| `Diagnostic` | 结构化诊断：code、severity、phase、object_ref、message、details、remediation |
| `DiagnosticCodes` | 静态常量类，聚合所有标准错误码（16 个分组，覆盖能力、依赖、Classic XML、Unified、脚本、导入/编译、验证、模板、Tag 导入等全场景） |

#### 3.4.4 部署计划 (`backend/domain/deployment_plan.py`, 59 行)

| 类 | 说明 |
|----|------|
| `DeploymentStep` | 单个部署步骤（操作类型、阶段、目标、依赖、载荷、回滚信息） |
| `DeploymentPlan` | 部署计划（有序步骤聚合 + 目标规格 + 设备能力 + 诊断 + 空跑标记） |

#### 3.4.5 部署结果 (`backend/domain/deployment_result.py`, 162 行)

| 类 | 说明 |
|----|------|
| `DeploymentResult` | 顶层部署结果（状态、统计、诊断、警告、编译信息） |
| `CompileResult` | 编译结果（是否成功、消息列表） |
| `VerificationResult` | 验证结果（Tag / 画面 / 事件 / 绑定 / 脚本各维度检查） |
| `ActualProjectSnapshot` | 真实 TIA 项目快照（Tag、画面项、脚本的快照类） |

#### 3.4.6 IR 验证 (`backend/domain/validation.py`, 411 行)

| 类/函数 | 说明 |
|---------|------|
| `IrV2ValidationError` | IR V2 验证异常 |
| `validate_ir_v2()` | 交叉引用和唯一性校验（schema_version、画面、Tag、脚本、资源、连接、绑定、事件） |
| `validate_template_binding_requirements()` | 按钮/指示器的绑定要求验证 |
| `validate_or_raise()` | 封装校验逻辑，出错即抛异常 |

#### 3.4.7 遗留适配器 (`backend/domain/legacy_adapter.py`, 536 行)

| 类 | 说明 |
|----|------|
| `LegacyIrAdapter` | 将旧版 V2.3 IR dict 转换为当前 HmiProjectSpec（IR V2）格式。映射旧对象类型、事件、Tag 模式。未知字段保留在 metadata.extra 中 |

**领域层依赖关系**: 领域模型层零外部依赖（仅依赖 stdlib + Pydantic），是架构中最纯粹的模块。

---

### 3.5 后端层 (Backend / Strategy)

**目录**: `backend/backends/`

#### 3.5.1 抽象基类 (`backend/backends/base.py`, 31 行)

| 方法 | 说明 |
|------|------|
| `supports(target)` | 检查后端是否支持指定目标 |
| `build_plan(spec, capabilities)` | 构建部署计划 |
| `execute(plan, context)` | 执行部署步骤 |
| `verify(context)` | 后置部署验证 |

#### 3.5.2 Basic Backend (`backend/backends/classic/basic_backend.py`, 736 行)

**职责**: Basic Panel 部署后端。禁止 VBS 脚本。

**核心流程**:
1. Tag XML 生成 -> Tag 导入 DefaultTagTable
2. TextList XML 生成
3. 画面 XML 重写（基于模板参考）
4. 模板泄漏检查
5. 画面导入
6. 编译
7. 6 项验收验证

**依赖**:
- `classic/common.py` (ClassicCommon 汇编器)
- `classic/tag_xml_builder.py` (TagXmlBuilder)
- `classic/screen_xml_builder.py` (ScreenXmlBuilder)
- `openness/classic_executor.py` (ClassicOpennessExecutor)
- `xml_validator.py` (XmlValidator)

#### 3.5.3 Comfort Backend (`backend/backends/classic/comfort_backend.py`, 368 行)

**职责**: Comfort Panel 部署后端。支持 VBS 脚本生成与安全扫描。

**核心流程**: 与 Basic Backend 类似，增加 VBS 脚本构建和安全性检查。

**依赖**:
- `classic/common.py` (ClassicCommon)
- `classic/vbs_builder.py` (VbsBuilder)
- `openness/classic_executor.py`

#### 3.5.4 Classic Common 汇编器 (`backend/backends/classic/common.py`, 107 行)

**职责**: 组合 Classic 子构建器为统一调用接口。

| 组件 | 说明 |
|------|------|
| `TagXmlBuilder` | PLC SW.Tag XML 生成（单/批量导出） |
| `HmiTagXmlBuilder` | HMI 侧 Tag XML 生成（TagComposition.Import） |
| `ScreenXmlBuilder` | Classic 画面 XML 生成 |
| `FunctionListBuilder` | 语义动作->FunctionList XML 映射 |
| `DynamicXmlBuilder` | BindingSpec->动态属性 XML 映射 |
| `XmlIdRegistry` | 确定性 XML ID 生成（SHA-256） |
| `LinkResolver` | 内部引用解析（ProcessTag、TagName、ScreenName） |
| `ClassicValidator` | 预导入 XML 验证 |
| `ClassicScreenReferenceRewriter` | 画面 XML 变量引用重写 |

#### 3.5.5 Classic 子装配器

| 文件 | 行数 | 核心类 | 职责 |
|------|------|--------|------|
| `tag_xml_builder.py` | 520 | `TagXmlBuilder`, `HmiTagXmlBuilder` | PLC/HMI Tag XML 生成，支持金模板 |
| `screen_xml_builder.py` | 254 | `ScreenXmlBuilder` | 画面 XML 生成（Header、Footer、Items、MultilingualText、事件） |
| `dynamic_xml_builder.py` | 130 | `DynamicXmlBuilder` | 动态绑定 XML 片段（直连、状态映射、范围动画、线性缩放、闪烁、表达式） |
| `function_list_builder.py` | 81 | `FunctionListBuilder` | FunctionList XML 生成（SetBit、ResetBit、ToggleBit、SetValue、ActivateScreen 等） |
| `link_resolver.py` | 111 | `LinkResolver` | 内部引用解析与重写 |
| `vbs_builder.py` | 90 | `VbsBuilder` | VBS 脚本生成 + 禁止模式黑名单扫描 |
| `xml_fragment_catalog.py` | 134 | `CatalogManifest`, `XmlFragmentCatalog` | XML 片段目录系统（YAML 清单 + 片段检索） |
| `xml_id_registry.py` | 68 | `XmlIdRegistry` | 确定性 XML ID（SHA-256 哈希 + 种子） |
| `classic_validator.py` | 122 | `ClassicValidator`, `ClassicValidationResult` | 预导入 XML 验证（命名空间、Screen 元素、ID/名称唯一性） |
| `classic_screen_reference_rewriter.py` | 1029 | `ClassicScreenReferenceRewriter` | 画面 XML 变量引用重写 + 模板泄漏检测 |

#### 3.5.6 Unified Backend (`backend/backends/unified/unified_backend.py`, 305 行)

**职责**: WinCC Unified 部署后端，扩展 HmiBackend。

**核心方法**:
| 方法 | 说明 |
|------|------|
| `supports(target)` | 检查家族是否为 UNIFIED |
| `build_plan(spec, capabilities)` | 通过 DeploymentPlanner 构建计划 |
| `execute(plan, context)` | 部署到 TIA Portal（空跑/未连接/运行时合同检查/Tag/画面/脚本构建 + executor 分发） |
| `verify(context)` | 通过 ObjectQueryService + VerificationService 后置验证 |

#### 3.5.7 Unified 子装配器

| 文件 | 行数 | 核心类 | 职责 |
|------|------|--------|------|
| `tag_builder.py` | 49 | `UnifiedTagBuilder` | 构建 Unified Tag 规格（TagSpec -> Unified 创建字典 + WinCC ML YAML） |
| `screen_builder.py` | 47 | `UnifiedScreenBuilder` | 构建 Unified 画面/画面项规格 |
| `property_builder.py` | 37 | `UnifiedPropertyBuilder` | 静态属性映射（别名解析 + 颜色格式转换） |
| `binding_builder.py` | 46 | `UnifiedBindingBuilder` | 动态绑定规格（BindingKind -> Unified Dynamization 类型映射） |
| `event_builder.py` | 80 | `UnifiedEventBuilder` | 事件处理器规格 + JavaScript 代码生成 |
| `js_builder.py` | 46 | `JsBuilder` | JavaScript 代码生成 + 安全扫描（白名单 API 策略） |
| `reflection_adapter.py` | 96 | `UnifiedReflectionAdapter` | 运行时类型反射与版本适配（语义 -> .NET 名称解析） |

---

### 3.6 Openness 层 (.NET 互操作)

**目录**: `backend/openness/`

#### 3.6.1 OpennessManager (`backend/openness_manager.py`, 2810 行)

**职责**: TIA Portal Openness 统一门面，向后兼容入口。内部委托给模块化子模块。

**关键方法**:

| 方法 | 说明 |
|------|------|
| `diagnose()` | 环境诊断（OS / pythonnet / DLL / TIA 进程 / 就绪状态） |
| `connect()` | 连接 TIA Portal（通过 TiaPortal.GetProcesses().Attach） |
| `disconnect()` | 断开连接（释放 Portal 引用） |
| `get_hmi_capabilities()` | HMI 设备能力查询（类型、家族、推荐模式、画面列表） |
| `sync_tags(tags)` | 家族感知的 Tag 同步（Classic -> XML 导入、Unified -> create_tags） |
| `import_screen(xml_path)` | 导入 SimaticML XML 画面（Screens.Import） |
| `import_screen_xml(xml_path, screen_folder, import_option)` | 导入模板 XML 到 Classic 画面文件夹 |
| `export_reference_screen(screen_name)` | 导出参考画面 XML |
| `export_screen_xml_template(screen_name, export_dir, overwrite)` | 导出模板 XML 到磁盘 |
| `create_unified_screen_from_ir(ir)` | 直接通过 Openness 对象模型创建 Unified 画面（无 XML 中间步骤） |
| `import_or_generate_from_ir(ir, mode)` | 统一入口：HMI 家族检测 -> IR 标准化/验证 -> 变量绑定 -> Tag 同步 -> 路由分发 |
| `_preprocess_xml_for_import(xml_content, hmi_software)` | XML 预处理管线（TextNormalizer -> MultilingualTextBuilder -> ScreenNumberAllocator -> 尺寸对齐 -> 名称冲突检测 -> XmlValidator） |

**同步 Tag 流程**:

```
sync_tags(tags)
  │
  ├─ 1. 前置检查 (self._project 是否已连接)
  │
  ├─ 2. _find_hmi_software() 获取 .NET hmi_software 对象
  │
  ├─ 3. get_hmi_capabilities() 检测 HMI 家族
  │
  ├─ 4. [块] HMI_FAMILY_UNKNOWN -> 返回 Diagnostic ERROR
  │
  ├─ 5. _resolve_hmi_tag_container(sw, hmi_family)
  │     Classic: TagFolder.DefaultTagTable.Tags -> TagFolder.TagTables[0].Tags -> sw.TagTables[0].Tags
  │     Unified: sw.Tags
  │
  ├─ 6. 过滤已有/新增 Tag
  │
  ├─ 7. 家族路由:
  │     ├─ Basic/Comfort/Classic: TagSpec -> HmiTagXmlBuilder.build_batch_tags_xml() -> ClassicOpennessExecutor.import_hmi_tags_safe()
  │     └─ Unified: specs -> UnifiedOpennessExecutor.create_tags()
  │
  └─ 8. [管线内] _verify_hmi_tags_exist() 后置验证
```

#### 3.6.2 模块化子模块

| 文件 | 行数 | 核心类 | 职责 |
|------|------|--------|------|
| `session_manager.py` | 153 | `SessionManager` | 会话生命周期管理（环境诊断、Attach、OpenProject、Disconnect） |
| `device_discovery.py` | 253 | `DeviceDiscovery` | HMI 设备发现（遍历 Device.DeviceItems、类型名启发、型号匹配 KTP/TP） |
| `compiler.py` | 224 | `HmiCompiler` | 编译触发（ICompilable.Compile + CompilerResult.Messages 递归收集） |
| `assembly_loader.py` | 141 | `AssemblyLoader`, `AssemblyMetadata` | Siemens.Engineering.dll 加载与元数据记录 |
| `exception_mapper.py` | 189 | `ExceptionMapper` | .NET 异常 -> 结构化 Diagnostic（模式匹配已知错误类型） |
| `classic_executor.py` | 3441 | `ClassicOpennessExecutor`, `ClassicStepResult`, `ClassicTagImportKind` | Classic HMI Openness 操作执行器（最大文件） |
| `unified_executor.py` | 595 | `UnifiedOpennessExecutor`, `UnifiedStepResult` | Unified HMI Openness 操作执行器 |
| `object_query_service.py` | 585 | `ObjectQueryService` | 只读查询服务（查询 Tag、画面、视图项、事件、脚本） |
| `reflection_utils.py` | 213 | (纯函数) | .NET 反射工具（类型描述、方法检查、重载列表） |
| `runtime_contract.py` | 202 | `RuntimeContract`, `RuntimeProber` | Unified 运行时合同（DLL 反射快照 + 版本缓存） |
| `diagnostics_utils.py` | 235 | (纯函数) | 诊断工具（异常链遍历、.NET 对象描述、XML 结构检查） |

---

### 3.7 基础设施层

#### 3.7.1 AI / LLM 相关

| 文件 | 行数 | 核心类/函数 | 职责 |
|------|------|------------|------|
| `backend/llm_client.py` | 228 | `LLMClient` | OpenAI 兼容流式客户端 /chat/completions。支持 thinking/reasoning 提取、三种深度级别 |
| `backend/mimo_client.py` | 323 | `analyze_with_mimo` (模块级) | MiMo 视觉 API 客户端。图片自动缩放为 data URL，8 种输出模式 |
| `backend/prompts.py` | 419 | `build_messages()`, `SYSTEM_PROMPT`, `IR_SCHEMA_DOC` | HMI IR 生成系统提示词（含少样本示例 + 自检） |
| `backend/review_prompts.py` | 231 | `HMI_REVIEW_TASK`, `IMAGE_ANALYSIS_TASK`, `build_review_feedback_text()` | MiMo 视觉评审和参考图分析提示词 + 西门子标准色板 |

#### 3.7.2 变量 / Tag 引擎

| 文件 | 行数 | 核心类 | 职责 |
|------|------|--------|------|
| `backend/variable_engine.py` | 1161 | `VariableEngine` | HMI 变量引擎：自动绑定生成、按钮行为推断、指示灯模式推断、IO 域类型推断、命名规则（BTN_/MEM_/STS_/LMP_/IO_/SIO_）、PLC 地址四级语义匹配、冲突检测 |
| `backend/tag_binding_normalizer.py` | 579 | (纯函数) | 遗留 IR 的 Tag 绑定规范化（三字段去重、中英文变量名映射） |
| `backend/hmi_ir.py` | 528 | `IRValidationError` | IR 验证/标准化/布局优化（类型检查、坐标默认值、自动补全未注册变量、分辨率缩放、自动布局） |
| `backend/utils/tag_prefix_utils.py` | 60 | (纯函数) | Tag 名前缀工具（剥离/检查/确保 BTN_/MEM_/STS_ 等） |

**VariableEngine 核心逻辑**:

```
VariableEngine.generate(ir) / enrich_to_v2(ir) -> HmiProjectSpec
  │
  ├─ 1. 遍历 IR 画面项，按类型分类:
  │      BUTTON       -> 推断 MOMENTARY / TOGGLE / SET / RESET
  │      INDICATOR    -> 推断 STATUS / ALARM / CUSTOM
  │      IO_FIELD     -> 推断数据类型 (Int / Real / String / Char)
  │      SYMBOLIC_IO  -> 文本列表变量生成
  │
  ├─ 2. 变量命名:
  │      Button       -> BTN_<名称>
  │      Indicator    -> LMP_(STATUS/ALARM) / STS_
  │      IO_FIELD     -> IO_ / SIO_
  │      Memory       -> MEM_
  │      Text         -> TXT_
  │
  ├─ 3. PLC 地址映射 (4 级语义匹配):
  │      精确匹配 tag_name / 前缀匹配 / 类型推断 / 生成占位 pending_mapping
  │
  ├─ 4. 冲突检测:
  │      tag_binding / process_tag / binding.tag 三字段一致性检查
  │      同一变量名不同数据类型冲突
  │
  ├─ 5. 生成 TagSpec 列表 + BindingSpec 列表
  │
  ├─ 6. 生成 VBScript 脚本 (Comfort 目标时)
  │
  └─ 7. 组装为 HmiProjectSpec (或兼容旧 dict 格式)
```

#### 3.7.3 XML 生成器

| 文件 | 行数 | 核心函数 | 职责 |
|------|------|---------|------|
| `backend/simaticml_generator.py` | 701 | `generate_simaticml()` | IR -> SimaticML XML（标准 TIA Portal Screen.Import 格式）。支持 IOField、SymbolicIOField、Button、Indicator/Circle、Text/TextField。可选参考 XML 对齐 |
| `backend/template_xml_generator.py` | 1243 | `generate_from_template_xml()`, `generate_from_template_v4()` | 基于已有模板 XML 重写生成（安全字段替换 / V4 原型克隆 + 变量替换）。支持 IOField、Button、SymbolicIOField、Circle、Ellipse、Rectangle、TextField、Slider、Switch、Gauge |

#### 3.7.4 XML 预处理管线

| 文件 | 行数 | 核心类 | 职责 |
|------|------|--------|------|
| `backend/text_normalizer.py` | 273 | `TextNormalizer` | 层 1: HTML 实体解码、HTML 标签移除、控制字符清除、空白规范化 |
| `backend/multilingual_text_builder.py` | 381 | `MultilingualTextBuilder` | 层 2: MultilingualText DOM 构建/修复（支持 V16/Comfort 富文本 body/p 结构） |
| `backend/screen_number_allocator.py` | 170 | `ScreenNumberAllocator` | 层 3: 画面编号分配/去重/移除 Number 节点 |
| `backend/xml_validator.py` | 864 | `XmlValidator`, `ValidationResult` | 层 4: 5 项预导入检查 + Tag/Block XML 类型检测 |

#### 3.7.5 模板系统 (`backend/template/`)

| 文件 | 行数 | 核心类 | 职责 |
|------|------|--------|------|
| `template_profile.py` | 77 | `ControlPrototype`, `TemplateProfile` | 数据模型层（TagReference、EventPattern、BindingPattern、ControlPrototype） |
| `prototype_extractor.py` | 351 | `prototype_extract_from_xml()` | 主编排器：解析模板 XML -> 控制分类 -> 行为推断 -> TemplateProfile |
| `binding_pattern_extractor.py` | 127 | (纯函数) | 从控件 XML 提取动态绑定模式 |
| `event_pattern_extractor.py` | 102 | (纯函数) | 从控件 XML 提取事件模式 |
| `prototype_registry.py` | 210 | `PrototypeRegistry` | IR 画面项 -> 最佳原型匹配（template_ref / type+behavior / type+mode / name / default） |
| `xml_rewrite_rules.py` | 231 | `RewritePlan` | 克隆+替换方案（名称/文本/几何/Tag 引用重写 + ID 分配） |
| `template_binding_validator.py` | 191 | (纯函数) | 生成后 XML 验证（重复名称、残留占位符、空 TagName/事件/动态引用） |
| `xml_utils.py` | 256 | (纯函数) | 底层 XML 工具（命名空间处理、ID 生成、节点深拷贝） |

#### 3.7.6 其他基础设施

| 文件 | 行数 | 核心类 | 职责 |
|------|------|--------|------|
| `backend/preview_renderer.py` | 299 | (纯函数) | Pillow 画面预览渲染（5 种对象类型 -> PNG） |
| `backend/generation_summary.py` | 213 | (纯函数) | V4 生成总结报告构建（AI 理解、Tag 表、绑定表、部署结果） |
| `backend/tia_text_sanitizer.py` | 143 | (纯函数) | 兼容 shim（委托给 TextNormalizer / MultilingualTextBuilder / XmlValidator） |
| `backend/import_engine.py` | 408 | `ImportEngine`, `ImportResult` | 终端导入执行器（预处理管线 + Screens.Import + 编译/保存） |

---

### 3.8 服务 / 规划 / 能力层

#### 3.8.1 部署服务 (`backend/services/deployment_service.py`, 945 行)

**核心类**:

| 类 | 说明 |
|----|------|
| `RuntimeContext` | 运行时上下文（project、hmi_software、device_discovery、HMI 家族、配置） |
| `BackendFactory` | 后端工厂（根据 HMI 家族选择 BasicBackend / ComfortBackend / UnifiedBackend） |
| `DeploymentService` | V3 统一部署服务：validate -> plan -> execute -> compile -> verify |

**状态机**:

```
DRY_RUN → NOT_CONNECTED → BLOCKED → DEPLOYING → DEPLOYED / FAILED / VERIFICATION_FAILED / COMPILE_FAILED
```

**核心方法**:

| 方法 | 说明 |
|------|------|
| `validate(spec, config)` | 验证 + 能力检查 + Tag 绑定门控 |
| `plan(spec, config, dry_run)` | 构建 DeploymentPlan |
| `deploy(spec, config)` | 完整部署管线：validate -> BackendFactory -> build_plan -> execute -> compile -> verify |
| `deploy_legacy_ir(ir, config)` | 遗留 IR 兼容部署（enrich_to_v2 -> deploy） |
| `execute(plan, context)` | 按步骤执行部署 |
| `_check_catalog(config)` | 金模板目录检查 |

#### 3.8.2 验证服务 (`backend/services/verification_service.py`, 467 行)

| 类 | 说明 |
|----|------|
| `VerificationService` | 语义后置验证：Tag、画面、事件、绑定、脚本全维度验证。V3.2 增强：按钮事件变量验证、动态绑定验证、模板残留检查、Tag 表成员验证 |

#### 3.8.3 部署规划器 (`backend/planners/deployment_planner.py`, 299 行)

| 类 | 说明 |
|----|------|
| `DeploymentPlanner` | 从 HmiProjectSpec 构建有序部署计划（P00-P90 步骤）、交叉引用验证、能力检查、诊断汇总 |

#### 3.8.4 能力服务 (`backend/capabilities/capability_service.py`, 222 行)

| 类 | 说明 |
|----|------|
| `CapabilitySet` | 能力集合（合并静态矩阵 + 运行时能力） |
| `CapabilityService` | 能力解析与项目验证（16 个能力类别，覆盖屏幕导入、Tag、脚本、动态绑定等） |

#### 3.8.5 静态能力矩阵 (`backend/capabilities/static_matrix.py`, 65 行)

| 类 | 说明 |
|----|------|
| `CapabilityEntry` | 能力条目（support_level: yes/no/limited/device） |
| `get_capability()` | 按 HMI 家族 + 能力类别查找 |

#### 3.8.6 Tag 绑定验证门控 (`backend/validation/tag_binding_gate.py`, 250 行)

| 函数 | 说明 |
|------|------|
| `validate_project_tag_bindings()` | Tag 完整性校验（唯一性、引用存在性、类型匹配、外部 pending_mapping） |
| `raise_if_project_tag_bindings_invalid()` | 阻塞部署的抛异常版本 |

#### 3.8.7 依赖图 (`backend/planners/dependency_graph.py`, 105 行)

| 类 | 说明 |
|----|------|
| `DependencyGraph` | 简单 DAG（拓扑排序，确保连接 -> Tag -> 画面顺序） |

#### 3.8.8 目录服务 (`backend/references/catalog_service.py`, 53 行)

| 类 | 说明 |
|----|------|
| `CatalogService` | 金模板目录管理（按 TIA 版本/家族/设备查找 manifest，验证合约） |

---

### 3.9 调试工具 (`backend/debug/`)

| 文件 | 行数 | 说明 |
|------|------|------|
| `tag_pipeline_debug.py` | 226 | Tag 导入管线调试探针。执行外部引用验证后执行受控导入探测，返回详细诊断（异常链、.NET 对象描述、XML 结构检查） |

---

## 4. 调用关系图

### 4.1 整体调用关系 (简化)

```
                    ┌─────────────┐
                    │   用户请求   │
                    └──────┬──────┘
                           │ HTTP / SSE
                           ▼
                    ┌─────────────┐
                    │   app.py    │
                    │  (路由分发)  │
                    └──┬──┬──┬──┬─┘
                       │  │  │  │
         ┌─────────────┘  │  │  └──────────────┐
         ▼                ▼  ▼                  ▼
  ┌────────────┐   ┌──────────────┐   ┌──────────────────┐
  │ Pipeline   │   │DeploymentSvc │   │ OpennessManager   │
  │ Orchestr.  │   │(V3 部署管线) │   │ (TIA 操作门面)    │
  └─────┬──────┘   └──────┬───────┘   └──┬──┬──┬──┬──┬───┘
        │                 │              │  │  │  │  │
        ▼                 ▼              ▼  ▼  ▼  ▼  ▼
  ┌────────────┐   ┌──────────────┐   ┌──────────────────┐
  │ LLMClient  │   │ BackendFactory│  │SessionMgr        │
  │ MiMoClient │   │   │            │  │DeviceDiscovery   │
  │ Prompts    │   │   ▼            │  │HmiCompiler       │
  │ Review     │   │BasicBackend   │  │ClassicExecutor   │
  │ Prompts    │   │ComfortBackend │  │UnifiedExecutor   │
  │ Variable   │   │UnifiedBackend │  │ExceptionMapper   │
  │ Engine     │   └──────────────┘  │AssemblyLoader    │
  │ hmi_ir     │                     │ObjectQueryService│
  │ Preview    │                     │RuntimeContract   │
  │ Renderer   │                     └──────────────────┘
  │ SimaticML  │
  │ Generator  │
  │ Template   │
  │ XmlGen     │
  │ XmlValidator│
  └────────────┘
```

### 4.2 详细调用链

#### 4.2.1 AI 生成管线

```
app.py: /api/generate
  └─ pipeline_orchestrator.run_pipeline()
       ├─ (可选) mimo_client.analyze_with_mimo()          [参考图分析]
       ├─ prompts.build_messages()                        [构建提示词]
       ├─ llm_client.LLMClient.stream()                   [LLM 流式生成]
       ├─ llm_client.extract_json()                       [JSON 提取]
       ├─ hmi_ir.validate_ir()                            [IR 验证]
       ├─ hmi_ir.scale_ir_to_resolution()                 [分辨率缩放]
       ├─ tia_text_sanitizer.sanitize_ir_text_fields()    [文本清洗]
       ├─ variable_engine.VariableEngine.generate()       [变量绑定]
       ├─ (可选) preview_renderer.render_ir_to_png()       [渲染预览]
       ├─ (可选) mimo_client.analyze_with_mimo()          [视觉评审]
       └─ (可选循环) → 再生 → llm_client.LLMClient.stream() ...
```

#### 4.2.2 Build 管线

```
app.py: /api/build
  ├─ hmi_ir.validate_ir()                                 [IR 验证 + 标准化]
  ├─ variable_engine.VariableEngine.generate()            [变量绑定]
  ├─ simaticml_generator.generate_simaticml()             [SimaticML XML 生成]
  │    └─ xml_validator.XmlValidator.validate()           [预导出验证]
  └─ 写盘 (.xml + .json)
```

#### 4.2.3 V3 部署管线

```
app.py: /api/hmi/deploy
  └─ deployment_service.DeploymentService.deploy()
       ├─ validate():
       │    ├─ domain.validation.validate_ir_v2()         [IR V2 校验]
       │    ├─ capability_service.CapabilityService       [能力检查]
       │    └─ validation.tag_binding_gate                [Tag 绑定门控]
       ├─ backends.base.HmiBackend.build_plan():
       │    └─ planners.deployment_planner.DeploymentPlanner
       ├─ backends.base.HmiBackend.execute():
       │    ├─ classic_executor / unified_executor        [Openness 操作]
       │    └─ (write XML / create objects)
       ├─ verification_service.VerificationService.verify()
       │    └─ object_query_service.ObjectQueryService    [只读查询]
       └─ compiler.HmiCompiler.compile()                 [触发编译]
```

#### 4.2.4 TIA 导入管线

```
app.py: /api/openness/import
  └─ openness_manager.OpennessManager.import_or_generate_from_ir()
       ├─ openness_manager.get_hmi_capabilities()         [家族检测]
       ├─ hmi_ir.validate_ir()                            [IR 验证]
       ├─ variable_engine.VariableEngine.generate()       [变量绑定]
       ├─ openness_manager.sync_tags()                    [Tag 同步]
       │    ├─ classic_executor / unified_executor
       │    └─ diagnostics_utils (Tag 集合枚举)
       ├─ 路由分发:
       │    ├─ unified_direct:
       │    │    └─ openness_manager.create_unified_screen_from_ir()
       │    ├─ classic_template_xml:
       │    │    ├─ template_xml_generator.generate_from_template_xml()
       │    │    └─ openness_manager.import_screen_xml()
       │    └─ simaticml:
       │         ├─ simaticml_generator.generate_simaticml()
       │         └─ openness_manager.import_screen()
       └─ XML 预处理 (_preprocess_xml_for_import):
            ├─ text_normalizer.TextNormalizer             [HTML 清洗]
            ├─ multilingual_text_builder.MultilingualTextBuilder
            ├─ screen_number_allocator.ScreenNumberAllocator
            ├─ openness_manager._align_xml_screen_size_to_hmi()
            └─ xml_validator.XmlValidator                 [最终验证]
```

---

## 5. 数据流分析

### 5.1 完整数据流 (用户请求到 TIA Portal)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                   用户请求 → TIA Portal 完整数据流                       │
└─────────────────────────────────────────────────────────────────────────┘

 用户输入 (自然语言 HMI 需求)
    │
    ▼
 [文字描述] "我需要一个电机控制画面，包含启动/停止按钮..."
    │
    ▼
 prompts.py: build_messages()
    │  SYSTEM_PROMPT + IR_SCHEMA_DOC + FEW_SHOT_EXAMPLE + 用户需求
    │
    ▼ messages (List[Dict])
 llm_client.py: LLMClient.stream()
    │  POST /chat/completions → SSE 令牌流
    │
    ▼ raw_text (str)
 extract_json()
    │  提取 ```json ... ``` 或纯 JSON
    │
    ▼ ir (dict)     ← 中间表示 (Intermediate Representation)
    │               格式: {"screens": [{"objects": [...], "tags": [...], ...}], ...}
    │
    ▼
 hmi_ir.py: validate_ir()
    │  - 类型检查 (Button/Indicator/IOField/SymbolicIOField/Text)
    │  - 坐标/尺寸验证与默认值填充
    │  - 数据类型验证
    │  - 分辨率检查
    │  - 自动补全未注册变量到 tags 列表
    │  - 自动布局优化 (行聚类/水平对齐/垂直间距/重叠解决/边界裁剪)
    │
    ▼ ir (dict, cleaned)
 hmi_ir.py: scale_ir_to_resolution()
    │  IR 坐标缩放到目标 HMI 分辨率
    │
    ▼ ir (dict, scaled)
 tia_text_sanitizer.py: sanitize_ir_text_fields()
    │  委托 TextNormalizer: HTML 标签移除、实体解码、控制字符清除
    │
    ▼ ir (dict, sanitized)
 variable_engine.py: VariableEngine.generate()
    │  1. 遍历画面项 → 推断按钮行为/指示灯模式/IO 数据类型
    │  2. 生成变量名 (BTN_/LMP_/IO_/STS_/MEM_)
    │  3. 四级 PLC 地址映射
    │  4. 冲突检测
    │  5. 生成 TagSpec + BindingSpec + ScriptSpec
    │  6. 组装为 HmiProjectSpec
    │
    ▼ HmiProjectSpec (IR V2, with tags+bindings)
    │
    ├──→ [预览路径] preview_renderer.py: render_ir_to_png()
    │       Pillow 绘制 -> PNG bytes -> base64 -> 前端预览
    │
    ├──→ [生成路径] simaticml_generator.py: generate_simaticml()
    │       IR → SimaticML XML 文档
    │       - Screen 节点 (Header + Footer + ObjectList)
    │       - Tags 节点 (HMI 变量定义)
    │       - TextLists 节点 (多语言文本)
    │       - VBScripts 节点 (脚本代码)
    │       - 控件 XML: IOField / SymbolicIOField / Button / Indicator / Text
    │       │
    │       ▼ simaticml_xml (str)
    │       import_engine.py / openness_manager.py
    │         XML 预处理管线:
    │           TextNormalizer → MultilingualTextBuilder
    │           → ScreenNumberAllocator → XmlValidator
    │         │
    │         ▼ preprocessed_xml (str or file path)
    │         TIA Openness: Screens.Import(FileInfo, ImportOptions.Override)
    │
    ├──→ [模板路径] template_xml_generator.py: generate_from_template_xml()
    │       template_xml + IR → 重写后的画面 XML
    │       - prototype_extractor 解析模板原型
    │       - prototype_registry 匹配 IR 项 → 最佳原型
    │       - xml_rewrite_rules 执行克隆/替换
    │       - template_binding_validator 生成后验证
    │       │
    │       ▼ rewritten_xml (str)
    │       openness_manager.import_screen_xml()
    │
    └──→ [Unified 直连] openness_manager.create_unified_screen_from_ir()
            IR 对象 → .NET 类型反射 → ScreenItem 创建
            - reflection_adapter 类型解析
            - unified_executor 执行创建
```

### 5.2 Tag 数据流

```
  Tag 数据流 (从 IR 到 TIA Portal Tag 表)
  ══════════════════════════════════════

 IR 画面项
   │  {type: "button", text: "启动", process_tag: "MOTOR_START"}
   │  {type: "indicator", text: "运行状态", process_tag: "MOTOR_RUNNING"}
   │  {type: "io_field", text: "速度设定", process_tag: "MOTOR_SPEED"}
   ▼
 VariableEngine
   │  1. 类型推断:
   │     Button("启动")    → behavior: MOMENTARY, tag: MOTOR_START (Bool)
   │     Indicator("运行") → mode: STATUS, tag: MOTOR_RUNNING (Bool)
   │     IO("速度")       → datatype: REAL, tag: MOTOR_SPEED (Real)
   │  2. 前缀应用:
   │     BTN_MOTOR_START, STS_MOTOR_RUNNING, IO_MOTOR_SPEED
   │  3. PLC 地址映射:
   │     MOTOR_START  → 精确匹配 DB1.DBX0.0
   │     MOTOR_*     → 前缀匹配 DB1.DBX*
   │  4. 生成 TagSpec 列表 + BindingSpec 列表
   ▼
 TagSpecs + BindingSpecs
   │
   ├──→ [Classic 路径] TagXmlBuilder.build_batch_tags_xml()
   │       → HMI Tag XML (Hmi.Tag.TagComposition.Import 格式)
   │       → ClassicOpennessExecutor.import_hmi_tags_safe()
   │         → TagComposition.Import(FileInfo, ImportOptions.Override)
   │       → _verify_hmi_tags_exist() (后置验证)
   │
   └──→ [Unified 路径] UnifiedTagBuilder.build_tags()
         → tag_specs 列表
         → UnifiedOpennessExecutor.create_tags()
           → sw.Tags.Create(...)
```

---

## 6. 关键设计模式

### 6.1 策略模式 (Strategy)

**应用位置**: `backend/backends/`

**说明**: 根据 HMI 家族选择不同的后端实现，每个后端封装了该 HMI 家族的完整部署逻辑。

```
        ┌──────────────────┐
        │   HmiBackend     │  (抽象基类)
        │  supports()      │
        │  build_plan()    │
        │  execute()       │
        │  verify()        │
        └──────┬───────────┘
               │ 继承
     ┌─────────┼─────────────┐
     ▼         ▼             ▼
┌────────┐ ┌────────┐ ┌────────────┐
│Basic   │ │Comfort │ │Unified     │
│Backend │ │Backend │ │Backend     │
└────────┘ └────────┘ └────────────┘

选择策略: BackendFactory.get_backend(hmi_family)
```

### 6.2 工厂模式 (Factory)

**应用位置**: `backend/services/deployment_service.py` - `BackendFactory`

**说明**: 根据 HMI 家族创建对应的后端实例，封装了后端选择逻辑。

```python
class BackendFactory:
    @staticmethod
    def get_backend(target: TargetSpec) -> HmiBackend:
        if target.family == HmiFamily.BASIC:
            return BasicBackend()
        elif target.family == HmiFamily.COMFORT:
            return ComfortBackend()
        elif target.family == HmiFamily.UNIFIED:
            return UnifiedBackend()
        else:
            raise ValueError(f"Unsupported HMI family: {target.family}")
```

### 6.3 门面模式 (Facade)

**应用位置**: `backend/openness_manager.py` - `OpennessManager`

**说明**: 对外提供统一的 TIA Portal Openness 操作接口，内部委托给多个模块化子模块（SessionManager、DeviceDiscovery、HmiCompiler、ExceptionMapper、AssemblyLoader 等），降低调用方复杂度。

### 6.4 构建者模式 (Builder)

**应用位置**: 多处 XML 构建和编译代码

**说明**: 将复杂对象的构建过程与其表示分离。

- **TagXmlBuilder**: 分步构建 Tag XML（单标签、批量标签、文本列表）
- **ScreenXmlBuilder**: 分步构建画面 XML（Header、Footer、Items、MultilingualText）
- **FunctionListBuilder**: 分步构建 FunctionList XML（事件 -> 动作列表）
- **XmlIdRegistry**: 分步注册/分配 XML ID
- **MultilingualTextBuilder**: 分步构建 MultilingualText DOM

### 6.5 管道模式 (Pipeline)

**应用位置**: 多处链式处理流程

**说明**: 多个处理器依次对数据进行变换，前一个的输出是后一个的输入。

**实例 1 - AI 生成管线** (pipeline_orchestrator):
```
用户需求 → image_analysis → llm_generation → ir_validation
→ scaling → sanitization → variable_binding → mimo_review
→ ([循环]) regeneration → re-validation → re-binding → re-review
```

**实例 2 - XML 预处理管线** (import_engine / openness_manager):
```
raw_xml → TextNormalizer → MultilingualTextBuilder
→ ScreenNumberAllocator → ScreenSizeAlignment
→ NameConflictDetection → XmlValidator
→ Screens.Import()
```

### 6.6 适配器模式 (Adapter)

**应用位置**: 
- `backend/domain/legacy_adapter.py` - `LegacyIrAdapter`: 旧版 IR dict -> HmiProjectSpec
- `backend/tia_text_sanitizer.py`: 兼容 shim，统一委托给 TextNormalizer / MultilingualTextBuilder / XmlValidator
- `backend/backends/unified/reflection_adapter.py` - `UnifiedReflectionAdapter`: 语义 -> .NET 类型/属性/事件名称解析

### 6.7 状态机模式 (State Machine)

**应用位置**: `backend/services/deployment_service.py` - `DeploymentService`

**说明**: 部署流程的状态变化由状态机驱动：

```
DRY_RUN ─→ NOT_CONNECTED ─→ BLOCKED ─→ DEPLOYING ─→ DEPLOYED
                                              │            │
                                              ├→ FAILED    └→ VERIFICATION_FAILED
                                              │            └→ COMPILE_FAILED
                                              └→ BLOCKED
```

### 6.8 注册表模式 (Registry)

**应用位置**: 
- `backend/template/prototype_registry.py` - `PrototypeRegistry`: 模板原型的匹配与检索
- `backend/backends/classic/xml_id_registry.py` - `XmlIdRegistry`: 确定性 ID 的注册与分配

### 6.9 单例模式 (Singleton)

**应用位置**: `app.py` 中的 `OpennessManager` 全局单例（通过 `get_openness()` 惰性初始化），在请求间保持 TIA Portal 连接状态。

### 6.10 模板方法模式 (Template Method)

**应用位置**: `HmiBackend` 抽象基类定义了 deploy 骨架：
```
validate() → build_plan() → execute() → verify()
```
子类（BasicBackend / ComfortBackend / UnifiedBackend）各自实现具体步骤的细节。

### 6.11 目录/目录清单模式 (Catalog / Manifest)

**应用位置**: 
- `backend/backends/classic/xml_fragment_catalog.py` - `XmlFragmentCatalog`: 按 TIA 版本/家族/设备查找 YAML manifest 管理的 XML 金片段
- `backend/references/catalog_service.py` - `CatalogService`: 金模板目录管理

### 6.12 契约模式 (Contract)

**应用位置**: `backend/openness/runtime_contract.py` - `RuntimeContract`

**说明**: 通过对 Siemens.Engineering.HmiUnified DLL 的运行时反射建立"运行时合同"，缓存支持的 .NET 类型、方法、属性和枚举值，保证 Unified 操作的安全性和可预测性。

---

## 7. 各模块代码规模统计

### 7.1 按层级汇总

| 层级 | 总行数 | 占比 |
|------|--------|------|
| 接入层 (app.py) | 1,097 | 5.4% |
| 配置管理 | 141 | 0.7% |
| 管线编排 | 353 | 1.7% |
| 领域模型 | 2,034 | 10.1% |
| Backend 层 (Classic + Unified) | 4,654 | 23.0% |
| Openness 层 | 6,241 | 30.9% |
| OpennessManager (门面) | 2,810 | 13.9% |
| AI / LLM / Prompts | 1,201 | 5.9% |
| 变量/Tag 引擎 | 2,328 | 11.5% |
| XML 生成器 | 1,944 | 9.6% |
| 模板系统 | 1,550 | 7.7% |
| XML 预处理 | 1,688 | 8.4% |
| 服务/规划/能力 | 1,754 | 8.7% |
| 调试/工具/其他 | 789 | 3.9% |
| **总计 (去重)** | **~20,200** | **100%** |

### 7.2 按文件排序 (行数前十)

| 排名 | 文件 | 行数 | 说明 |
|------|------|------|------|
| 1 | `backend/openness/classic_executor.py` | 3,441 | Classic HMI Openness 执行器 |
| 2 | `backend/openness_manager.py` | 2,810 | TIA Portal Openness 门面 |
| 3 | `backend/template_xml_generator.py` | 1,243 | 模板 XML 生成器 |
| 4 | `backend/variable_engine.py` | 1,161 | 变量引擎 |
| 5 | `backend/backends/classic/classic_screen_reference_rewriter.py` | 1,029 | 画面引用重写器 |
| 6 | `app.py` | 1,097 | Flask 主入口 |
| 7 | `backend/services/deployment_service.py` | 945 | V3 部署服务 |
| 8 | `backend/xml_validator.py` | 864 | XML 验证器 |
| 9 | `backend/backends/classic/basic_backend.py` | 736 | Basic 后端 |
| 10 | `backend/simaticml_generator.py` | 701 | SimaticML 生成器 |

### 7.3 各目录完整统计

| 目录 | 文件数 | 总行数 | 说明 |
|------|--------|--------|------|
| `backend/` (根目录) | 22 | 10,464 | 核心模块 |
| `backend/openness/` | 12 | 6,241 | .NET 互操作层 |
| `backend/backends/` | 17 | 4,654 | 后端策略层 |
| `backend/domain/` | 6 | 2,034 | 领域模型 |
| `backend/template/` | 8 | 1,550 | 模板系统 |
| `backend/services/` | 2 | 1,412 | 部署+验证服务 |
| `backend/planners/` | 3 | 421 | 部署规划 |
| `backend/capabilities/` | 3 | 309 | 能力矩阵 |
| `backend/validation/` | 2 | 268 | Tag 绑定验证 |
| `backend/debug/` | 2 | 242 | 调试工具 |
| `backend/utils/` | 2 | 61 | 工具函数 |
| `backend/references/` | 2 | 57 | 目录服务 |
| `app.py` (根) | 1 | 1,097 | 主入口 |
| **总计** | **~80** | **~28,810** | |

---

## 8. 核心流程时序

### 8.1 完整 AI 生成 + 视觉评审时序

```
前端                         后端                             LLM                    MiMo                    TIA Portal
 │                            │                               │                      │                       │
 │  POST /api/generate        │                               │                      │                       │
 │  (requirement + files)     │                               │                      │                       │
 │───────────────────────────>│                               │                      │                       │
 │                            │                               │                      │                       │
 │    SSE: pipeline_start     │                               │                      │                       │
 │<───────────────────────────│                               │                      │                       │
 │                            │                               │                      │                       │
 │    [可选 有参考图]           │                               │                      │                       │
 │    SSE: image_analysis_    │                               │                      │                       │
 │         start              │                               │                      │                       │
 │<───────────────────────────│                               │                      │                       │
 │                            │  analyze_with_mimo(images)    │                      │                       │
 │                            │───────────────────────────────│─────────────────────>│                       │
 │                            │                               │                      │  MiMo 视觉分析          │
 │                            │                               │                      │<──────────────────────│
 │    SSE: image_analysis_    │  (返回分析文本)               │                      │                       │
 │         result             │<──────────────────────────────│──────────────────────│                       │
 │<───────────────────────────│                               │                      │                       │
 │                            │                               │                      │                       │
 │    SSE: generate_start     │                               │                      │                       │
 │<───────────────────────────│                               │                      │                       │
 │                            │  build_messages()             │                      │                       │
 │                            │  LLMClient.stream()           │                      │                       │
 │                            │──────────────────────────────>│                      │                       │
 │    SSE: thinking / content │    SSE 令牌流                 │                      │                       │
 │<───────────────────────────│<──────────────────────────────│                      │                       │
 │                            │                               │                      │                       │
 │                            │  extract_json()               │                      │                       │
 │                            │  validate_ir()                │                      │                       │
 │                            │  scale_ir_to_resolution()     │                      │                       │
 │                            │  sanitize_ir_text_fields()    │                      │                       │
 │                            │                               │                      │                       │
 │    SSE: parsed_ok          │                               │                      │                       │
 │<───────────────────────────│                               │                      │                       │
 │                            │                               │                      │                       │
 │    SSE: variable_bind      │  VariableEngine.generate()    │                      │                       │
 │<───────────────────────────│                               │                      │                       │
 │                            │                               │                      │                       │
 │    [可选 MiMo 评审]        │                               │                      │                       │
 │    SSE: review_start       │                               │                      │                       │
 │<───────────────────────────│                               │                      │                       │
 │                            │  render_ir_to_png()           │                      │                       │
 │                            │  analyze_with_mimo(png)       │                      │                       │
 │    SSE: review_progress    │───────────────────────────────│─────────────────────>│                       │
 │<───────────────────────────│                               │                      │  MiMo 画面评审          │
 │                            │                               │                      │<──────────────────────│
 │    SSE: review_result      │                               │                      │                       │
 │<───────────────────────────│<──────────────────────────────│──────────────────────│                       │
 │                            │                               │                      │                       │
 │    [若未通过]              │                               │                      │                       │
 │    SSE: regenerate_start   │  LLMClient.stream(regen)      │                      │                       │
 │<───────────────────────────│──────────────────────────────>│                      │                       │
 │                            │  (循环 2-8 步)                │                      │                       │
 │                            │                               │                      │                       │
 │    [若通过]               │                               │                      │                       │
 │    SSE: review_pass        │                               │                      │                       │
 │    SSE: pipeline_done      │                               │                      │                       │
 │<───────────────────────────│                               │                      │                       │
```

### 8.2 V3 部署管线时序

```
前端               DeploymentService          BackendFactory       Backend          Openness         TIA Portal
 │                        │                        │                 │                 │                │
 │ POST /api/hmi/deploy   │                        │                 │                 │                │
 │───────────────────────>│                        │                 │                 │                │
 │                        │                        │                 │                 │                │
 │    ① validate          │                        │                 │                 │                │
 │                        │ validate_ir_v2()       │                 │                 │                │
 │                        │ CapabilityService      │                 │                 │                │
 │                        │ tag_binding_gate       │                 │                 │                │
 │                        │                        │                 │                 │                │
 │    ② BackendFactory    │                        │                 │                 │                │
 │                        │ get_backend(family)────│────────────────>│                 │                │
 │                        │                        │                 │                 │                │
 │    ③ build_plan        │                        │                 │                 │                │
 │                        │ build_plan(spec)───────────────────────>│                 │                │
 │                        │                        │                 │                 │                │
 │    ④ execute           │                        │                 │                 │                │
 │                        │ execute(plan)──────────────────────────>│                 │                │
 │                        │                        │                 │  Tag 创建         │                │
 │                        │                        │                 │────────────────>│                │
 │                        │                        │                 │                 │ TagComposition  │
 │                        │                        │                 │                 │ .Import() /     │
 │                        │                        │                 │                 │ Tags.Create()   │
 │                        │                        │                 │                 │───────────────> │
 │                        │                        │                 │                 │<─────────────── │
 │                        │                        │                 │                 │                │
 │                        │                        │                 │  画面创建        │                │
 │                        │                        │                 │────────────────>│                │
 │                        │                        │                 │                 │ Screens.Import │
 │                        │                        │                 │                 │ / ScreenItems  │
 │                        │                        │                 │                 │ .Create()      │
 │                        │                        │                 │                 │───────────────> │
 │                        │                        │                 │                 │<─────────────── │
 │                        │                        │                 │                 │                │
 │    ⑤ compile           │                        │                 │                 │                │
 │                        │ compile() ───────────────────────────────────────────────>│                │
 │                        │                        │                 │                 │ ICompilable    │
 │                        │                        │                 │                 │ .Compile()     │
 │                        │                        │                 │                 │───────────────> │
 │                        │                        │                 │                 │<─────────────── │
 │                        │                        │                 │                 │                │
 │    ⑥ verify            │                        │                 │                 │                │
 │                        │ verify() ───────────────────────────────────────────────>│                │
 │                        │                        │                 │                 │ ObjectQuery    │
 │                        │                        │                 │                 │ Service        │
 │                        │                        │                 │                 │───────────────> │
 │                        │                        │                 │                 │<─────────────── │
 │                        │                        │                 │                 │                │
 │<──── DeploymentResult ─│                        │                 │                 │                │
```

### 8.3 Tag 同步时序

```
前端 / 管线               OpennessManager           HMI Family           ClassicExecutor /         TIA Portal
 │                            │                    Detection             UnifiedExecutor             │
 │                            │                        │                      │                      │
 │ sync_tags(tags)            │                        │                      │                      │
 │───────────────────────────>│                        │                      │                      │
 │                            │                        │                      │                      │
 │    ① 前置检查              │                        │                      │                      │
 │    ② _find_hmi_software() │                        │                      │                      │
 │────────────────────────────────────────────────────>│                      │                      │
 │                            │                        │                      │                      │
 │    ③ get_hmi_capabilities │                        │                      │                      │
 │                            │                        │ Type heuristics      │                      │
 │                            │                        │ (KTP/TP/Unified)     │                      │
 │                            │                        │─────────────────────>│                      │
 │                            │                        │<─────────────────────│                      │
 │                            │  HMI_FAMILY_UNKNOWN    │                      │                      │
 │     [未知家族阻断]         │<───────── ERROR ───────│                      │                      │
 │<──────── Diagnostic ──────│                        │                      │                      │
 │                            │                        │                      │                      │
 │    ④ _resolve_hmi_tag     │                        │                      │                      │
 │      _container()          │                        │                      │                      │
 │                            │  Classic: TagFolder.   │                      │                      │
 │                            │  DefaultTagTable.Tags  │                      │                      │
 │                            │  Unified: sw.Tags      │                      │                      │
 │                            │────────────────────────│─────────────────────>│                      │
 │                            │<───────────────────────│<─────────────────────│                      │
 │                            │                        │                      │                      │
 │    ⑤ 过滤已有/新增         │                        │                      │                      │
 │                            │                        │                      │                      │
 │    ⑥ 家族路由:             │                        │                      │                      │
 │    [Classic]               │                        │                      │                      │
 │                            │  TagSpec -> XML        │                      │                      │
 │                            │  HmiTagXmlBuilder      │                      │                      │
 │                            │  .build_batch_tags_xml()                     │                      │
 │                            │─────────────────────────────────────────────>│                      │
 │                            │                        │                      │ TagComposition       │
 │                            │                        │                      │ .Import()            │
 │                            │                        │                      │─────────────────────>│
 │                            │                        │                      │<─────────────────────│
 │                            │                        │                      │                      │
 │    [Unified]               │                        │                      │                      │
 │                            │  specs ->              │                      │                      │
 │                            │  UnifiedOpennessExec.                         │                      │
 │                            │  .create_tags()        │                      │                      │
 │                            │─────────────────────────────────────────────>│                      │
 │                            │                        │                      │ sw.Tags.Create()     │
 │                            │                        │                      │─────────────────────>│
 │                            │                        │                      │<─────────────────────│
 │                            │                        │                      │                      │
 │    ⑦ 后置验证              │                        │                      │                      │
 │    _verify_hmi_tags_exist  │                        │                      │                      │
 │                            │ 遍历 Tag 表确认        │                      │                      │
 │                            │────────────────────────│─────────────────────>│                      │
 │  <──────── 结果 ──────────│                        │                      │                      │
```

---

## 附录: 文件索引

### 核心文件

| 文件路径 | 行数 | 类型 |
|----------|------|------|
| `C:\Users\sunny\Desktop\SiemensHmi_Assistant\SiemensHmi_Assistant_V2.3\SiemensHmi_Assistant_V2.3\SiemensHmi_Assistant\app.py` | 1097 | Flask 主入口 |
| `backend/config_manager.py` | 141 | 配置管理 |
| `backend/pipeline_orchestrator.py` | 353 | AI 生成管线编排 |
| `backend/openness_manager.py` | 2810 | Openness 门面 |

### 领域模型

| 文件路径 | 行数 | 类型 |
|----------|------|------|
| `backend/domain/ir_v2.py` | 392 | IR V2 模型 |
| `backend/domain/enums.py` | 188 | 枚举定义 |
| `backend/domain/diagnostics.py` | 171 | 诊断模型 |
| `backend/domain/deployment_plan.py` | 59 | 部署计划 |
| `backend/domain/deployment_result.py` | 162 | 部署结果 |
| `backend/domain/validation.py` | 411 | IR 验证 |
| `backend/domain/legacy_adapter.py` | 536 | 遗留适配器 |
| `backend/domain/__init__.py` | 115 | 领域包初始化 |

### Backend 层

| 文件路径 | 行数 | 类型 |
|----------|------|------|
| `backend/backends/base.py` | 31 | 抽象基类 |
| `backend/backends/classic/basic_backend.py` | 736 | Basic 后端 |
| `backend/backends/classic/comfort_backend.py` | 368 | Comfort 后端 |
| `backend/backends/classic/common.py` | 107 | Classic 汇编器 |
| `backend/backends/classic/classic_screen_reference_rewriter.py` | 1029 | 画面引用重写器 |
| `backend/backends/classic/classic_validator.py` | 122 | Classic 验证器 |
| `backend/backends/classic/dynamic_xml_builder.py` | 130 | 动态绑定 XML |
| `backend/backends/classic/function_list_builder.py` | 81 | FunctionList XML |
| `backend/backends/classic/link_resolver.py` | 111 | 引用解析器 |
| `backend/backends/classic/screen_xml_builder.py` | 254 | 画面 XML 构建器 |
| `backend/backends/classic/tag_xml_builder.py` | 520 | Tag XML 构建器 |
| `backend/backends/classic/vbs_builder.py` | 90 | VBS 构建器 |
| `backend/backends/classic/xml_fragment_catalog.py` | 134 | XML 片段目录 |
| `backend/backends/classic/xml_id_registry.py` | 68 | XML ID 注册表 |
| `backend/backends/unified/unified_backend.py` | 305 | Unified 后端 |
| `backend/backends/unified/tag_builder.py` | 49 | Unified Tag 构建器 |
| `backend/backends/unified/screen_builder.py` | 47 | Unified 画面构建器 |
| `backend/backends/unified/property_builder.py` | 37 | Unified 属性构建器 |
| `backend/backends/unified/binding_builder.py` | 46 | Unified 绑定构建器 |
| `backend/backends/unified/event_builder.py` | 80 | Unified 事件构建器 |
| `backend/backends/unified/js_builder.py` | 46 | Unified JS 构建器 |
| `backend/backends/unified/reflection_adapter.py` | 96 | Unified 反射适配器 |

### Openness 层

| 文件路径 | 行数 | 类型 |
|----------|------|------|
| `backend/openness/classic_executor.py` | 3441 | Classic 执行器 |
| `backend/openness/unified_executor.py` | 595 | Unified 执行器 |
| `backend/openness/session_manager.py` | 153 | 会话管理器 |
| `backend/openness/device_discovery.py` | 253 | 设备发现 |
| `backend/openness/compiler.py` | 224 | 编译触发 |
| `backend/openness/assembly_loader.py` | 141 | 程序集加载 |
| `backend/openness/exception_mapper.py` | 189 | 异常映射 |
| `backend/openness/object_query_service.py` | 585 | 对象查询服务 |
| `backend/openness/reflection_utils.py` | 213 | 反射工具 |
| `backend/openness/runtime_contract.py` | 202 | 运行时合同 |
| `backend/openness/diagnostics_utils.py` | 235 | 诊断工具 |

### 基础设施

| 文件路径 | 行数 | 类型 |
|----------|------|------|
| `backend/llm_client.py` | 228 | LLM 客户端 |
| `backend/mimo_client.py` | 323 | MiMo 客户端 |
| `backend/prompts.py` | 419 | 提示词 |
| `backend/review_prompts.py` | 231 | 评审提示词 |
| `backend/variable_engine.py` | 1161 | 变量引擎 |
| `backend/tag_binding_normalizer.py` | 579 | Tag 绑定规范化 |
| `backend/hmi_ir.py` | 528 | IR 验证器 |
| `backend/simaticml_generator.py` | 701 | SimaticML 生成器 |
| `backend/template_xml_generator.py` | 1243 | 模板 XML 生成器 |
| `backend/xml_validator.py` | 864 | XML 验证器 |
| `backend/preview_renderer.py` | 299 | 画面渲染器 |
| `backend/text_normalizer.py` | 273 | 文本规范化 |
| `backend/multilingual_text_builder.py` | 381 | 多语言文本构建 |
| `backend/screen_number_allocator.py` | 170 | 画面编号分配 |
| `backend/tia_text_sanitizer.py` | 143 | 文本清洗 shim |
| `backend/import_engine.py` | 408 | 导入执行器 |
| `backend/generation_summary.py` | 213 | 生成总结 |

### 模板系统

| 文件路径 | 行数 | 类型 |
|----------|------|------|
| `backend/template/template_profile.py` | 77 | 模板数据模型 |
| `backend/template/prototype_extractor.py` | 351 | 原型提取器 |
| `backend/template/prototype_registry.py` | 210 | 原型注册表 |
| `backend/template/binding_pattern_extractor.py` | 127 | 绑定模式提取 |
| `backend/template/event_pattern_extractor.py` | 102 | 事件模式提取 |
| `backend/template/xml_rewrite_rules.py` | 231 | XML 重写规则 |
| `backend/template/xml_utils.py` | 256 | XML 工具 |
| `backend/template/template_binding_validator.py` | 191 | 模板绑定验证 |

### 服务 / 规划 / 能力

| 文件路径 | 行数 | 类型 |
|----------|------|------|
| `backend/services/deployment_service.py` | 945 | 部署服务 |
| `backend/services/verification_service.py` | 467 | 验证服务 |
| `backend/planners/deployment_planner.py` | 299 | 部署规划器 |
| `backend/planners/dependency_graph.py` | 105 | 依赖图 |
| `backend/capabilities/capability_service.py` | 222 | 能力服务 |
| `backend/capabilities/static_matrix.py` | 65 | 静态能力矩阵 |
| `backend/validation/tag_binding_gate.py` | 250 | Tag 绑定门控 |
| `backend/references/catalog_service.py` | 53 | 目录服务 |
| `backend/utils/tag_prefix_utils.py` | 60 | Tag 前缀工具 |
| `backend/debug/tag_pipeline_debug.py` | 226 | 调试探针 |

---

*本文档基于对 Siemens HMI Assistant V2.3 后端代码的全面静态分析自动生成，覆盖 app.py 及 backend/ 下所有 Python 模块。*
*生成日期: 2026-06-21*

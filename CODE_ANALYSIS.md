# Siemens HMI 画面助手 — 完整代码分析文档

> **生成日期:** 2026-06-18  
> **分析范围:** 项目全部 Python 源码、配置、测试  
> **总代码行数:** ~3500+ 行（Python）

---

## 目录

1. [项目概览](#1-项目概览)
2. [系统架构图](#2-系统架构图)
3. [数据流全景](#3-数据流全景)
4. [入口文件: app.py](#4-入口文件-apppy)
5. [后端模块逐文件分析](#5-后端模块分析)
   - [5.1 config_manager.py — 配置管理](#51-config_managerpy)
   - [5.2 prompts.py — 提示词工程](#52-promptspy)
   - [5.3 llm_client.py — 大模型客户端](#53-llm_clientpy)
   - [5.4 hmi_ir.py — HMI中间表示校验](#54-hmi_irpy)
   - [5.5 simaticml_generator.py — SimaticML生成](#55-simaticml_generatorpy)
   - [5.6 openness_manager.py — TIA Openness连接](#56-openness_managerpy)
   - [5.7 pipeline_orchestrator.py — 多阶段流水线](#57-pipeline_orchestratorpy)
   - [5.8 preview_renderer.py — 预览渲染](#58-preview_rendererpy)
   - [5.9 mimo_client.py — MiMo视觉API](#59-mimo_clientpy)
   - [5.10 review_prompts.py — 审查提示词](#510-review_promptspy)
   - [5.11 template_xml_generator.py — 模板XML改写](#511-template_xml_generatorpy)
   - [5.12 text_normalizer.py — 文本规范化](#512-text_normalizerpy)
   - [5.13 multilingual_text_builder.py — 多语言文本构建](#513-multilingual_text_builderpy)
   - [5.14 xml_validator.py — XML校验器](#514-xml_validatorpy)
   - [5.15 screen_number_allocator.py — 画面编号分配](#515-screen_number_allocatorpy)
   - [5.16 import_engine.py — 导入引擎](#516-import_enginepy)
   - [5.17 tia_text_sanitizer.py — 文本安全兼容层](#517-tia_text_sanitizerpy)
6. [配置文件: config.yaml](#6-配置文件-configyaml)
7. [前端文件](#7-前端文件)
8. [测试套件](#8-测试套件)
9. [导入管线详解](#9-导入管线详解)
10. [关键设计决策与模式](#10-关键设计决策与模式)

---

## 1. 项目概览

**Siemens HMI 画面助手** 是一个基于 Flask 的 Web 应用，核心功能是：

1. **用户** 用中文自然语言描述 HMI 画面需求（如"需要一个电机启停控制画面，含启动/停止/复位按钮…"）
2. **大模型（LLM）** 将需求转化为结构化的中间表示（IR, JSON 格式）
3. **后端** 将 IR 转换为 Siemens SimaticML XML 格式
4. **Openness API** 将生成的 XML 自动导入到 TIA Portal（西门子博途）项目中
5. **可选视觉审查** 使用 MiMo 视觉模型对渲染的预览图进行审查，必要时自动修正

### 技术栈

| 层次 | 技术 | 用途 |
|------|------|------|
| Web 框架 | Flask 3.x | HTTP API + SSE 流式推送 |
| 配置 | PyYAML | config.yaml 读写 |
| LLM | DeepSeek/OpenAI 兼容 API | 需求→IR JSON 生成 |
| 视觉审查 | Xiaomi MiMo API | 预览图审查 |
| 图像渲染 | Pillow (PIL) | IR→PNG 预览图 |
| PDF 解析 | pdfplumber | 上传 PDF 需求提取文本 |
| TIA 集成 | pythonnet + Siemens.Engineering.dll | 博途 Openness 自动化 |
| XML | xml.etree.ElementTree | SimaticML 生成与修复 |
| 测试 | pytest | API/模块单元测试 |

---

## 2. 系统架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                         前端 (index.html + app.js)                     │
│  ┌──────────┐ ┌──────────┐ ┌───────────┐ ┌──────────┐ ┌──────────┐ │
│  │ 配置管理  │ │ 需求输入  │ │ 思考过程  │ │ XML预览   │ │ Openness │ │
│  │ 页       │ │ 框       │ │ 展示区    │ │ 展示区    │ │ 控制面板  │ │
│  └────┬─────┘ └────┬─────┘ └─────┬─────┘ └────┬─────┘ └────┬─────┘ │
└───────┼────────────┼─────────────┼────────────┼────────────┼────────┘
        │            │             │            │            │
   ┌────▼────────────▼─────────────▼────────────▼────────────▼────┐
   │                    Flask API (app.py)                           │
   │  /api/config       /api/generate      /api/build               │
   │  /api/build/template-xml   /api/openness/*                     │
   │  /api/generate/with_review                                     │
   └────┬──────────────┬──────────────┬──────────────┬──────────────┘
        │              │              │              │
   ┌────▼────┐  ┌──────▼──────┐  ┌───▼──────┐  ┌───▼──────────┐
   │Config   │  │Pipeline     │  │SimaticML │  │Openness      │
   │Manager  │  │Orchestrator │  │Generator │  │Manager       │
   └─────────┘  └──────┬──────┘  └───┬──────┘  └───┬──────────┘
                       │              │              │
              ┌────────▼──────┐       │     ┌────────▼──────────┐
              │LLM Client     │       │     │ 导入管线(5层)      │
              │(DeepSeek/     │       │     │ TextNormalizer →  │
              │ OpenAI API)   │       │     │ MT Builder →      │
              └───────────────┘       │     │ ScreenNumber →    │
                      │              │     │ XmlValidator →    │
              ┌───────▼───────┐       │     │ ImportEngine      │
              │HMI IR         │       │     └──────────────────┘
              │Validator       │◄──────┘
              └───────┬───────┘
                      │
              ┌───────▼───────┐
              │Preview        │
              │Renderer(PIL)  │
              └───────┬───────┘
                      │
              ┌───────▼───────┐
              │MiMo Client    │
              │(视觉审查)      │
              └───────────────┘
```

---

## 3. 数据流全景

```
用户输入中文需求
      │
      ▼
┌─────────────────┐
│ 1. LLM 生成      │  System Prompt + Few-shot 示例 → DeepSeek/OpenAI
│    (SSE 流式)    │  产出: JSON 格式 HMI 画面 IR
└────────┬────────┘
         ▼
┌─────────────────┐
│ 2. IR 校验       │  validate_ir() — 类型检查、交叉引用、默认值补全
│                  │  _optimize_layout() — 轻量自动排版
└────────┬────────┘
         ▼
┌─────────────────┐
│ 3. [可选] 视觉审查│  render_ir_to_png() → PNG 预览图
│    (MiMo)        │  analyze_with_mimo() → 审查结果
│                  │  若不通过 → 修正提示词 → 回到步骤1
└────────┬────────┘
         ▼
┌─────────────────┐
│ 4. SimaticML 生成│  generate_simaticml() → 带命名空间的 TIA XML
│    或            │  或 generate_from_template_xml() → 改写模板XML
│    模板XML改写   │
└────────┬────────┘
         ▼
┌─────────────────┐
│ 5. TIA Portal   │  OpennessManager.import_screen()
│    导入          │  预处理管线 → Screens.Import(FileInfo, ImportOptions)
└─────────────────┘
```

---

## 4. 入口文件: app.py

**文件路径:** `app.py` (494行)  
**角色:** Flask 主程序 — 定义所有 HTTP 路由，连接前后端与后端模块。

### 逐行分析

| 行号 | 代码 | 分析 |
|------|------|------|
| 1 | `# -*- coding: utf-8 -*-` | 源文件编码声明，确保中文注释/字符串在 Python 2 兼容环境下也能正常处理 |
| 2-16 | 文档字符串 | 详细列出 15 条路由一览表，是开发期的重要参考 |
| 17-24 | `import os, io, json...` | 导入标准库和 Flask 核心模块：`flask.Flask` 是应用工厂，`jsonify` 返回 JSON 响应，`Response` 用于 SSE 流式，`stream_with_context` 是流式上下文管理器 |
| 26-33 | `from backend import ...` | 导入项目自定义模块。`config_manager` 别名 `cfgm` 简化调用，`extract_json` 从 LLM 输出提取 JSON，`validate_ir` 校验中间表示，`generate_simaticml` 生成 XML，`OpennessManager` 管理博途连接，`generate_from_template_xml` 和 `run_pipeline` 分别提供模板改写和审查流水线能力 |
| 35-38 | `BASE_DIR / app = Flask(...)` | `BASE_DIR` 是项目根目录的绝对路径。Flask 实例化时显式指定 `template_folder` 和 `static_folder` 到 `BASE_DIR` 子目录，避免工作目录不是项目根目录时找不到模板 |
| 42 | `app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0` | 开发期间禁静态文件缓存，防止浏览器缓存旧版 `app.js`/`style.css`。注释解释：旧缓存可能导致前端调用已废弃接口→404→诊断弹窗卡死 |
| 45-49 | `@app.after_request` / `_no_cache_static` | 对 `/static/` 路径的响应额外设置 `Cache-Control: no-store, max-age=0`，双重保险禁用缓存 |
| 53 | `_openness = None` | 模块级全局变量，保存 OpennessManager 实例。因为博途附加态需要在多次 HTTP 请求间保持（与 TIA Portal 进程的连接不能每次请求重新建立） |
| 56-64 | `get_openness()` | 懒初始化单例模式函数。首次调用创建新的 `OpennessManager(cfg)`，后续调用只更新其内部配置（`cfg` 和 `output_cfg`），复用已建立的博途连接。 |
| 70-72 | `@app.route("/")` / `index()` | 根路由返回 `index.html` |
| 78-82 | `GET /api/config` | 读取配置文件。注释说明出于安全考虑对 `api_key` 做掩码处理（实际此版本未在服务端做掩码，由前端处理） |
| 85-92 | `POST /api/config` | 保存配置。接收 JSON body 中的 `config` 字段，调用 `cfgm.save_config()` 写入 config.yaml。异常时返回 400。 |
| 95-102 | `POST /api/config/raw` | 直接保存原始 YAML 文本。用于前端"原始编辑"模式。 |
| **文件解析 (108-154)** | | |
| 108-140 | `parse_uploaded_files(files)` | 核心文件解析函数。接收 Flask `request.files.getlist("files")` 返回的文件列表，返回三元组：`extra_text`（提取的文本内容，拼入 LLM prompt）、`images_preview`（前端展示用的 data URL 列表）、`images_analysis`（MiMo 分析用的 base64 图片列表）。支持 PDF（通过 pdfplumber 提取文本）、PNG/JPG/BMP/GIF/WEBP（转 base64）、TXT/MD/CSV（直接读文本）。 |
| 143-154 | `_extract_pdf_text(raw_bytes, name)` | PDF 文本提取辅助。使用 `pdfplumber.open()` 逐页提取文本，标注页号和文件名。异常时返回错误提示文本（而非抛异常中断流程）。 |
| **流式生成 (160-213)** | | |
| 160-213 | `POST /api/generate` | **核心路由之一**。接收用户需求文本（支持 multipart/form-data 带文件或纯 JSON），调用 LLM 流式生成 HMI 画面 IR。关键设计点：(1) `parse_uploaded_files` 处理上传附件并将提取文本拼入 prompt；(2) `thinking_depth` 可临时覆盖 config.yaml 中的 LLM 思考深度配置；(3) SSE 事件类型包括 `start`(含深度信息)、`thinking`(思考过程增量)、`content`(正文增量)、`parsed_ok`(JSON 解析成功)、`parse_warn`(解析警告)、`done`(流结束)、`error`(错误)；(4) 使用 `stream_with_context` 装饰器保证在流式生成期间 Flask 请求上下文存活；(5) `Cache-Control: no-cache` 和 `X-Accel-Buffering: no` 是 SSE 必须的 HTTP 头。 |
| **带审查流水线 (219-260)** | | |
| 219-260 | `POST /api/generate/with_review` | 带 MiMo 视觉审查的多阶段流水线。与 `/api/generate` 类似，但将生成逻辑委托给 `run_pipeline()` 编排器。额外产出 `pipeline_start`、`review_start`、`review_result`、`review_pass`、`regenerate_start` 等 SSE 事件。 |
| **构建 API (266-302)** | | |
| 266-302 | `POST /api/build` | 接收 LLM 原始输出文本，经 `extract_json()`→`validate_ir()`→`generate_simaticml()` 流水线后同时生成 XML 和落盘 IR JSON。落盘路径格式：`exports/{screen_name}_{timestamp}.xml`。返回 `ir`、`xml`、路径和警告。 |
| **模板 XML 构建 (403-448)** | | |
| 403-448 | `POST /api/build/template-xml` | 专门用于经典 HMI 模板路线：接收 IR + 模板 XML 路径，调用 `generate_from_template_xml()` 改写模板。落盘到 `exports/generated_from_template/` 目录。 |
| **Openness API 组 (308-484)** | | |
| 308-310 | `GET /api/openness/diagnose` | 诊断当前环境是否满足 Openness 连接条件（Windows/pythonnet/DLL 路径）。 |
| 315-325 | `GET /api/openness/status` + `GET /api/tia/status` | 兼容别名路由。旧版前端缓存可能仍请求 `/api/tia/status`，不使用装饰器 `@app.route` 多装饰器模式同时支持两个 URL。返回 `connected`、`ready` 和诊断结果。 |
| 328-330 | `POST /api/openness/connect` | 一键连接博途。 |
| 333-362 | `POST /api/openness/export-reference` | 从已连接博途项目导出一个画面作为 SimaticML 格式参考模板，自动更新 `config.yaml` 的 `output.reference_xml`。 |
| 365-368 | `GET /api/openness/capabilities` | 获取当前 HMI 设备能力（类型、推荐模式、可用画面列表等）。 |
| 371-400 | `POST /api/openness/export-template` | 导出指定画面为模板 XML（经典 HMI 模板路线用）。导出成功后自动更新配置中的 `classic_template.template_xml_path`。 |
| 451-479 | `POST /api/openness/import` | **导入画面到博途。** 支持多种模式：新模式 `ir + mode`（自动路由到 unified_direct/classic_template_xml/simaticml），旧模式 `xml_path`（直接导入预设的 XML 文件），以及纯 IR 模式（先生成 SimaticML 再导入）。这是最复杂的路由之一。 |
| 482-484 | `POST /api/openness/disconnect` | 断开与博途的附加连接。 |
| **启动入口 (487-493)** | | |
| 487-493 | `if __name__ == "__main__"` | 从 `config.yaml` 的 `server` 节读取 host/port/debug 配置启动 Flask 开发服务器。`threaded=True` 保证 SSE 流式响应不阻塞其他请求。 |

---

## 5. 后端模块分析

### 5.1 config_manager.py

**文件路径:** `backend/config_manager.py` (142行)  
**角色:** 配置文件读写与校验的单一入口。使用线程锁保护并发读写。

| 行号 | 分析 |
|------|------|
| 1-6 | 导入标准库和 PyYAML。`threading.Lock()` 实现线程安全。 |
| 8-9 | `_LOCK = threading.Lock()` 和 `_CONFIG_PATH` 是模块级私有变量。`_CONFIG_PATH` 基于当前文件的祖父目录（即项目根目录）拼接 `config.yaml`。 |
| 12-94 | `DEFAULT_CONFIG` 字典定义了所有配置项的默认值，作为"配置模板"。每当加载配置时，用户文件中的值会通过 `_deep_merge` 覆盖默认值，保证新增配置项有合理默认值。这让配置升级无缝——用户不需要手动添加新字段。 |
| 97-105 | `_deep_merge(base, override)` — 递归深合并函数。如果 override 中的值是 dict 且 base 中对应键也是 dict，则递归合并；否则直接覆盖。这保证了嵌套配置（如 `llm.providers.deepseek`）的增量更新。 |
| 108-118 | `load_config()` — 首次运行时如果 config.yaml 不存在，自动写入默认配置。之后每次加载都会与默认配置合并，防止缺失新增字段。 |
| 121-127 | `save_config(new_config)` — 保存前也执行深合并，保证写入的配置是完整的。 |
| 130-135 | `save_raw_yaml(text)` — 前端"原始编辑"模式的保存函数。先解析验证再保存，防写入非法 YAML。 |
| 138-141 | `get_raw_yaml()` — 读取当前配置并序列化为 YAML 字符串，供前端原始编辑展示。 |

**设计要点:**
- 线程安全：所有文件操作都在 `_LOCK` 保护下
- 配置模板模式：`DEFAULT_CONFIG` + `_deep_merge` 保证向前兼容
- 首次运行自动生成配置文件，降低部署门槛

---

### 5.2 prompts.py

**文件路径:** `backend/prompts.py` (374行)  
**角色:** **项目最重要的模块** — 定义所有 LLM 系统提示词、Few-shot 示例、布局规范、以及修正模式的提示词模板。

| 行号 | 段落 | 分析 |
|------|------|------|
| 14-116 | `IR_SCHEMA_DOC` | 输出 JSON Schema 文档。详细定义了 meta（画面元信息）、tags（变量声明）、text_lists（文本列表）、objects（5种控件类型：IOField/SymbolicIOField/Button/Indicator/Text）、scripts（VBS脚本）的完整结构。每个字段都有中文说明和示例值。 |
| 118-130 | `TEXT_CONVENTIONS` | 文字与命名规范。定义了术语统一性（启动/停止/复位…）、命名前缀规范（LMP_指示灯/BTN_按钮/IO_/SIO_/TXT_）、物理单位标注、故障类使用红色并闪烁、按钮文字≤6汉字、标题≤16汉字等约束。 |
| 132-144 | `VBS_CONVENTIONS` | VBS 脚本规范。要求使用 `SmartTags("变量名")` 或 `HMIRuntime.Tags()` 读写变量，登录脚本做空值/越界判断，Basic 面板减少复杂脚本等。 |
| 146-176 | `LAYOUT_CONVENTIONS` | **布局与排版硬性规范**（11条）。这是解决之前版本"控件堆叠、间距混乱"问题的核心。关键约束：先分区再放控件、不同分辨率下不同边距、按钮间≥24px、同类控件行间≥18px、区块间≥24px、禁止重叠和越界、小屏优先纵向排布。第10条要求输出前自检重叠/间距/对齐/孤立控件。 |
| 178-188 | `JSON_SELF_CHECK` | 输出前自检清单。提醒模型在脑中完成检查（不输出检查过程）：id 唯一性、交叉引用验证、坐标范围内检查、间距验证、多余对象检查、标题文本存在性检查等。 |
| 190-222 | `SYSTEM_PROMPT` | **最终拼接的系统提示词。** 使用 Python f-string 将上述所有规范片段组装成一份完整的系统提示。要求模型扮演"资深西门子 WinCC/博途 HMI 画面工程师"，只输出 JSON，不输出解释。 |
| 225-293 | Few-shot 示例 | `FEW_SHOT_USER` 是一个电机启停控制的需求描述，`FEW_SHOT_ASSISTANT` 是对应的完整 IR JSON。这个示例展示了按钮区+状态区+参数区三区布局、变量声明与脚本定义的交叉引用、统一的命名前缀等最佳实践。 |
| 296-317 | `build_messages()` | 组装发送给 LLM 的 messages 列表。接收 `user_requirement`（用户需求）、`extra_context`（上传文件提取的补充文本）、`use_few_shot`（是否使用少样本示例）、`review_context`（审查反馈上下文）。当 `review_context` 不为 None 时，走修正模式；否则走初始生成模式。 |
| 320-355 | `_build_revision_messages()` | 构建修正模式的 messages。将上一版 IR JSON、MiMo 审查反馈文本和原需求组合后，要求模型"只修正被指出的问题，保持其他部分不变"。 |
| 358-373 | `_REGENERATION_SYSTEM_ADDENDUM` | 修正模式专用的系统提示词补充。规定了9条修正原则，核心是"逐项修正、不破坏正确部分"。 |

**设计要点:**
- 提示词分层设计：规范文档 → 自检清单 → 最终拼接（模块化、可维护）
- Few-shot 示例是关键：让模型理解正确的 IR 格式和工程化布局
- 修正模式与初始模式共享核心结构，但有独立的审查反馈处理逻辑

---

### 5.3 llm_client.py

**文件路径:** `backend/llm_client.py` (229行)  
**角色:** 大模型 API 客户端的统一封装，支持流式输出和思考过程解析。

| 行号 | 分析 |
|------|------|
| 15-19 | 导入 `json` 和 `requests`。 |
| 20-25 | `DEPTH_MAP` — 思考深度配置映射表。将用户的中文深度选择（关闭/低/中/高）映射为三个参数：`use_reasoner`（是否使用推理模型）、`effort`（`reasoning_effort` 值）、`hint_tokens`（诱导思考时的 token 预算）。 |
| 28-32 | `_THINKING_INDUCE` — 当 provider 不支持原生推理字段时，注入的诱导式思考提示。要求模型在 `<thinking>` 标签内用中文推演设计思路，标签外输出最终 JSON。 |
| 35-42 | `LLMClient.__init__()` — 从配置中提取当前活跃的 provider 名称、provider 配置、思考深度和是否显示思考过程。 |
| 45-75 | `_build_payload(messages)` — 构建 API 请求体。核心逻辑：(1) 根据 `thinking_depth` 决定使用 `reasoner_model` 还是 `chat_model`；(2) 对原生推理模型透传 `reasoning_effort` 参数；(3) 对无原生推理的模型，在 system 层注入诱导思考提示。 |
| 78-169 | `stream(messages)` — **流式生成核心**。使用 `requests.post(stream=True)` 逐行读取 SSE 响应。三种输出解析策略：(1) 原生推理模型直接读取 `reasoning_content` 和 `content` 字段；(2) 诱导式模型通过状态机解析 `<thinking>...</thinking>` 标签，标签内内容作为 `thinking` 事件产出，标签外作为 `content` 事件；(3) 后处理：处理了标签部分到达的边界情况（如 `"<think"` 在 buffer 末尾等待更多字符）。 |
| 105-112 | SSE 行解析 — 跳过空行、去除 `data:` 前缀、识别 `[DONE]` 结束标记。 |
| 145-165 | `in_thinking_block` 状态机 — 诱导式思考解析的核心。`idx = buffer.find("<thinking>")` 查找开始标签，`idx = buffer.find("</thinking>")` 查找结束标签。边界情况处理：当 `"<think"` 在 buffer 末尾 9 字符内且未闭合时 `break` 等待更多字符；`"</think"` 同理。 |
| 172-203 | `generate_sync(messages)` — 非流式单次生成。用于辅助调用（如图片分析）。关闭 stream，移除 reasoning_effort 字段和诱导思考提示，因为非流式不需要解析 `<thinking>`。 |
| 206-228 | `extract_json(text)` — 从 LLM 输出中提取第一个 JSON 对象。处理了三种常见情况：(1) ```` ```json ``` ```` 代码块包裹；(2) 从文本中定位第一个 `{` 到匹配的 `}`；(3) 大括号不匹配时报错。这个函数在多个模块中被复用。 |

**设计要点:**
- 思考深度通过配置映射表抽象，支持多种推理策略（原生 reasoning_effort / 诱导式提示词 / 关闭）
- 流式解析的状态机处理了标签部分到达的边界情况
- 与 OpenAI 兼容 API 完全兼容，可切换到任何兼容网关

---

### 5.4 hmi_ir.py

**文件路径:** `backend/hmi_ir.py` (471行)  
**角色:** HMI IR 的校验、归一化、自动排版。是整个管线的质量关卡。

| 行号 | 分析 |
|------|------|
| 18-28 | 定义了项目中的所有合法枚举值：`VALID_OBJECT_TYPES`（5种控件类型）、`VALID_MODES`（3种模式）、`VALID_FORMATS`（4种格式）、`VALID_DATATYPES`（6种数据类型）、`VALID_HMI_TYPES`（3种 HMI 类型）、`VALID_RES`（7种常见分辨率）。 |
| 31-32 | `IRValidationError` — 自定义异常类，在 IR 不合法时抛出，携带描述性错误信息。 |
| 35-38 | `_req(d, key, where)` — 便捷函数，检查字典中是否存在必填字段，不存在则抛出带位置的描述性错误。 |
| 41-52 | `parse_resolution(value)` — 解析 `"800x480"` 格式的分辨率字符串，返回 `(width, height)` 元组或 None。支持大小写不敏感。 |
| 55-66 | `_bbox(o)` — 计算任意对象的包围盒 `(x1, y1, x2, y2)`。Indicator 类型的包围盒以 `(x, y)` 为圆心向四周扩展半径计算。 |
| 69-77 | `_move_to_bbox(o, x1, y1)` — 将对象移动到指定的左上角。Indicator 需将圆心移动到 `(x1+r, y1+r)`。 |
| 80-85 | `_is_title_text(o)` — 判断对象是否为标题文本。判断依据：类型为 Text 且 bold=true / font_size≥22 / id 为 "TXT_Title"。 |
| 88-109 | 间距常量函数。`_min_h_gap(a, b)` 返回两控件间最小水平间距（按钮间24px、指示灯间24px、含文本的12px、默认20px）。`_min_v_gap(prev_row, next_row)` 返回行间最小垂直间距（含按钮的22px、默认18px）。 |
| 120-136 | `_cluster_rows(objs, tolerance=26)` — 将对象列表按行聚类。先按 `(y, x)` 排序，再按中心 y 坐标分组（容差26px）。每行内按 x 排序，行间按 y 排序。 |
| 139-249 | `_optimize_layout(ir)` — **自动排版核心函数**。执行一系列启发式布局优化：(1) 标题规范化：居中并吸附到顶部安全区域；(2) 分离标题和非标题控件；(3) 逐行聚类；(4) 行内水平对齐+最小间距修复：如果两控件间距不足，将后者推远；(5) 行宽越界修正：整行左移；(6) 行间垂直间距拉开；(7) 多轮全局重叠修复（最多3轮）：后出现的对象向下避让；(8) 最终边界裁剪。完成后在 `_warnings` 中添加提示并在 IR 中标记 `_layout_optimized = True`。 |
| 252-413 | `validate_ir(ir)` — **IR 校验主函数**。执行流程：(1) 类型检查；(2) meta 字段默认值补全（screen_name→"Screen_1"、resolution→"1280x800"等）；(3) resolution 和 hmi_type 的合法性验证与回退；(4) generation_mode 和 template 字段处理；(5) tags 校验：name 必填、data_type 合法性检查、归一化 output；(6) text_lists 校验：name 必填、entries 归一化；(7) scripts 校验：name 必填；(8) objects 校验（核心）：类型合法、ID唯一（冲突时追加索引）、坐标范围警告、各对象类型的必填字段和可选字段处理（IOField 的 display_format/decimal_digits/unit、SymbolicIOField 的 text_list 引用、Button 的脚本事件引用、Indicator 的 color/blink、Text 的 font_size/bold/color）；(9) 交叉引用检查：process_tag 是否在 tags 中声明、text_list 是否在 text_lists 中声明、脚本事件引用的脚本是否存在。最后设置 `_screen_size` 和 `_warnings`，调用 `_optimize_layout()` 后返回。 |
| 416-470 | `scale_ir_to_resolution(ir, target_resolution, in_place=False)` — 将 IR 的坐标系统一缩放到目标 HMI 分辨率。分别对 `x/y`（按宽高比缩放）、`width/height/radius`（按比例缩放且保证最小1px）、`font_size`（按比例缩放且保证最小10px）处理。支持原地修改或返回新对象。 |

**设计要点:**
- 校验与排版一体化：`validate_ir` 不仅是"检查是否合法"，还会自动补全默认值、修复常见问题、执行自动排版
- 启发式布局优化：`_optimize_layout` 使用多次迭代逐步收敛（水平对齐→垂直间距→重叠修复→边界裁剪）
- 宽容的校验策略：不合法的值会被回退到默认值并产出警告，而非直接抛异常（除非是致命错误如 objects 为空）

---

### 5.5 simaticml_generator.py

**文件路径:** `backend/simaticml_generator.py` (680行)  
**角色:** 将校验后的 IR 转换为 SimaticML 命名空间的 XML 字符串，用于通过 Openness 导入到 TIA Portal。

| 行号 | 分析 |
|------|------|
| 8-23 | **版本说明文档字符串** — 这是整个项目中最关键的工程说明之一。指出：SimaticML 在不同 TIA 版本(V16/V17/V18/V19)和不同 HMI 类型(Basic/Comfort/Unified)间的精确元素名/命名空间存在差异。推荐做法：在博途中手工创建样例画面并导出 XML 来观察真实结构。 |
| 25-31 | 导入依赖：`uuid` 生成唯一ID、`xml.etree.ElementTree` 用于 XML 构建、`xml.sax.saxutils.escape` 转义特殊字符。三个项目内模块：`TextNormalizer` 清洗文本、`MultilingualTextBuilder` 构建标准多语言文本节点、`XmlValidator` 最终校验。 |
| 35 | `SIMATICML_NS = "http://www.siemens.com/automation/SimaticML"` — Comfort 面板的默认命名空间。 |
| 38-51 | 工具函数。`_color_to_argb(hex)` 将 `#RRGGBB` 转为 `"R,G,B"` 的 WinCC 颜色格式（WinCC 用的是十进制分量字符串，不是十六进制）。`_attr_str(attrs)` 将属性 dict 转为 XML 属性字符串。`_elem(name, attrs, text)` 构建自闭合或包含文本内容的 XML 元素字符串（含 XML 转义）。注意注释：用户可见文本应使用 `_multilingual_text_elem()` 而非此函数。 |
| 69-86 | `_multilingual_text_elem(text, language)` — **关键函数**：生成符合 TIA Portal 标准的 MultilingualText 节点。委托给 `MultilingualTextBuilder.build_string()` 用 DOM 构建，保证 XML 结构正确性。TIA 正确格式必须是 `<MultilingualText><Text Language="zh-CN">安全文本</Text></MultilingualText>`。 |
| 90-258 | 对象→XML 转换函数组。每个函数返回 XML 行列表（无缩进，由外层 `_ind()` 统一处理）：`_geo_lines()` 生成 Geometry 子元素（X/Y/Width/Height）。`_io_field_lines()` 生成 IOField ScreenItem，含 Properties（Mode/OutputFormat/DecimalDigits/FontSize）和 Connection（ProcessTag）。`_symbolic_io_field_lines()` 类似但含 TextList 引用。`_button_lines()` 含 Text 子元素（用 MultilingualText 包裹）、BackColor 属性和可选的 Press/Release/Click Events。`_indicator_lines()` 生成 Circle 控件，含 FillColor/BorderColor 和 Animations（ColorAnimation Range 0/1 + 可选的 FlashAnimation）。`_text_lines()` 生成 TextField 控件，含 Text/FontSize/Bold/ForeColor。`_label_lines()` 和 `_unit_lines()` 为对象生成左侧标签和右侧单位文本。 |
| 252-258 | `_DISPATCH` — 类型→转换函数的映射字典，实现策略模式。 |
| 261-278 | `_ind(prefix, lines)` — 缩进处理函数。递归展平嵌套的行列表并在每行前添加前缀缩进。 |
| 281-389 | `_extract_template_info(ref_xml)` — **模板匹配核心**。从博途导出的参考画面 XML 中提取命名空间、结构信息和 Screen 的父级标签链。使用正则和逐行分析来获取：(1) Document 元素的 xmlns；(2) Screen 元素的父级标签链（如 TIA V16 Comfort 的 `SW.Blocks > SW.ScreenFolder > Screen`）；(3) Screen 的额外属性；(4) 对象容器元素名（ObjectList / ScreenItems / ScreenItemList）。这让生成的 XML 能匹配用户实际使用的 TIA 版本和 HMI 类型。 |
| 392-404 | `generate_simaticml(ir, tia_version, reference_xml)` — 公共入口。如果提供了 reference_xml 则提取模板信息，然后调用内部 `_generate()`。 |
| 407-540 | `_generate(ir, tia_version, tmpl)` — **XML 生成主函数**。流程：(1) 提取 meta 信息（hmi_type/screen_name/title/resolution）；(2) 应用模板的命名空间和结构信息；(3) 生成 XML 声明和 Document 根元素；(4) 生成 Screen 父级标签（如有）；(5) 生成 Screen 元素及其 AttributeList；(6) 生成 Tags（变量声明）；(7) 生成 TextLists（文本列表）；(8) 生成对象容器内的各控件（Base 面板模式下按钮的 VBS 事件被清除）；(9) 生成 VBScripts（Base 面板下跳过）；(10) 闭合标签；(11) 通过 XmlValidator 校验并尝试自动修复。 |
| 547-680 | **TIA XML 校验与修复**。`validate_tia_xml(xml_content)` 委托给 `XmlValidator.validate()` 返回校验结果。`repair_tia_xml(xml_content)` — **三阶段修复流水线**：Step 1: 文本级 HTML 清洗+控制字符移除（TextNormalizer）；Step 2: 删除 `<Number>` 节点（ScreenNumberAllocator）；Step 3: DOM 级 MultilingualText 标准重建（`_rebuild_multilingual_text_dom`）。`_rebuild_multilingual_text_dom()` 使用 ElementTree 解析 XML，遍历所有 MultilingualText 元素并调用 `MultilingualTextBuilder.rebuild_element()` 重建为标准结构。 |

**设计要点:**
- 模板匹配机制：通过解析博途导出的参考 XML，自动匹配命名空间和结构，避免硬编码版本差异
- 命名空间和带点标签名的兼容处理（`Hmi.Screen.IOField` vs `{ns}IOField`）
- Fail Fast 策略：修复后再次校验，错误依然存在时仍返回 XML（而非丢弃），由调用方决定是否导入
- Base 面板特殊处理：禁用 VBS 脚本事件

---

### 5.6 openness_manager.py

**文件路径:** `backend/openness_manager.py` (2155行)  
**角色:** 项目最长的文件。通过 pythonnet 加载 Siemens.Engineering.dll，管理 TIA Portal 的连接、画面查找、XML 导入导出、以及 Unified 面板的直接控件创建。

| 行号 | 分析 |
|------|------|
| 17-28 | 延迟导入 `clr`(pythonnet)，非 Windows 环境优雅降级。 |
| 31-38 | `OpennessManager.__init__()` — 从配置中提取 openness、output 和 hmi_defaults 节。维护 `_portal`（TIA Portal 进程引用）、`_project`（项目引用）、`_tia`（命名空间引用）三个内部状态。 |
| 41-77 | `diagnose()` — 环境诊断。检查项：操作系统（需 Windows）、pythonnet 是否安装、Siemens.Engineering.dll 是否存在、是否有运行中的 TIA Portal 进程（使用 Windows `tasklist` 命令）。`ready` 状态仅在 Windows + pythonnet + DLL 存在时返回 True。 |
| 80-123 | `connect()` — 附加到运行中的 TIA Portal 实例。使用 `TiaPortal.GetProcesses()[0].Attach()` 附加到第一个进程（或通过 `TiaPortalMode.WithUserInterface` 启动新实例）。然后获取已打开的项目（通过项目路径打开或取第一个已打开项目）。 |
| 132-300 | `_preprocess_xml_for_import(xml_content, hmi_software)` — **导入前预处理管线（5步）**。Step 1: 文本级清洗（TextNormalizer）；Step 2: DOM 级 MultilingualText 重建；Step 3: 删除 `<Number>` 节点；Step 3.5: 画面尺寸保护（`_align_xml_screen_size_to_hmi` 对齐到目标 HMI 分辨率）；Step 4: 画面名称冲突检测（重名时自动追加时间戳后缀）；Step 5: XML Lint 最终扫描（XmlValidator 闸门）。 |
| 305-457 | **画面尺寸处理**。`_local_xml_tag()` 提取 ElementTree 元素的本地名。`_parse_resolution_text()` 解析多种分辨率格式（`800x480` / `800*480` / `800,480`）。`_extract_screen_size_from_xml()` 从 Screen 的 AttributeList 直接读取 Width/Height。`_set_screen_size_in_xml()` 修改 Screen 的 Width/Height 并可选择按比例缩放所有控件坐标。`_scale_screen_items()` 缩放 ScreenItems 的 Left/Top/Width/Height/Radius。`_resolve_hmi_screen_size()` 采用三级优先级获取目标 HMI 尺寸：显式配置 > 已有画面的 Width/Height 属性 > 导出第一个已有画面并解析其 XML。 |
| 535-589 | `_detect_screen_number_conflicts()` — 检测 screen number 冲突。从已有画面收集已用号码，与 XML 中的 Number 比较，自动建议下一个可用号码。 |
| 594-642 | `_import_to_screens()` — **统一导入封装（稳定版）**。严格执行 Openness 规范：(1) 唯一允许的导入方式：`Screens.Import(FileInfo, ImportOptions.Override)`；(2) 禁止 `ScreenComposition.Import` / InvokeMember 反射 / ASCII hack；(3) 每次重新获取对象链避免 disposed object。如果唯一方式失败，Fail Fast 而非尝试补救方案。 |
| 645-697 | `_find_hmi_software()` — **HMI 设备定位**。遍历 `Project.Devices > Device.DeviceItems`，对每个 DeviceItem 尝试获取 `SoftwareContainer.Software`，匹配类型名包含 "Hmi" 的软件对象。支持按配置中的 `hmi_device` 名称过滤（Name/DeviceName/TypeIdentifier/OrderNumber 任一匹配即可）。 |
| 700-733 | `_detect_classic_hmi_family()` — 区分经典 HMI 的 Basic / Comfort / Classic 子类型。综合用户配置 `hmi_type` 和设备属性字符串（Name/TypeIdentifier/OrderNumber 等）判断。 |
| 736-806 | `export_reference_screen(screen_name)` — 从 HMI 设备导出一个画面作为格式参考。查找画面→统一导出封装（多次尝试策略）→读取 XML→清理临时文件→返回 XML 内容和元信息。 |
| 809-902 | `import_screen(xml_path)` — **导入 SimaticML XML 到 HMI 画面文件夹**。核心流程：(1) 重新获取 `_find_hmi_software()` 避免 disposed object；(2) 读取并预处理 XML（5步管线）；(3) screen number 冲突检测；(4) 写入临时文件；(5) 重新获取对象链；(6) 定位目标 Screens 集合（支持子文件夹 Find/Create）；(7) 调用统一导入封装；(8) 清理临时目录；(9) 触发编译/保存（如配置）。 |
| 914-1013 | `get_hmi_capabilities()` — 返回当前 HMI 设备的能力信息。识别 Unified vs Classic（Basic/Comfort），推荐对应的生成模式（Unified→unified_direct / Classic→classic_template_xml / Basic→classic_template_xml 且需 Basic 专用模板）。列出已有画面列表。 |
| 1018-1110 | `export_screen_xml_template(screen_name, export_dir, overwrite)` — 导出指定画面为模板 XML。与 `export_reference_screen` 共享统一的导出封装。落盘到配置的 `template_export_dir`。 |
| 1115-1250 | `import_screen_xml(xml_path, screen_folder, import_option)` — 将通用 XML 画面文件导入到经典 HMI。支持子文件夹 Find/Create、多种 ImportOptions（Override/Rename/PreserveExisting）。 |
| 1255-1448 | `create_unified_screen_from_ir(ir)` — **Unified 直接绘制**（仅 Unified HMI）。通过 Openness 对象模型直接创建控件：(1) 查找或创建 Screen；(2) 如已存在且 `update_existing_screen=true` 则清空已有对象；(3) 遍历 IR objects 按类型映射创建 Unified 控件；(4) 设置 Name/Left/Top/Width/Height/Text/ProcessValue/BackColor 等属性。支持 `unsupported_object_policy`（warn/error/skip）策略。 |
| 1453-1643 | `import_or_generate_from_ir(ir, mode)` — **统一路由入口**。根据 `mode` 参数（auto/unified_direct/classic_template_xml/simaticml）和 HMI 能力自动选择生成路线。Auto 模式按优先级：Unified→unified_direct、Classic→classic_template_xml、否则→simaticml。每种模式都有回退机制：unified_direct 非 Unified 时回退到 classic_template_xml 或 simaticml；classic_template_xml 模板路径无效时回退到 simaticml（Basic 面板除外——不回退以避免生成不兼容格式）。 |
| 1648-1983 | `_export_screen_to_file(screen, xml_path)` — **统一导出封装**（核心修复）。使用6种逐级降级策略尝试导出：(1) 直接 `screen.Export(FileInfo, ExportOptions.WithDefaults)`；(2) 单参数 `screen.Export(FileInfo)`；(3) `.NET InvokeMember` 用 Binder 绕过 pythonnet 重载解析；(4) 遍历所有 Export MethodInfo 用 `MethodInfo.Invoke` 调用；(5) 搜索替代导出方法（SaveAs/ExportToFile 等）。支持删除已有文件后再导出（TIA V16 的 ExportOptions.WithDefaults 不允许覆盖）。 |
| 1988-2071 | **画面查找辅助**。`_find_screen_by_name()` 按名称查找画面（空名称返回第一个）。`_collect_screens()` 递归收集 ScreenFolder 中所有画面（含子文件夹），每次操作都有 try/except 保护因 pythonnet 的 .NET collection 特殊性。`_list_available_screens()` 列出所有画面名称。 |
| 2085-2155 | **模块级辅助函数**（Unified 用）。`_net_type_name()` 获取 .NET 类型名。`_try_get_attr()` / `_try_set_attr()` / `_try_call()` 安全操作 .NET 对象属性/方法。`_create_screen_item()` 尝试多个候选类型名创建 ScreenItem。`_hex_to_argb_int()` 颜色格式转换。 |

**设计要点:**
- 多层降级导出策略：解决 pythonnet 与 .NET 之间的重载解析问题
- 画面尺寸自动对齐：导入前检查并修正 XML 尺寸以匹配目标 HMI 设备，防止 TIA Portal 闪退
- 每次操作重新获取对象链：避免 .NET disposed object 引用失效
- 经典 HMI 子类型识别：Basic/Comfort 同属 Siemens.Engineering.Hmi，需要额外逻辑区分

---

### 5.7 pipeline_orchestrator.py

**文件路径:** `backend/pipeline_orchestrator.py` (344行)  
**角色:** 多阶段生成→审查→修正流水线的编排器。

| 行号 | 分析 |
|------|------|
| 32-47 | 辅助函数。`_target_resolution_from_config()` 从配置中提取目标 HMI 分辨率（显式 target_resolution > screen_resolution > hmi_defaults.resolution）。`_adapt_ir_to_target_resolution()` 缩放 IR 到目标分辨率。 |
| 50-94 | `_analyze_uploaded_images(images, requirement, mimo_cfg)` — 用 MiMo 分析用户上传的参考图片。最多分析前3张（避免 token 爆炸），调用 `analyze_with_mimo()` 获取视觉分析结果，提取 summary/parameters/controls/indicators/suggestions 并拼成文本返回。该文本会被拼入 LLM 的 prompt 中作为上下文。 |
| 97-115 | `_safe_review(ir, mimo_cfg)` — 安全审查。先将 IR 渲染为 PNG，将 PNG 转为 base64，再调用 MiMo 视觉审查。渲染失败时返回错误 dict 而非抛异常。 |
| 118-128 | `_summarize_review_for_sse(review_result)` — 将完整审查结果精简为前端友好的 SSE 数据（只保留 pass/score/categories/summary/critical_issues/suggestions）。 |
| 130-343 | `run_pipeline(...)` — **流水线主函数**。这是一个 Generator，yield SSE 事件元组。状态机流程：<br>**(1)** `pipeline_start` 事件，告知前端最大迭代次数；<br>**(2)** 可选 `image_analysis_start`/`image_analysis_result`，用 MiMo 分析上传图片；<br>**(3)** `generate_start` + `thinking/content/parsed_ok`，Stream 1 初始生成；<br>**(4)** `review_start` + `review_progress` + `review_result`，视觉审查；<br>**(5)** 若审查通过→`review_pass` + `pipeline_done`；<br>**(6)** 若达到最大迭代→`pipeline_done`（附最优结果）；<br>**(7)** 否则→`regenerate_start`→回到步骤3（修正轮次）；<br>**(8)** 每轮修正后重新 adapt resolution + sanitize text。 |
| 182-197 | 初始生成阶段 — 将目标分辨率注入 LLM prompt（如果配置了的话），保证生成的坐标系统与目标 HMI 一致。 |
| 235-280 | 审查-修正循环 — 核心循环逻辑。最多 `max_iterations` 轮，每轮执行审查→判断是否通过→未通过且未达最大轮次则进入修正。修正使用 `build_messages(..., review_context=...)` 将审查反馈作为上下文传入。 |
| 282-312 | 修正阶段 — `regenerate_start` 携带本轮的前5个关键问题，供前端展示。修正 LLM 调用同样通过 SSE 流式推送 thinking/content。 |

**设计要点:**
- Generator 模式：整个流水线是单个 Python Generator，通过 `yield (event, data)` 推送 SSE 事件
- 审查门控：`pass_threshold`（默认70分）作为通过/不通过的分界线
- 最大迭代次数保护：防止审查-修正循环无限进行
- 分辨率注入：初始生成时将目标分辨率拼入 prompt，避免 IR 使用默认分辨率导致后续需要缩放

---

### 5.8 preview_renderer.py

**文件路径:** `backend/preview_renderer.py` (300行)  
**角色:** 将校验后的 IR 渲染为 PNG 预览图像，供 MiMo 进行视觉审查。

| 行号 | 分析 |
|------|------|
| 26-40 | `_DEFAULT_FONT_PATHS` — 跨平台字体路径列表。Windows 优先使用 Microsoft YaHei（微软雅黑，支持中文），Linux 使用 NotoSansCJK，macOS 使用 PingFang。 |
| 43-48 | `_hex_to_rgb(hex_color)` — `#RRGGBB → (R, G, B)` 元组。 |
| 51-55 | `_contrast_color(bg_hex)` — 根据背景色亮度返回对比前景色（黑 `#06281F` 或白 `#FFFFFF`）。使用标准亮度公式 `0.299R + 0.587G + 0.114B`。 |
| 58-87 | `_get_font(size, bold)` — **字体缓存函数**。缓存键为 `(size, bold)`。遍历字体路径列表尝试加载 TrueType 字体，全部失败则回退到 Pillow 默认字体。 |
| 94-128 | **五种对象的绘制函数**。`_draw_text()` 直接在画布上绘制文本。`_draw_label()` 将标签文本右对齐放置在对象左侧。`_draw_io_field()` 绘制带蓝色边框的圆角矩形 + 示例值文本（String→"ABC" / 其他→"123"）+ 右侧单位文本。`_draw_symbolic_io_field()` 绘制带紫色边框的圆角矩形 + "〔列表〕"文本 + 下拉三角。`_draw_button()` 绘制带填充色的圆角按钮 + 文字（自动选对比色），有脚本事件时在右上角加小圆点标记。`_draw_indicator()` 绘制指示灯（填充圆 + 左上高光反光 + 可选闪烁虚线环）。 |
| 247-253 | `_DRAW_DISPATCH` — 类型→绘制函数的映射字典。 |
| 260-299 | `render_ir_to_png(ir)` — **主入口**。检查 IR 包含 `_screen_size` 和 objects 非空，创建 RGB 图像（使用 meta.background_color 作为背景色），遍历所有对象调用对应的绘制函数，最后保存为 PNG 字节流返回。 |

**设计要点:**
- 跨平台字体支持：自动从多个候选路径加载，保证 Linux/macOS 上也能渲染中文
- 颜色对比度自动计算：亮色背景上使用暗色文字，暗色背景使用亮色文字
- 仅用于视觉审查，非 WYSIWYG 精确预览

---

### 5.9 mimo_client.py

**文件路径:** `backend/mimo_client.py` (324行)  
**角色:** 调用 Xiaomi MiMo 视觉 API 进行 HMI 预览图审查。

| 行号 | 分析 |
|------|------|
| 20-22 | `SUPPORTED_MIME_TYPES` — MiMo 支持的图片格式。 |
| 25-32 | `MIMO_SYSTEM_PROMPT` — 英文系统提示，要求 MiMo 作为"precise multimodal visual perception engine"返回忠实观察。 |
| 35-45 | `SCHEMA_HINTS` — 9种输出模式（brief/detailed/ocr/chart/table/ui/drawing/compare/custom）对应的提示词。 |
| 48-135 | **图片处理工具函数**。`_guess_mime_type()` 基于文件扩展名推断 MIME 类型。`_path_to_data_url()` 将本地文件转为 base64 data URL。`_base64_to_data_url()` 标准化 base64/URL。`_resize_image_if_needed()` 用 Pillow 等比缩放超大图片（超过 `max_dimension` 时），避免 token 浪费。`_image_to_content_part()` 统一将各种图片输入格式转为 MiMo API content part。 |
| 136-160 | `_build_user_text(task, output_schema, language)` — 为 MiMo 构建中文任务描述，包含输出 Schema 提示和推荐 JSON 结构。 |
| 163-184 | `_safe_parse_json(text)` — 从 MiMo 输出安全解析 JSON。失败时返回包装 raw_text 的兜底结构。 |
| 187-196 | `_extract_usage(raw)` — 从 MiMo 响应中提取 token 用量统计。 |
| 203-323 | `analyze_with_mimo(images, task, output_schema, config, language)` — **主入口函数**。验证配置和 API Key→验证 images 参数→构建 content parts（图片+文本）→POST 请求→错误分类（auth/network/api/bad_input）→解析结果。返回统一的结构：成功时 `{ok, model, task, visual_result, raw_text, usage}`，失败时 `{ok: false, error_type, message, retryable}`。 |

**设计要点:**
- 错误分类和重试标记：`error_type` 区分 auth/network/api/bad_input，`retryable` 标记是否可重试
- 图片自动缩放：防止超大图片导致 token 爆炸
- 输出解析兜底：JSON 解析失败时返回原始文本而非抛异常

---

### 5.10 review_prompts.py

**文件路径:** `backend/review_prompts.py` (232行)  
**角色:** 审查与修正提示词模板。

| 行号 | 分析 |
|------|------|
| 15-27 | `SIEMENS_COLOR_REFERENCE` — Siemens HMI 标准色参考：绿色`#27D17F`(运行/正常)、红色`#E25563`(故障/停止)、青色`#14E0B1`(一般状态)、深灰`#3A4250`(关闭)、浅色文字`#E6EDF3`、深色按钮文字`#06281F`、深色背景`#1F2630`、蓝色边框`#2A86FF`(IO域)、紫色边框`#8A5CFF`(符号IO域)。 |
| 29-109 | `HMI_REVIEW_TASK` — **审查主任务提示词**。定义了6个评估维度：layout_alignment（布局清晰度与对齐）、component_sizing（组件尺寸与间距）、color_conventions（颜色规范）、text_readability（文字可读性）、completeness（元素完整性）、professional_quality（专业质量）。每个维度有pass/issues结构。输出格式为严格JSON：`{pass, score, categories, summary, critical_issues, suggestions}`。score分级：90+优秀、70-89合格、50-69需改进、<50不合格。 |
| 112-135 | `IMAGE_ANALYSIS_TASK` — 参考图片分析任务。提取参数/变量、控制元素、状态指示、布局风格、特殊图形元素、HMI设计建议。 |
| 137-151 | `REGENERATION_SYSTEM_ADDENDUM` — 修正模式的系统提示补充。9条修正原则。 |
| 154-196 | `build_review_feedback_text(review_result)` — 将 MiMo 审查的 JSON 结果转换为结构化的中文反馈文本。按层级组织：审查结果→关键问题→各维度问题→改进建议。 |
| 199-231 | `build_regeneration_messages(requirement, previous_ir, review_result)` — 构建修正模式的完整 messages 列表。 |

---

### 5.11 template_xml_generator.py

**文件路径:** `backend/template_xml_generator.py` (1000行)  
**角色:** 经典 HMI 模板 XML 改写。用 IR 中的信息安全替换模板 XML 中的文本/坐标/颜色/变量等字段。

| 行号 | 分析 |
|------|------|
| 31-37 | `_PREFIX_TYPE_MAP` — 对象ID前缀到类型的映射（TXT_→Text、BTN_→Button等）。 |
| 40-63 | `_XML_TAG_TO_IR_TYPE` / `_IR_TYPE_TO_XML_TAG` — TIA V16 Comfort 面板的 XML 标签与 IR 类型的双向映射。注意：Circle→Indicator(指示灯)、Ellipse→Indicator(仅圆形被当作指示灯)。 |
| 73-87 | `_local_tag(elem)` — 提取元素的本地标签名，兼容三种格式：命名空间（`{ns}Tag`）、点分隔（`Hmi.Screen.Tag`）、纯标签。 |
| 102-218 | `generate_from_template_xml(ir, template_xml, options)` — **主入口**。处理流程：(1) 检测并注册命名空间；(2) 解析模板 XML；(3) 提取 IR 的源分辨率和模板尺寸；(4) 改写画面名称（默认保留模板尺寸以避免 target HMI 分辨率不匹配）；(5) 如果 IR 分辨率与模板不同，按比例缩放控件坐标；(6) 遍历 IR 对象匹配模板控件（按 template_ref > id > 名称前缀 > 类型映射 > 模糊前缀 的优先级）；(7) 模板控件不足时自动克隆同类型控件；(8) 将 IR 对象属性应用到匹配的模板控件；(9) 检测未使用的模板控件并发出提醒；(10) 序列化回 XML 字符串。 |
| 225-275 | **命名空间与序列化**。`_detect_namespace()` 从 XML 中提取命名空间映射。`_element_to_string()` 序列化 ElementTree 并尽可能保留原始 XML 声明。 |
| 279-344 | **分辨率处理**。`_get_ir_screen_size()` 从 IR 读取坐标源分辨率。`_scale_objects_to_size()` 将 IR 对象坐标从源分辨率等比映射到模板尺寸。 |
| 350-423 | **Screen 节点操作**。`_find_screen_node()` BFS/DFS 查找 Screen 元素。`_get_screen_size()` 读取 Width/Height。`_set_screen_name()` 修改 Name/DisplayName。`_set_screen_size()` 修改 Width/Height。 |
| 429-613 | **控件遍历与匹配**。`_iter_candidate_screen_items()` 遍历所有可能的画面控件（TIA Comfort 实际标签名 + 通用标签名）。`_get_item_name()` 从多种格式（直接属性 Name、AttributeList→ObjectName、子元素 Name、深层 Name）提取控件名称。`_set_item_name()` 对应设置。`_build_item_name_map()` / `_build_item_type_map()` 构建名称/类型查找表。`_match_template_item()` — **5级优先级匹配**：template_ref > id 完全匹配 > 名称前缀(TXT_/BTN_) > IR→XML标签类型映射 > 模糊前缀。**关键修复**：按类型匹配时通过 `used_tags` 排除已用控件，避免 IR 的多个同类型对象（如3个按钮）反复覆盖同一模板控件。 |
| 620-897 | **属性修改辅助**。`_apply_object_to_item()` 将 IR 对象的名称/位置/尺寸/文本/变量连接/颜色/脚本事件应用到模板控件。`_set_position()` 设置 Left/Top(也尝试 X/Y)。`_set_item_text()` 按控件类型选择正确的 MultilingualText CompositionName（Button 优先 Text/TextOff/TextOn、TextField 优先 Text）。`_set_multilingual_text_by_composition()` 按 CompositionName 精准更新 V16 文本节点。`_set_tia_text_node()` 处理 TIA V16 的富文本格式（`<body><p>...</p></body>`）。`_set_process_tag()` 兼容 5 种不同的变量连接字段名。`_set_button_event()` 设置按钮的 Press/Release/Click 事件。`_set_nested_property()` 在子树中设置属性值（属性优先，后子元素，skip_help_text 避免误改帮助文字）。 |
| 913-999 | **克隆机制**。`_build_parent_map()` 构建 child→parent 映射。`_collect_existing_ids()` 收集所有 ID 属性。`_next_simatic_id()` 生成十六进制格式的新 ID。`_clone_template_item()` 深拷贝+唯一 ID。`_clone_matching_template_item()` 克隆同类型模板控件并插入到源控件的父节点中。 |

**设计要点:**
- 保留模板尺寸：默认不覆盖模板 XML 的 Screen Width/Height，避免与目标 HMI 分辨率不匹配
- 多级名称匹配：覆盖了 TIA V16 的各种命名格式（属性/子元素/深层元素/ObjectName）
- 控件克隆：解决模板中控件数量不足的问题（如模板只有1个按钮但 IR 需要3个）
- 帮助文字保护：`skip_help_text` 标志确保按钮标题不会误写入 HelpText

---

### 5.12 text_normalizer.py

**文件路径:** `backend/text_normalizer.py` (274行)  
**角色:** 导入管线第一层 — 清洗所有即将写入 TIA XML 的文本字段。

| 行号 | 分析 |
|------|------|
| 31-47 | `_FORBIDDEN_HTML_PATTERN` — 已知禁止的 HTML/Markdown 标签名的正则。包含约80+个 HTML 标签名。关键设计：**只匹配已知标签名，不使用通配 `<[^>]+>`**，因为通配会误删 XML 结构标签如 `<MultilingualText>`。 |
| 53 | `_ALLOWED_TIA_RICH_TAGS_IN_XML` — 在完整 XML 中允许的 TIA 合法富文本标签：`{body, p}`。WinCC Advanced/Comfort 的按钮文本显示属性合法使用 `<body><p>...</p></body>`。 |
| 57-65 | `_HTML_ENTITIES` — HTML 实体解码映射表（`&nbsp;`→空格、`&amp;`→`&`、`&deg;`→° 等常见的约20个实体）。 |
| 68 | `_ILLEGAL_CONTROL` — XML 1.0 禁止的控制字符范围 `[\x00-\x08\x0B\x0C\x0E-\x1F]`。 |
| 71-221 | `TextNormalizer` 类。`normalize(text)` — **9步文本清洗流水线**：(1)None→空字符串处理；(2)HTML实体解码；(3)数字实体解码（`&#NNNN;`）；(4)十六进制实体解码（`&#xHH;`）；(5)HTML注释去除；(6)已知HTML标签移除；(7)非法控制字符移除（保留tab/newline/carriage return后续统一）；(8)换行和制表符统一为空格；(9)连续空白压缩 + Trim。`normalize_xml_content(xml_string)` — 清洗完整 XML 字符串中的文本内容。与 `normalize()` 的区别：保留 TIA 合法的 `<body>`/`<p>` 标签（通过 `_replace_html_tag` 回调函数判断）。返回清洗后的 XML 和清理报告 `{html_removed, html_tags_found, controls_removed}`。`is_clean(text)` — 快速检查文本是否已清洗。`normalize_ir(ir)` — 遍历 IR 所有文本字段并清洗（meta/objects/tags/text_lists/scripts）。 |

**设计要点:**
- 安全正则：只匹配已知 HTML 标签名，避免破坏 XML 结构
- TIA 富文本保护：在完整 XML 上下文中保留 `<body>`/`<p>`
- 多层实体解码：命名实体→数字实体→十六进制实体

---

### 5.13 multilingual_text_builder.py

**文件路径:** `backend/multilingual_text_builder.py` (382行)  
**角色:** 导入管线第二层 — 构建和修复 TIA Portal 标准 MultilingualText DOM 节点。

| 行号 | 分析 |
|------|------|
| 18-27 | `MultilingualTextBuilder` 类。`SUPPORTED_LANGUAGES` 支持11种语言代码。`RICH_TEXT_COMPOSITIONS` 定义了需要富文本格式的 CompositionName：`{Text, TextOff, TextOn, Caption, DisplayText}`。 |
| 42-59 | `build(text, language)` — 构建通用 MultilingualText 片段。**关键修复**：不创建 `<ID>` 子元素。TIA 对象上 ID 应该是标签属性（如 `<MultilingualText ID="1">`），而不是子节点。 |
| 80-109 | `build_v16(text, mt_id, item_id, composition_name, language)` — 构建 TIA V16/Comfort 导出风格的 MultilingualText 节点。带 ObjectList→MultilingualTextItem→AttributeList→Culture+Text 的结构。`_set_v16_text_value()` 根据是否为富文本 composition_name 决定文本格式。 |
| 114-159 | `rebuild_element(mt_element)` — **就地修复核心**。处理三种情况：(1) TIA V16 结构→更新文本节点值+确保 Culture 存在；(2) 通用结构→确保 `<Text Language="...">` 存在且内容安全；(3) 兜底→根据元素属性判断按 V16 结构重建或通用结构补 Text。所有分支都先执行 `_remove_direct_id_children()` 清理可能存在的错误 `<ID>` 子节点。 |
| 170-209 | `validate_element(mt_element)` — 验证 MultilingualText。兼容 V16 和通用结构。检查禁止的 `<ID>` 子节点、缺少 Language 属性、空内容、未清洗的文本、缺少富文本格式等。 |
| 220-382 | 内部工具方法。`_local_tag()` 提取元素本地名（兼容命名空间和点分隔名）。`_extract_text()` 从 V16 或通用结构中提取文本内容。`_ensure_v16_culture()` 确保 MultilingualTextItem 有 Culture 子节点。`_rebuild_as_v16()` 完全重建 V16 结构。`_set_v16_text_value()` 根据 rich 标志写入纯文本或 `<body><p>...</p></body>` 富文本格式。`_derive_child_id()` 生成层级的十六进制 ID。 |

**设计要点:**
- ID 位置的正确性：ID 必须是 MultilingualText 元素的属性，不能是子元素（这是 TIA Portal 导入失败的常见原因之一）
- V16 富文本格式识别：按钮的 Text/TextOff/TextOn 需要 `<body><p>` 包裹，HelpText 不需要
- 非破坏性修复：`rebuild_element` 对 V16 结构只更新文本内容和 Culture，保留 ObjectList/MultilingualTextItem/CompositionName 和所有 ID 属性

---

### 5.14 xml_validator.py

**文件路径:** `backend/xml_validator.py` (330行)  
**角色:** 导入管线第四层（闸门）— 在导入前对 XML 进行结构化校验。

| 行号 | 分析 |
|------|------|
| 26-48 | `_HTML_PATTERN` — 与 TextNormalizer 相同的禁止 HTML 标签正则。`_ALLOWED_TIA_RICH_TAGS` 和 `_RICH_TEXT_COMPOSITIONS` 用于在校验时区分允许和禁止的标签。 |
| 51-78 | `ValidationResult` 数据类和 `XmlValidator` 类。`validate()` 方法串联5个检查项。`check_number_conflicts()` 检查 screen number 是否与已有画面冲突。 |
| 98-118 | `_check_html_tags()` — HTML 标签检查。遍历所有 HTML 标签匹配，忽略 TIA 合法的 `<body>`/`<p>`，统计禁止标签的个数和位置。 |
| 120-176 | `_check_multilingual_text()` — **MultilingualText 结构完整性检查（核心）**。使用 DOM 解析后：(1) 检查是否有非法 `<ID>` 子元素；(2) V16 结构检查：MultilingualTextItem 的 ID/CompositionName/Culture/Text 和富文本格式；(3) 通用结构检查：Text 子节点的 Language 属性和内容。DOM 解析失败时使用正则回退检查。 |
| 178-220 | `_check_v16_multilingual_text()` — V16 结构的详细检查：MultilingualTextItem 的 ID 属性、Culture 存在性、Text 内容无 HTML、富文本 CompositionName 需要 body/p 标签。 |
| 222-259 | `_check_control_chars()` — 控制字符检查。`_check_number_nodes()` — Number 节点检测（建议删除让 TIA 自动分配）。`_check_root_elements()` — 根元素和 Screen 节点存在性检查。 |
| 275-329 | 静态工具方法。`_html_tag_name()` 提取标签名。`_has_rich_body_p()` 检查是否包含 body 和 p 子元素。`_local_tag()` 本地名提取。`_is_v16_multilingual_text()` 判断是否为 V16 结构。`_approx_line()` 通过正则查找元素在 XML 文本中的近似行号。 |

**设计要点:**
- 闸门模式：任何校验失败都标记 `valid = False`，调用方据此决定是否阻断导入
- V16 与通用结构兼容：自动识别两种 MultilingualText 结构并适配对应的校验规则
- 正则回退：DOM 解析失败时用正则兜底

---

### 5.15 screen_number_allocator.py

**文件路径:** `backend/screen_number_allocator.py` (171行)  
**角色:** 导入管线第三层 — 管理 screen number 分配，防止导入冲突。

| 行号 | 分析 |
|------|------|
| 27-48 | `ScreenNumberAllocator` 类。支持两种分配策略：`compact`（最小空缺，如已用[1,2,5]→返回3）和 `max_plus_one`（max+1，如[1,2,5]→返回6）。维护 `_used_numbers`（已注册号码集合）和 `_reserved`（已分配但未最终确认的号码）。 |
| 50-76 | `register_existing(numbers)` — 注册已用的 screen numbers。`register_xml_numbers(xml_content)` — 从 XML 中通过正则 `<Number>N</Number>` 提取并注册所有号码。 |
| 78-109 | `allocate()` — 根据策略返回一个新的唯一号码。compact 从1开始找第一个未占用的号码。`_allocate_max_plus_one()` 使用 max+1 策略。 |
| 111-125 | `remove_number_nodes(xml_content)` — 用正则从 XML 中安全删除所有 `<Number>` 节点。**关键设计**：让 TIA Portal 自动分配 screen number，而非硬编码可能导致冲突的固定号码。 |
| 127-158 | `detect_conflicts(xml_content)` — 检测 XML 中的 screen number 是否与已注册号码冲突。返回冲突详情和建议的下一个可用号码。 |

**设计要点:**
- 紧凑分配策略：优先使用空隙号码，保持 screen number 列表紧凑
- 节点删除而非修改：删除 `<Number>` 节点让 TIA 自动分配，比指定新号码更可靠

---

### 5.16 import_engine.py

**文件路径:** `backend/import_engine.py` (409行)  
**角色:** 导入管线第五层（终端层）— 通过 Openness API 将校验通过的 XML 导入 TIA Portal。

| 行号 | 分析 |
|------|------|
| 31-62 | `ImportResult` 数据类。`to_dict()` 方法提供统一的外部接口格式（`imported/ok/method/screen_name/message/error/warnings/validation`）。 |
| 65-91 | `ImportEngine` 类。**分层设计**：(1)预处理层→(2)校验层(闸门)→(3)导入层。`VALID_OPTIONS = {"Override", "Rename"}` 仅允许这两种导入选项。 |
| 93-270 | `import_xml(xml_content, target_folder, import_option, compile_after, save_after)` — **完整导入管线**。Phase 1: 预处理（TextNormalizer 清洗 + MultilingualTextBuilder DOM 重建 + ScreenNumberAllocator 删除 Number + 画面尺寸自动对齐）；Phase 2: **闸门校验**（XmlValidator + screen number 冲突检查 → 不通过则 **Fail Fast** 直接返回错误 ImportResult）；Phase 3: 导入（唯一允许方式 `Screens.Import(FileInfo, ImportOptions)` + 写入临时文件 + 重新获取 HMI 软件对象 + 定位目标 Screens 集合 + 编译/保存）。 |
| 274-408 | 内部方法。`_normalize_option()` 规范化导入选项名称。`_rebuild_all_multilingual_text()` DOM 级重建（与 simaticml_generator 中的逻辑共享）。`_collect_existing_numbers()` 从已连接 HMI 收集已有 screen numbers。`_extract_screen_name()` 从 XML 提取画面名称（兼容 TIA V16 AttributeList 格式）。`_resolve_target_screens()` 定位目标 Screens 集合（支持子文件夹 Find/Create）。 |

**设计要点:**
- Fail Fast 哲学：校验不通过直接阻断，不允许"修一半继续导入"
- 单一导入方式：整个 ImportEngine 只使用 `Screens.Import(FileInfo, ImportOptions.Override)` 一种导入方式
- 清洁临时文件：finally 块确保临时目录被删除

---

### 5.17 tia_text_sanitizer.py

**文件路径:** `backend/tia_text_sanitizer.py` (144行)  
**角色:** 兼容层 — 将旧代码接口委托给新的管线模块。

| 行号 | 分析 |
|------|------|
| 21-23 | 文档说明核心功能已迁移到 `text_normalizer` / `multilingual_text_builder` / `xml_validator` |
| 24-41 | `_FORBIDDEN_HTML_TAGS` — 保留旧变量名引用（与 text_normalizer 中的相同）。 |
| 44-49 | `sanitize_tia_text(text)` — 委托给 `TextNormalizer.normalize()`。 |
| 52-57 | `sanitize_ir_text_fields(ir)` — 委托给 `TextNormalizer.normalize_ir()`。 |
| 64-70 | `lint_xml_content(xml_content)` — 委托给 `XmlValidator.validate()`。 |
| 73-118 | `_rebuild_multilingual_text_nodes(xml_content)` — 委托给 `MultilingualTextBuilder`。 |
| 121-143 | `lint_and_repair_xml(xml_content)` — 组合委托：TextNormalizer → ScreenNumberAllocator → MultilingualText 重建 → 重新校验。 |

---

## 6. 配置文件: config.yaml

**文件路径:** `config.yaml` (280行)  
**角色:** 全局应用配置。

### 配置节详解

| 节 | 字段 | 类型 | 说明 |
|-----|------|------|------|
| **llm** | `active_provider` | string | 活跃的 LLM 服务商（deepseek/openai_compatible） |
| | `thinking_depth` | string (关闭/低/中/高) | 模型推理深度 |
| | `stream` | bool | 是否使用流式输出 |
| | `show_thinking` | bool | 是否在 UI 展示思考过程 |
| | `providers.*` | dict | 服务商配置（base_url/api_key/model等） |
| **openness** | `tia_version` | string (V16/V17/V18/V19) | TIA Portal 版本 |
| | `dll_path` | path | Siemens.Engineering.dll 路径 |
| | `attach_running` | bool | 是否附加到已运行的博途实例 |
| | `project_path` | path | 项目路径（留空使用已打开项目） |
| | `hmi_device` | string | 目标 HMI 设备名 |
| | `generation_mode` | string (auto/unified_direct/classic_template_xml/simaticml) | 生成模式 |
| | `classic_template` | dict | 经典模板 XML 路线配置 |
| | `unified_direct` | dict | Unified 直接绘制路线配置 |
| **hmi_defaults** | `resolution` | string (WxH) | 默认 HMI 分辨率 |
| | `hmi_type` | string (Basic/Comfort/Unified) | 默认 HMI 类型 |
| | `background_color` | hex | 默认背景色 |
| **output** | `export_dir` | path | 导出目录 |
| | `encoding` | string (utf-8-sig) | 输出文件编码 |
| | `reference_xml` | string | 博途导出的参考 XML（用于 SimaticML 模板匹配） |
| **mimo** | `enabled` | bool | MiMo 视觉审查总开关 |
| | `api_key` | string | MiMo API Key |
| | `model` | string | MiMo 模型名 |
| | `max_iterations` | int | 审查-修正最大轮次 |
| | `review_pass_threshold` | int (0-100) | 审查通过最低分 |
| **server** | `host` | string | Flask 监听地址 |
| | `port` | int | Flask 监听端口 |
| | `debug` | bool | Flask 调试模式 |

---

## 7. 前端文件

### templates/index.html

单页应用（SPA）入口 HTML。加载 `static/css/style.css` 和 `static/js/app.js`。

### static/js/app.js

前端 Vue.js/原生 JS 应用，负责：
- 配置页（结构化编辑 / 原始 YAML 编辑）
- 需求输入（文本 + 文件上传）
- SSE 流式展示（思考过程 + 正文 + 提示）
- XML 预览与复制
- Openness 诊断 / 连接 / 导入控制面板
- 审查结果展示

### static/css/style.css

HMI 深色主题样式。使用 Siemens 标准色系（`#1F2630` 深色背景、`#E6EDF3` 浅色文字）。

---

## 8. 测试套件

### tests/test_flask_api.py (147行)

Flask API 端点测试（使用 `app.test_client()`）：

| 测试类 | 测试用例 | 验证内容 |
|--------|----------|----------|
| `TestConfigApi` | `test_get_config` | GET /api/config 返回 config 和 raw |
| | `test_get_config_has_generation_mode` | 配置含 generation_mode/classic_template/unified_direct |
| `TestOpennessApi` | `test_capabilities_endpoint_returns_json` | GET /api/openness/capabilities 返回正确结构 |
| | `test_diagnose_endpoint` | GET /api/openness/diagnose 返回 os/ready |
| | `test_export_template_endpoint_no_screen_name` | POST /api/openness/export-template 不崩溃 |
| | `test_export_reference_endpoint_returns_json` | /api/openness/export-reference 返回 JSON |
| | `test_status_endpoint` | 兼容 /api/openness/status |
| | `test_tia_status_endpoint` | 兼容 /api/tia/status |
| `TestBuildApi` | `test_build_template_xml_requires_ir` | 无 IR 返回 400 |
| | `test_build_template_xml_invalid_template_path` | 无效路径返回 400 |
| | `test_build_endpoint_with_valid_ir` | 旧 /api/build 可用 |
| | `test_import_endpoint_with_ir_and_mode` | 新导入模式可用 |

### tests/test_hmi_ir.py (115行)

IR 校验模块测试：

| 测试用例 | 验证内容 |
|----------|----------|
| `test_validate_ir_basic` | 基本 IR 正常通过 |
| `test_validate_ir_accepts_generation_mode` | 接受并归一化 generation_mode |
| `test_validate_ir_defaults_generation_mode` | 未提供时默认 auto |
| `test_validate_ir_invalid_generation_mode_falls_back` | 非法值回退到 auto |
| `test_validate_ir_accepts_template_fields` | 接受 template_screen/template_xml |
| `test_validate_ir_accepts_template_ref` | 对象接受 template_ref |
| `test_validate_ir_rejects_empty_objects` | 空 objects 抛异常 |
| `test_validate_ir_all_object_types` | 全部5种对象类型通过 |

### tests/test_openness_manager.py (216行)

OpennessManager 错误处理和诊断测试（不依赖实际 TIA 连接）：

| 测试类 | 关键测试 |
|--------|----------|
| `TestOpennessManagerDiagnose` | `diagnose()` 返回 dict 不崩溃、无效 DLL 路径有消息、未连接时 capabilities 有 warnings |
| `TestExportScreenToFile` | **关键测试**：验证 `_export_screen_to_file` **不传 str 给 `Screen.Export()`**（这是真实 bug 的回归测试）、导出失败时返回 attempts 列表 |
| `TestExportReferenceScreen` | 未连接时返回 ok=False + message |
| `TestExportScreenXmlTemplate` | 未连接时返回 ok=False 且始终有 warnings 列表 |
| `TestFindScreenByName` | 无 HMI 时返回 None、`_list_available_screens` 返回空列表 |

### tests/test_template_xml_generator.py (183行)

模板 XML 改写模块测试（使用模拟的 MINIMAL_TEMPLATE_XML）：

| 测试用例 | 验证内容 |
|----------|----------|
| `test_can_modify_screen_name` | 画面名称被正确改写 |
| `test_can_modify_text` | 文本对象内容被正确改写 |
| `test_can_modify_coordinates` | X/Y/Width/Height 被正确改写 |
| `test_can_modify_process_tag` | 变量连接被正确改写 |
| `test_unmatched_object_returns_warning` | 无匹配控件时返回 warning（使用模板中没有的 Indicator 类型测试） |
| `test_preserves_namespace` | 命名空间得以保留 |
| `test_preserves_original_structure` | SW.Blocks/SW.ScreenFolder/ObjectList 原始结构保留 |
| `test_empty_objects_no_crash` | 空对象列表不崩溃 |
| `test_broken_xml_returns_original` | 损坏 XML 返回原始字符串 |
| `test_match_by_prefix` | 按 TXT_ 前缀正确匹配文本控件 |
| `test_duplicate_template_refs_work` | 多对象引用同一模板不崩溃 |

---

## 9. 导入管线详解

TIA HMI XML 导入管线是整个项目最关键的架构设计之一，定义了 XML 在导入到 TIA Portal 前必须经历的5个处理层：

```
                    输入 XML
                       │
┌──────────────────────▼─────────────────────┐
│ 第1层: TextNormalizer                       │
│   • HTML标签识别与移除（仅限已知标签名）        │
│   • HTML实体解码 (&nbsp; → 空格)             │
│   • 数字/十六进制实体解码                     │
│   • 非法控制字符移除                          │
│   • 空白压缩与Trim                           │
│   输出: 清洗后的 XML 字符串                   │
└──────────────────────┬─────────────────────┘
                       ▼
┌──────────────────────▼─────────────────────┐
│ 第2层: MultilingualTextBuilder              │
│   • DOM级解析所有MultilingualText节点        │
│   • 安全重建为标准TIA结构                     │
│   • 移除错误的<ID>子元素                      │
│   • 确保Language属性和Culture存在             │
│   • 富文本vs纯文本格式判断                    │
│   输出: 标准MultilingualText结构的XML         │
└──────────────────────┬─────────────────────┘
                       ▼
┌──────────────────────▼─────────────────────┐
│ 第3层: ScreenNumberAllocator                │
│   • 正则删除<Number>节点                     │
│   • 检测已有画面号码冲突                      │
│   • 建议下一个可用号码                        │
│   输出: 无硬编码Number的XML                   │
└──────────────────────┬─────────────────────┘
                       ▼
┌──────────────────────▼─────────────────────┐
│ 第3.5层: 画面尺寸对齐（OpennessManager内）     │
│   • 提取XML中的Screen Width/Height           │
│   • 读取目标HMI设备实际尺寸                   │
│   • 不匹配时自动修改+缩放控件                  │
│   输出: 尺寸匹配目标HMI的XML                  │
└──────────────────────┬─────────────────────┘
                       ▼
┌──────────────────────▼─────────────────────┐
│ 第4层: XmlValidator（闸门）                  │
│   • HTML标签扫描（排除TIA合法富文本）          │
│   • MultilingualText结构完整性检查            │
│   • 控制字符检查                             │
│   • Number节点警告                           │
│   • 根Document/Screen元素存在性检查           │
│   • 校验不通过 → Fail Fast 阻断导入           │
│   输出: 校验报告 (ValidationResult)           │
└──────────────────────┬─────────────────────┘
                       ▼
┌──────────────────────▼─────────────────────┐
│ 第5层: ImportEngine（终端）                  │
│   • 仅使用: Screens.Import(FileInfo, ...)     │
│   • 写入临时文件 → 导入 → 清理                │
│   • 编译/保存项目（如配置）                    │
│   输出: ImportResult (成功/失败)              │
└─────────────────────────────────────────────┘
```

### 管线设计原则

1. **每层专注单一职责** — TextNormalizer 只管文本，MultilingualTextBuilder 只管结构，Allocator 只管编号
2. **闸门模式** — 第4层是最后防线，不通过则禁止进入第5层
3. **No Partial Fix** — 不允许"修一半继续导入"
4. **Fail Fast** — 尽早发现和报告问题
5. **Single Method** — 导入只允许 `Screens.Import(FileInfo, ImportOptions.Override)` 一种方式

---

## 10. 关键设计决策与模式

### 1. 中间表示 (IR) 模式

项目核心设计是 **需求 → LLM → IR JSON → SimaticML XML → TIA Portal** 的转换链。

IR（Intermediate Representation）是对 HMI 画面的结构化描述：
- 与具体 XML Schema 解耦（一次生成，多种导出）
- 便于校验（`validate_ir` 统一检查）
- 便于修改（审查反馈→修正 IR→重新生成 XML）
- 便于预览（`render_ir_to_png` 直接渲染）

### 2. 双路线生成策略

```
                ┌─ Unified 面板 → unified_direct (Openness 对象模型直接创建)
                │
IR ── mode ────┼─ Classic 面板 → classic_template_xml (改写博途导出的模板 XML)
                │
                └─ 兜底 → simaticml (从零生成 SimaticML XML)
```

### 3. Config Template Pattern

`DEFAULT_CONFIG` + `_deep_merge` 保证向前兼容：新增配置项有默认值，用户不需要手动更新配置文件。

### 4. Stream Generator Pattern

整个流水线使用 Python Generator + SSE：
- `run_pipeline()` 通过 `yield (event, data)` 推送状态
- `LLMClient.stream()` 逐块产出 `(kind, text)`
- Flask 用 `stream_with_context` + `Response(event_stream(), mimetype="text/event-stream")` 推送

### 5. MultilingualText 的脆弱性

TIA Portal 对 MultilingualText 格式极其敏感：
- ID 必须是元素属性，不能是子元素（否则报 "Cannot find the required 'ID' attribute element for the 'ID' element"）
- 按钮的 Text/TextOff/TextOn 需要 `<body><p>...</p></body>` 富文本格式
- 禁止 HTML 标签（`<div>`, `<span>` 等）混入 Text
- 这些是项目历史上最频繁的 bug，驱动了导入管线从 monolothic 重构为5层架构

### 6. pythonnet 与 .NET 互操作稳定性

`_export_screen_to_file` 的6级降级策略展示了 pythonnet 环境下的工程实践：
- pythonnet 的重载解析可能失败
- 需要直接使用 .NET InvokeMember/MethodInfo.Invoke
- 必须用 `Array.CreateInstance(SystemObject, n)` 构建参数数组

### 7. 启发式布局优化

`_optimize_layout` 不是精确的布局引擎，而是启发式的：
- 基于包围盒的行聚类
- 最小间距强制
- 重叠检测与避让（多次迭代）
- 边界裁剪
- 设计目标：让 LLM 生成的内容"看起来合理"，而非像素完美

---

## 附录: 文件清单

| 文件 | 行数 | 核心职责 |
|------|------|----------|
| `app.py` | 494 | Flask 主程序，15条路由 |
| `backend/config_manager.py` | 142 | 配置文件读写与线程安全 |
| `backend/prompts.py` | 374 | LLM 系统提示词 + Few-shot 示例 |
| `backend/llm_client.py` | 229 | LLM 流式/非流式调用客户端 |
| `backend/hmi_ir.py` | 471 | IR 校验 + 归一化 + 自动排版 |
| `backend/simaticml_generator.py` | 680 | IR→SimaticML XML 生成 |
| `backend/openness_manager.py` | 2155 | TIA Portal Openness 连接管理 |
| `backend/pipeline_orchestrator.py` | 344 | 生成→审查→修正 SSE 流水线 |
| `backend/preview_renderer.py` | 300 | IR→PNG 预览图渲染 |
| `backend/mimo_client.py` | 324 | MiMo 视觉 API 客户端 |
| `backend/review_prompts.py` | 232 | 审查与修正提示词 |
| `backend/template_xml_generator.py` | 1000 | IR→模板XML改写 |
| `backend/text_normalizer.py` | 274 | 管线第1层: 文本安全清洗 |
| `backend/multilingual_text_builder.py` | 382 | 管线第2层: MT节点构建 |
| `backend/xml_validator.py` | 330 | 管线第4层: 导入前校验闸门 |
| `backend/screen_number_allocator.py` | 171 | 管线第3层: 画面编号管理 |
| `backend/import_engine.py` | 409 | 管线第5层: 稳定导入终端 |
| `backend/tia_text_sanitizer.py` | 144 | 兼容层: 旧接口委托到新管线 |
| `config.yaml` | 280 | 全局配置文件 |
| `requirements.txt` | 25 | Python 依赖声明 |
| `tests/test_flask_api.py` | 147 | API 端点测试 |
| `tests/test_hmi_ir.py` | 115 | IR 校验模块测试 |
| `tests/test_openness_manager.py` | 216 | OpennessManager 错误处理测试 |
| `tests/test_template_xml_generator.py` | 183 | 模板XML改写测试 |

---

> **文档说明:** 本文档对 Siemens HMI 画面助手项目的全部 Python 源码进行了逐行分析。涵盖了15个后端模块、4个测试文件、配置文件和前端结构。重点解析了：LLM 提示词工程、IR 校验管线、SimaticML 生成、TIA Portal Openness 集成、5层导入管线架构、以及关键的工程实践（如 pythonnet/.NET 互操作性、MultilingualText 格式兼容性、启发式布局优化等）。

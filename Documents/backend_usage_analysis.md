# Siemens HMI Assistant — 后端模块完整分析文档

> 生成日期：2026-06-20
> 分析范围：所有 `backend/` 目录下的生产代码（共 60+ 个 Python 文件）

---

## 1. 总体架构概览

### 1.1 分层架构

Siemens HMI Assistant 后端采用**五层分层架构**，自顶向下依次为：

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. 入口/编排层 (Orchestration & Entry)                          │
│    pipeline_orchestrator.py, config_manager.py                  │
├─────────────────────────────────────────────────────────────────┤
│ 2. 生成/语义层 (Generation & Semantic IR)                       │
│    llm_client.py, prompts.py, review_prompts.py, mimo_client.py │
│    hmi_ir.py, variable_engine.py                                │
│    domain/ir_v2.py, domain/enums.py, ...                        │
├─────────────────────────────────────────────────────────────────┤
│ 3. 后端/代码生成层 (Backends & Code Generation)                 │
│    backends/classic/* (XML generation), backends/unified/*      │
│    simaticml_generator.py, template_xml_generator.py            │
│    preview_renderer.py                                          │
├─────────────────────────────────────────────────────────────────┤
│ 4. 管线/校验层 (Pipeline & Validation)                          │
│    text_normalizer.py, multilingual_text_builder.py             │
│    xml_validator.py, screen_number_allocator.py                 │
│    import_engine.py（⚠️当前未使用）, generation_summary.py        │
├─────────────────────────────────────────────────────────────────┤
│ 5. Openness/部署层 (TIA Portal Integration)                     │
│    openness_manager.py, session_manager.py, compiler.py         │
│    device_discovery.py, classic_executor.py, unified_executor.py│
│    services/deployment_service.py, services/verification_service│
│    planners/, capabilities/, references/                        │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 核心数据流

```
用户需求（中文自然语言）
      │
      ▼
  ┌─────────────────────────────────────────────────────────┐
  │ 1. LLM 生成 (llm_client + prompts)                      │
  │    用户需求 → LLM → JSON 格式 HMI IR（中间表示）         │
  └───────────────────────┬─────────────────────────────────┘
                          ▼
  ┌─────────────────────────────────────────────────────────┐
  │ 2. IR 校验与清洗 (hmi_ir.validate_ir)                   │
  │    布局自动优化、坐标归一化、交叉引用检查                │
  └───────────────────────┬─────────────────────────────────┘
                          ▼
  ┌─────────────────────────────────────────────────────────┐
  │ 3. 变量引擎绑定 (variable_engine)                       │
  │    自动推断变量名、数据类型、VBS 脚本生成                │
  └───────────────────────┬─────────────────────────────────┘
                          ▼
  ┌─────────────────────────────────────────────────────────┐
  │ 4. XML/画面生成 (simaticml_generator / template_xml)    │
  │    根据 HMI 类型(Basic/Comfort/Unified)生成 TIA XML     │
  └───────────────────────┬─────────────────────────────────┘
                          ▼
  ┌─────────────────────────────────────────────────────────┐
  │ 5. XML 校验管线 (text_normalizer → mt_builder →         │
  │    xml_validator，由 deployment_service 执行导入)        │
  └───────────────────────┬─────────────────────────────────┘
                          ▼
  ┌─────────────────────────────────────────────────────────┐
  │ 6. Openness 导入 (openness_manager)                     │
  │    Screens.Import(FileInfo, ImportOptions.Override)      │
  │    → 编译 → 验证 → 保存                                  │
  └─────────────────────────────────────────────────────────┘
```

### 1.3 可选的视觉审查反馈环路

```
  validate_ir → render_ir_to_png → MiMo 视觉审查
                                     │
                              ┌──────┴──────┐
                              ▼              ▼
                          通过            未通过
                          (结束)    → 修正 IR → 重新生成
                                    (最多 3 轮迭代)
```

---

## 2. 各模块详细说明（按功能分组）

---

### 2.1 入口层（app.py 直接导入）

#### 2.1.1 `pipeline_orchestrator.py` — 流水线编排器

| 项目          | 内容                                                                            |
| ----------- | ----------------------------------------------------------------------------- |
| **文件路径**    | `backend/pipeline_orchestrator.py`                                            |
| **核心职责**    | 将「生成 → 预览渲染 → MiMo 视觉审查 → 修正 → 再审查」串联为 SSE 事件生成器                              |
| **导出符号**    | `run_pipeline(requirement, extra_text, uploaded_images, config) -> Generator` |
| **被哪些模块调用** | Flask app 路由（SSE 端点）                                                          |

**详细说明：**

- `run_pipeline()` 是多阶段流水线的核心入口，接收用户需求、补充文本、上传图片和完整配置，yield `(event_name, data)` 元组供前端 SSE 消费
- 流水线状态机：`pipeline_start → [image_analysis] → generate_start → review_start → review_result → (review_pass → pipeline_done | regenerate_start → 回到 generate_start)`
- 内部辅助函数：
  - `_target_resolution_from_config(config)` — 从配置提取目标 HMI 分辨率
  - `_adapt_ir_to_target_resolution(ir, config)` — 将 IR 坐标系适配到目标分辨率
  - `_analyze_uploaded_images(...)` — 用 MiMo 分析上传的参考图片（最多前 3 张）
  - `_safe_review(ir, mimo_cfg)` — 安全执行 MiMo 视觉审查（渲染 → base64 → MiMo API）
  - `_summarize_review_for_sse(review_result)` — 将审查结果精简为前端友好格式
- 审查阶段支持最多 3 轮迭代修正，pass_threshold 默认 70 分

#### 2.1.2 `llm_client.py` — 大模型客户端

| 项目          | 内容                                                              |
| ----------- | --------------------------------------------------------------- |
| **文件路径**    | `backend/llm_client.py`                                         |
| **核心职责**    | 使用 OpenAI 兼容接口调用大模型（支持 DeepSeek/OpenAI 等），提供流式与非流式两种模式          |
| **导出符号**    | `LLMClient`（类）、`extract_json(text) -> dict`（函数）、`DEPTH_MAP`（常量） |
| **被哪些模块调用** | `pipeline_orchestrator.py`                                      |

**详细说明：**

- `LLMClient` 类：
  - `__init__(config)` — 从配置读取 active_provider、thinking_depth 等
  - `stream(messages)` — 流式生成器，yield `(kind, text)`；kind 可以是 `thinking`（推理过程）、`content`（正文）或 `error`
  - `generate_sync(messages)` — 非流式单次生成，返回完整响应文本
  - `_build_payload(messages)` — 根据 thinking_depth 选择 chat_model 或 reasoner_model，设置 reasoning_effort
- `extract_json(text)` — 从模型输出中提取第一个 JSON 对象，支持 ` ```json ``` ` 代码块包装，自动容错处理大括号匹配
- `DEPTH_MAP` — 思考深度映射字典：
  - `"关闭"`: use_reasoner=False
  - `"低"`: effort="low", hint_tokens=512
  - `"中"`: effort="medium", hint_tokens=1500
  - `"高"`: effort="high", hint_tokens=4000

#### 2.1.3 `prompts.py` — 内置提示词

| 项目          | 内容                                                                                                                                                                                                |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **文件路径**    | `backend/prompts.py`                                                                                                                                                                              |
| **核心职责**    | 定义系统级提示词，将中文自然语言需求转换为严格 JSON 格式的 HMI 中间表示 (IR)                                                                                                                                                    |
| **导出符号**    | `SYSTEM_PROMPT`, `IR_SCHEMA_DOC`, `TEXT_CONVENTIONS`, `TAG_CONVENTIONS`, `VBS_CONVENTIONS`, `LAYOUT_CONVENTIONS`, `JSON_SELF_CHECK`, `FEW_SHOT_USER`, `FEW_SHOT_ASSISTANT`, `build_messages(...)` |
| **被哪些模块调用** | `pipeline_orchestrator.py`                                                                                                                                                                        |

**详细说明：**

- `SYSTEM_PROMPT` — 核心系统提示词，定义 AI 角色为"西门子 WinCC/TIA Portal HMI 画面工程师"，包含 5 类对象（IOField/SymbolicIOField/Button/Indicator/Text）的生成约束
- `IR_SCHEMA_DOC` — 完整 IR JSON Schema 文档，定义 `meta/tags/text_lists/objects/scripts` 五层结构
- `TEXT_CONVENTIONS` — 文字与命名规范：面向操作员的文字使用简体中文、变量名使用英文下划线、命名前缀规则（LMP_/BTN_/IO_/SIO_/TXT_）
- `TAG_CONVENTIONS` — 变量绑定硬性规范：命名前缀规则（BTN_─瞬时按钮, MEM_─自保持, STS_─状态指示灯, LMP_─故障指示灯, IO_─数值 IO 域, SIO_─符号 IO 域）
- `VBS_CONVENTIONS` — VBS 脚本规范：使用 SmartTags/HMIRuntime.Tags，禁止死循环，Basic 面板减少复杂脚本
- `LAYOUT_CONVENTIONS` — 布局排版规范：分区（标题区/控制区/状态区/参数区）、边距、间距、对齐、禁止重叠越界等 11 条规则
- `JSON_SELF_CHECK` — 输出前自检清单（ID 唯一、引用完整、坐标在范围内、间距满足等 7 项）
- `FEW_SHOT_USER` / `FEW_SHOT_ASSISTANT` — 电机启停控制画面示例（含完整 IR JSON）
- `build_messages(user_requirement, extra_context, use_few_shot, review_context)` — 组装发送给 LLM 的消息列表；当 review_context 非空时自动切换为修正模式

#### 2.1.4 `hmi_ir.py` — HMI 画面中间表示校验

| 项目          | 内容                                                                                                                                                                                                                                                   |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **文件路径**    | `backend/hmi_ir.py`                                                                                                                                                                                                                                  |
| **核心职责**    | 对 LLM 产出的 JSON 做结构检查、补默认值、交叉引用校验，并执行轻量自动布局优化                                                                                                                                                                                                         |
| **导出符号**    | `VALID_OBJECT_TYPES`, `VALID_MODES`, `VALID_FORMATS`, `VALID_DATATYPES`, `VALID_HMI_TYPES`, `VALID_TAG_MODES`, `TAG_PREFIX_MAP`, `VALID_RES`, `IRValidationError`, `parse_resolution(...)`, `validate_ir(ir) -> dict`, `scale_ir_to_resolution(...)` |
| **被哪些模块调用** | `pipeline_orchestrator.py`, `openness_manager.py`                                                                                                                                                                                                    |

**详细说明：**

- `VALID_OBJECT_TYPES` — 合法对象类型：`{"IOField", "SymbolicIOField", "Button", "Indicator", "Text"}`
- `VALID_HMI_TYPES` — 合法 HMI 类型：`{"Basic", "Comfort", "Unified"}`
- `VALID_TAG_MODES` — 合法按钮模式：`{"momentary", "toggle"}`
- `TAG_PREFIX_MAP` — 对象类型到变量名前缀映射：`Button→BTN_`, `Indicator→STS_`, `IOField→IO_`, `SymbolicIOField→SIO_`
- `VALID_RES` — 标准分辨率：`{"1920x1080", "1280x800", "1024x768", "800x480", "480x272", "640x480", "320x240"}`
- `IRValidationError` — 校验失败异常类
- `validate_ir(ir)` — 核心校验函数，包含：
  - meta 字段补全和归一化
  - tags 数组规范化（名称、数据类型、地址、注释）
  - text_lists 规范化
  - scripts 规范化
  - objects 逐对象校验：补全缺失的 process_tag（自动添加到 tags）、校验交叉引用、类型合法性检查
  - 自动布局优化 `_optimize_layout()`：行聚类、水平对齐、最小间距修复、重叠检测与修复、边界裁剪
- `scale_ir_to_resolution(ir, target_resolution)` — 将 IR 坐标系等比缩放到目标分辨率，同时缩放坐标、尺寸、字号

#### 2.1.5 `simaticml_generator.py` — SimaticML 生成器

| 项目          | 内容                                                                                                                                           |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| **文件路径**    | `backend/simaticml_generator.py`                                                                                                             |
| **核心职责**    | 将校验后的 IR 转换为带 SimaticML 命名空间的 XML，用于通过 ScreenFolder.Import() 导入到博途                                                                           |
| **导出符号**    | `SIMATICML_NS`, `generate_simaticml(ir, tia_version, reference_xml) -> str`, `validate_tia_xml(xml) -> dict`, `repair_tia_xml(xml) -> tuple` |
| **被哪些模块调用** | `openness_manager.py`                                                                                                                        |

**详细说明：**

- `SIMATICML_NS` — Comfort 面板命名空间：`"http://www.siemens.com/automation/SimaticML"`
- `generate_simaticml(ir, tia_version, reference_xml)` — 主入口，支持：
  - 从参考画面 XML 提取命名空间和结构信息（`_extract_template_info`）
  - 生成 Document/Screen/AttributeList/Tags/TextLists/ObjectList/VBScripts 完整结构
  - 五类对象映射：IOField/SymbolicIOField/Button/Circle(Indicator)/Text
  - Basic 面板自动剥离 VBS 脚本事件
  - MultilingualText 标准包装（委托 MultilingualTextBuilder）
  - 自动校验 + 修复管线
- `validate_tia_xml(xml)` — 导入前 XML 校验（委托 XmlValidator）
- `repair_tia_xml(xml)` — 自动修复管线：TextNormalizer 清洗 → ScreenNumberAllocator 删 Number 节点 → MultilingualText DOM 级重建

#### 2.1.6 `template_xml_generator.py` — 经典 HMI 模板 XML 改写

| 项目          | 内容                                                                                                                                                                                      |
| ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **文件路径**    | `backend/template_xml_generator.py`                                                                                                                                                     |
| **核心职责**    | 将 IR 与从 TIA Portal 导出的模板 XML 结合，安全改写模板生成新画面 XML                                                                                                                                         |
| **导出符号**    | `_PREFIX_TYPE_MAP`, `_XML_TAG_TO_IR_TYPE`, `_IR_TYPE_TO_XML_TAG`, `_RICH_TEXT_COMPOSITIONS`, `generate_from_template_xml(...) -> (str, list)`, `generate_from_template_v4(...) -> dict` |
| **被哪些模块调用** | `openness_manager.py` (通过 `import_or_generate_from_ir`)                                                                                                                                 |

**详细说明：**

- `_PREFIX_TYPE_MAP` — 名称前缀到类型映射：`TXT_→Text`, `BTN_→Button`, `IO_→IOField`, `SIO_→SymbolicIOField`, `LMP_→Indicator`
- `_XML_TAG_TO_IR_TYPE` — TIA V16 Comfort 面板 XML 标签到 IR 类型映射（含 Circle/Ellipse→Indicator, TextField→Text 等）
- `_IR_TYPE_TO_XML_TAG` — IR 类型到 XML 标签反向映射
- `_RICH_TEXT_COMPOSITIONS` — 需要富文本结构的属性名：`{"Text", "TextOff", "TextOn", "Caption", "DisplayText"}`
- `generate_from_template_xml(ir, template_xml, options)` — 主入口（V2 兼容）：
  - 命名空间自动检测与注册
  - 画面名称改写（支持 screen name 冲突检测和重命名）
  - 画面尺寸保护（不覆盖模板尺寸，避免 TIA 报错）
  - IR 对象到模板控件匹配（5 级优先级：template_ref → id → 前缀 → XML 标签类型 → 模糊前缀）
  - 模板控件数量不足时自动克隆同类型控件
  - 属性安全替换：名称、位置、尺寸、文本、变量连接、颜色、脚本事件
- `generate_from_template_v4(ir, template_xml, options)` — V4.0 模板原型管线：
  - VariableEngine 语义增强
  - 模板分析（提取按钮/指示灯原型）
  - 原型匹配（behavior/indicator_mode 感知）
  - 克隆 → 替换名称/几何/文本/变量引用
  - 导入前校验（残留模板变量检测）

#### 2.1.7 `openness_manager.py` — TIA Portal Openness 连接管理器

| 项目          | 内容                                                                                                                                       |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| **文件路径**    | `backend/openness_manager.py`                                                                                                            |
| **核心职责**    | 通过 pythonnet 加载 Siemens.Engineering.dll，附加到正在运行的博途实例，定位 HMI 设备并导入生成的 XML                                                                 |
| **导出符号**    | `OpennessManager`（类）、`_net_type_name`, `_try_get_attr`, `_try_set_attr`, `_try_call`, `_create_screen_item`, `_hex_to_argb_int`（模块级辅助函数） |
| **被哪些模块调用** | Flask app 路由                                                                                                                             |

**详细说明：**

- `OpennessManager` 类是向后兼容的 Façade，V3.0 已将核心逻辑委托给子模块：
  - `SessionManager` → 连接/断开/诊断（lazy-init 属性）
  - `DeviceDiscovery` → HMI 设备查找与类型识别
  - `HmiCompiler` → 编译触发
  - `ExceptionMapper` → .NET 异常映射
  - `AssemblyLoader` → DLL 加载与版本元数据
- 核心方法：
  - `diagnose()` — 环境检查（OS/pythonnet/DLL 路径/TIA 进程）
  - `connect()` — 附加到运行中的博途实例并打开项目
  - `import_screen(xml_path)` — 导入画面 XML（预处理 → Screens.Import → 编译 → 保存）
  - `import_screen_xml(xml_path, ...)` — 经典 HMI 模板 XML 导入
  - `create_unified_screen_from_ir(ir)` — Unified 直接画面生成
  - `import_or_generate_from_ir(ir, mode)` — 统一入口，按 HMI 类型自动路由
  - `export_reference_screen(screen_name)` — 导出参考画面 XML
  - `get_hmi_capabilities()` — 返回 HMI 设备能力信息
  - `sync_tags(tags)` — HMI 变量表同步
  - `_preprocess_xml_for_import(...)` — 5 步预处理管线
  - `_export_screen_to_file(...)` — 3 级降级导出（直接调用/InvokeMember/MethodInfo.Invoke）
- 模块级辅助函数（Unified 对象反射操作）：
  - `_net_type_name(obj)` — 获取 .NET 对象完整类型名
  - `_try_get_attr(obj, name)` — 安全获取 .NET 属性
  - `_try_set_attr(obj, name, value)` — 安全设置 .NET 属性
  - `_try_call(obj, method_name, *args)` — 安全调用 .NET 方法
  - `_create_screen_item(screen, candidate_type_names, name)` — 尝试创建 ScreenItem
  - `_hex_to_argb_int(hex_color)` — 颜色值 #RRGGBB → ARGB 整数（Unified 专用）

#### 2.1.8 `config_manager.py` — 配置管理

| 项目          | 内容                                                                                                                                   |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| **文件路径**    | `backend/config_manager.py`                                                                                                          |
| **核心职责**    | config.yaml 读写、校验、深合并，供前端配置页通过 /api/config 读写                                                                                        |
| **导出符号**    | `DEFAULT_CONFIG`, `load_config() -> dict`, `save_config(new_config) -> dict`, `save_raw_yaml(text) -> dict`, `get_raw_yaml() -> str` |
| **被哪些模块调用** | Flask app 路由                                                                                                                         |

**详细说明：**

- `DEFAULT_CONFIG` — 默认配置字典，包含 `llm/openness/hmi_defaults/output/mimo/server` 六大节
  - `llm.providers`: 支持 deepseek 和 openai_compatible 两个大模型提供商
  - `openness.classic_template`: 经典模板 XML 模式的配置
  - `openness.unified_direct`: Unified 直接绘制配置
  - `mimo`: 视觉审查配置（enabled/api_key/max_iterations/review_pass_threshold）
- `load_config()` — 线程安全加载，不存在则写入默认配置
- `save_config(new_config)` — 深合并保存
- `save_raw_yaml(text)` — 原始 YAML 编辑模式
- `get_raw_yaml()` — 返回当前配置的原始 YAML 文本
- 使用 `threading.Lock` 保证线程安全

#### 2.1.9 `variable_engine.py` — 变量引擎

| 项目          | 内容                                                                                                                                                                                                                                                                                                                                                                           |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **文件路径**    | `backend/variable_engine.py`                                                                                                                                                                                                                                                                                                                                                 |
| **核心职责**    | 自动生成变量命名、绑定规则、Tag Table 管理，将 IR 画面对象映射为工程级 HMI 变量系统                                                                                                                                                                                                                                                                                                                          |
| **导出符号**    | `VariableEngine`（类）、`auto_bind_variables(...)`, `enrich_to_v2(...)`（模块级函数）、`BTN_PREFIX_MOMENTARY`, `BTN_PREFIX_TOGGLE`, `INDICATOR_PREFIX_STATUS`, `INDICATOR_PREFIX_ALARM`, `IOFIELD_PREFIX`, `SYMBOLIC_IOFIELD_PREFIX`, `DEFAULT_DATA_TYPES`, `VBS_TOGGLE_TEMPLATE`, `VBS_MOMENTARY_PRESS_TEMPLATE`, `VBS_MOMENTARY_RELEASE_TEMPLATE`, `TOGGLE_KEYWORDS`, `ALARM_KEYWORDS` |
| **被哪些模块调用** | `pipeline_orchestrator.py`, `template_xml_generator.py`                                                                                                                                                                                                                                                                                                                      |

**详细说明：**

- 模块级常量：
  - `BTN_PREFIX_MOMENTARY` = `"BTN_"` — 瞬时按钮变量前缀
  - `BTN_PREFIX_TOGGLE` = `"MEM_"` — 自保持按钮变量前缀
  - `INDICATOR_PREFIX_STATUS` = `"STS_"` — 状态指示灯变量前缀
  - `INDICATOR_PREFIX_ALARM` = `"LMP_"` — 报警指示灯变量前缀
  - `IOFIELD_PREFIX` = `"IO_"` — 数值 IO 域变量前缀
  - `SYMBOLIC_IOFIELD_PREFIX` = `"SIO_"` — 符号 IO 域变量前缀
  - `DEFAULT_DATA_TYPES` — 默认数据类型映射：Bool/Int/DInt/Real/Word/String
  - `VBS_TOGGLE_TEMPLATE` — 切换按钮 VBS 模板：`SmartTags("{tag_name}") = Not ...`
  - `VBS_MOMENTARY_PRESS_TEMPLATE` — 瞬时按下模板：`SmartTags("{tag_name}") = 1`
  - `VBS_MOMENTARY_RELEASE_TEMPLATE` — 瞬时释放模板：`SmartTags("{tag_name}") = 0`
  - `TOGGLE_KEYWORDS` — 切换类关键词集合（切换/自保持/toggle 等 10 个）
  - `ALARM_KEYWORDS` — 报警类关键词集合（故障/报警/alarm 等 15 个）
- `VariableEngine` 类：
  - `enrich(legacy_ir, target_hint, plc_tag_mapping)` — V3.0 新 API，将旧 IR 转换为语义 `HmiProjectSpec` 并补齐推断
  - `generate(ir)` — V2 兼容入口，内部走 enrich 后回填旧格式字段
  - 推断内容：缺失的 TagSpec、EventSpec/ActionSpec、BindingSpec、命名建议、PLC 地址映射（4 级语义匹配）
  - 变量冲突检测：同名不同类型/同名不同地址
  - 静态方法：`get_tag_table()`, `get_tag_names()`, `get_binding_summary()`
- `auto_bind_variables(ir, plc_prefix)` — 模块级便捷函数（旧兼容）
- `enrich_to_v2(ir, target_hint)` — 模块级便捷函数（新 API）

#### 2.1.10 `review_prompts.py` — 审查与修正提示词

| 项目          | 内容                                                                                                                                                                                                  |
| ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **文件路径**    | `backend/review_prompts.py`                                                                                                                                                                         |
| **核心职责**    | MiMo 视觉审查任务模板、修正模式提示词、Siemens 标准色参考                                                                                                                                                                 |
| **导出符号**    | `SIEMENS_COLOR_REFERENCE`, `HMI_REVIEW_TASK`, `IMAGE_ANALYSIS_TASK`, `REGENERATION_SYSTEM_ADDENDUM`, `build_review_feedback_text(review_result) -> str`, `build_regeneration_messages(...) -> list` |
| **被哪些模块调用** | `pipeline_orchestrator.py`, `prompts.py`（修正模式）                                                                                                                                                      |

**详细说明：**

- `SIEMENS_COLOR_REFERENCE` — Siemens HMI 标准色参考：运行绿色 #27D17F、故障红色 #E25563、主题青色 #14E0B1、背景深色 #1F2630 等 10 种标准色
- `HMI_REVIEW_TASK` — 视觉审查模板，6 个评估维度：
  1. 布局清晰度与对齐 (layout_alignment)
  2. 组件尺寸与间距 (component_sizing)
  3. 颜色规范 (color_conventions)
  4. 文字可读性 (text_readability)
  5. 元素完整性 (completeness)
  6. 整体专业质量 (professional_quality)
  - 输出为结构化 JSON：含 pass/score/categories/critical_issues/suggestions
- `IMAGE_ANALYSIS_TASK` — 参考图片分析任务模板，提取参数/控制元素/状态指示/布局风格
- `REGENERATION_SYSTEM_ADDENDUM` — 修正模式系统提示词附加说明
- `build_review_feedback_text(review_result)` — 将审查结果转换为模型友好的 Markdown 格式反馈
- `build_regeneration_messages(requirement, previous_ir, review_result)` — 构建修正模式完整消息列表

#### 2.1.11 `preview_renderer.py` — 画面预览渲染器

| 项目          | 内容                                                                                      |
| ----------- | --------------------------------------------------------------------------------------- |
| **文件路径**    | `backend/preview_renderer.py`                                                           |
| **核心职责**    | 将校验后的 IR 使用 Pillow 直接绘制为 PNG 图像，供 MiMo 视觉审查                                             |
| **导出符号**    | `_DRAW_DISPATCH`, `_font_cache`, `_DEFAULT_FONT_PATHS`, `render_ir_to_png(ir) -> bytes` |
| **被哪些模块调用** | `pipeline_orchestrator.py`                                                              |

**详细说明：**

- `_DRAW_DISPATCH` — 对象类型到绘制函数的映射字典：Text→_draw_text, IOField→_draw_io_field, SymbolicIOField→_draw_symbolic_io_field, Button→_draw_button, Indicator→_draw_indicator
- `_font_cache` — 字体缓存字典 `{(size, bold): ImageFont}`
- `_DEFAULT_FONT_PATHS` — 系统字体探测路径列表（Windows/Linux/macOS），优先级：微软雅黑 > Arial > Segoe UI > Noto Sans CJK > PingFang
- `render_ir_to_png(ir)` — 主入口：
  - 从 IR 的 `_screen_size` 取画面尺寸
  - 使用 meta.background_color 创建背景
  - 遍历 objects 按类型分发到对应绘制函数
  - 返回 PNG bytes
- 各对象渲染效果：
  - Text：直接 `draw.text()`
  - IOField：`rounded_rectangle` + 示例值文本 + 单位
  - SymbolicIOField：圆角矩形 + "〔列表〕"文本 + 下拉三角
  - Button：填充色圆角矩形 + 居中文本 + 脚本标记圆点
  - Indicator：填充圆 + 高光弧 + 可选 blink 虚线环

#### 2.1.12 `mimo_client.py` — MiMo 视觉 API 客户端

| 项目          | 内容                                                                                                                                       |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| **文件路径**    | `backend/mimo_client.py`                                                                                                                 |
| **核心职责**    | 调用 MiMo-V2.5 视觉 API 进行图像理解和 HMI 画面审查                                                                                                     |
| **导出符号**    | `SUPPORTED_MIME_TYPES`, `MIMO_SYSTEM_PROMPT`, `SCHEMA_HINTS`, `analyze_with_mimo(images, task, output_schema, config, language) -> dict` |
| **被哪些模块调用** | `pipeline_orchestrator.py`                                                                                                               |

**详细说明：**

- `SUPPORTED_MIME_TYPES` — 支持的图片 MIME 类型：`{image/jpeg, image/png, image/gif, image/webp, image/bmp}`
- `MIMO_SYSTEM_PROMPT` — MiMo 系统提示词："You are a precise multimodal visual perception engine..."
- `SCHEMA_HINTS` — output_schema 映射：brief/detailed/ocr/chart/table/ui/drawing/compare/custom
- `analyze_with_mimo(...)` — 主入口：
  - 图片输入支持 3 种格式：url/path/base64
  - 自动缩放超过 max_dimension 的图片
  - 安全 JSON 解析（失败时返回 raw_text 兜底结构）
  - 返回结构化结果：`{ok, model, task, visual_result, raw_text, usage}`
  - 错误处理：区分 auth/bad_input/api/network 四种错误类型

---

### 2.2 文本处理管线

#### 2.2.1 `text_normalizer.py` — 文本规范化器（管线第一层）

| 项目          | 内容                                                                                                                                                        |
| ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **文件路径**    | `backend/text_normalizer.py`                                                                                                                              |
| **核心职责**    | 清洗所有即将写入 TIA XML 的文本字段，保证不含 HTML/Markdown/控制字符                                                                                                            |
| **导出符号**    | `TextNormalizer`（类）                                                                                                                                       |
| **被哪些模块调用** | `simaticml_generator.py`, `tia_text_sanitizer.py`, `multilingual_text_builder.py`, `openness_manager.py`, `template_xml_generator.py`, `import_engine.py` |

**详细说明：**

- `TextNormalizer.normalize(text)` — 9 步清洗管线：空值处理 → HTML 实体解码 → 数字实体解码 → HTML 注释移除 → 已知 HTML 标签移除（标签名匹配，不用通配符） → 非法控制字符移除 → 换行/制表符统一为空格 → 连续空白压缩 → Trim
- `TextNormalizer.normalize_xml_content(xml_string)` — 对完整 XML 执行文本级安全清洗（保留 TIA 合法富文本 `<body>/<p>`）
- `TextNormalizer.normalize_ir(ir)` — 遍历 IR 对象中所有文本字段执行清洗
- `TextNormalizer.is_clean(text)` — 快速检查文本是否已清洗
- 已知禁止的 HTML 标签名正则（覆盖约 80 个 HTML5 标签）

#### 2.2.2 `tia_text_sanitizer.py` — TIA 文本安全清洗器（兼容层）

| 项目          | 内容                                                                                                                                    |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| **文件路径**    | `backend/tia_text_sanitizer.py`                                                                                                       |
| **核心职责**    | 向后兼容接口，委托给 TextNormalizer + MultilingualTextBuilder + XmlValidator 新模块                                                                |
| **导出符号**    | `_FORBIDDEN_HTML_TAGS`, `sanitize_tia_text(text)`, `sanitize_ir_text_fields(ir)`, `lint_xml_content(xml)`, `lint_and_repair_xml(xml)` |
| **被哪些模块调用** | `template_xml_generator.py`, 旧代码                                                                                                      |

**详细说明：**

- 所有函数均为向后兼容的委托接口，实际逻辑已迁移到管线各层
- `_FORBIDDEN_HTML_TAGS` — 与 TextNormalizer 内部相同的 HTML 标签匹配正则
- `lint_and_repair_xml(xml)` — 组合 TextNormalizer + ScreenNumberAllocator + MultilingualTextBuilder + XmlValidator

#### 2.2.3 `multilingual_text_builder.py` — MultilingualText 构建器（管线第二层）

| 项目          | 内容                                                                                           |
| ----------- | -------------------------------------------------------------------------------------------- |
| **文件路径**    | `backend/multilingual_text_builder.py`                                                       |
| **核心职责**    | 使用 XML DOM 安全构建和修复 TIA Portal 标准 MultilingualText 节点                                         |
| **导出符号**    | `MultilingualTextBuilder`（类）                                                                 |
| **被哪些模块调用** | `simaticml_generator.py`, `openness_manager.py`, `import_engine.py`, `tia_text_sanitizer.py` |

**详细说明：**

- `MultilingualTextBuilder` 支持两种 TIA 格式：
  1. 通用结构：`<MultilingualText><Text Language="zh-CN">...</Text></MultilingualText>`
  2. TIA V16/Comfort：`<MultilingualText ID="1" CompositionName="Text"><ObjectList><MultilingualTextItem ...><AttributeList><Culture>zh-CN</Culture><Text>...</Text></AttributeList></MultilingualTextItem></ObjectList></MultilingualText>`
- 关键方法：
  - `build(text, language)` — 构建通用结构
  - `build_with_namespace(text, ns_uri, language)` — 构建带命名空间版本
  - `build_v16(text, mt_id, item_id, composition_name, language)` — 构建 V16/Comfort 风格
  - `rebuild_element(mt_element)` — 就地修复已有节点（保留 V16 结构，不插入错误的 `<ID>` 子元素）
  - `validate_element(mt_element)` — 验证 MultilingualText 结构合法性
  - `build_string(text, language)` — 静态便捷方法，返回 XML 字符串
- 对 Text/TextOff/TextOn/Caption/DisplayText 等可见文字属性自动使用富文本结构 `<body><p>...</p></body>`
- `SUPPORTED_LANGUAGES` — 支持 11 种语言代码（zh-CN/en-US/de-DE/ja-JP 等）

#### 2.2.4 `screen_number_allocator.py` — Screen Number 分配器（管线第三层）

| 项目          | 内容                                                                                           |
| ----------- | -------------------------------------------------------------------------------------------- |
| **文件路径**    | `backend/screen_number_allocator.py`                                                         |
| **核心职责**    | 主动分配唯一 screen number，防止导入时冲突                                                                 |
| **导出符号**    | `ScreenNumberAllocator`（类）                                                                   |
| **被哪些模块调用** | `simaticml_generator.py`, `openness_manager.py`, `import_engine.py`, `tia_text_sanitizer.py` |

**详细说明：**

- `ScreenNumberAllocator` 支持两种分配策略：`compact`（最小空缺）和 `max_plus_one`（最大值+1）
- `register_existing(numbers)` — 注册已使用的 screen numbers
- `register_xml_numbers(xml_content)` — 从 XML 提取并注册 <Number> 节点值
- `allocate()` — 分配新的唯一 screen number
- `remove_number_nodes(xml_content)` — 删除所有 <Number> 节点（让 TIA 自动分配）
- `detect_conflicts(xml_content)` — 检测 XML 中的 screen number 是否冲突

#### 2.2.5 `xml_validator.py` — XML 校验器（管线第四层）

| 项目          | 内容                                                                                           |
| ----------- | -------------------------------------------------------------------------------------------- |
| **文件路径**    | `backend/xml_validator.py`                                                                   |
| **核心职责**    | TIA Portal XML Pre-Import 全面校验（闸门）                                                           |
| **导出符号**    | `ValidationResult`（数据类）, `XmlValidator`（类）                                                   |
| **被哪些模块调用** | `simaticml_generator.py`, `openness_manager.py`, `import_engine.py`, `tia_text_sanitizer.py` |

**详细说明：**

- `ValidationResult` — 校验结果数据类，含 `valid/errors/warnings/stats`
- `XmlValidator.validate(xml_content)` — 执行 5 项检查：
  1. HTML 标签检测（允许 TIA 合法富文本 body/p）
  2. MultilingualText 结构完整性（兼容 V16/通用两种格式，禁止 <ID> 子元素）
  3. 非法控制字符检测
  4. Number 节点告警
  5. 根元素检查（必须含 Document 和 Screen）
- `XmlValidator.check_number_conflicts(xml_content, used_numbers)` — screen number 冲突检查

#### 2.2.6 `import_engine.py` — TIA 导入引擎（管线第五层终端层）

| 项目          | 内容                                        |
| ----------- | ----------------------------------------- |
| **文件路径**    | `backend/import_engine.py`                |
| **核心职责**    | 通过 Openness API 将已校验的 XML 安全导入 TIA Portal |
| **导出符号**    | `ImportResult`（数据类）, `ImportEngine`（类）    |
| **被哪些模块调用** | 未被生产代码直接导入（独立终端模块）                        |

**详细说明：**

- `ImportEngine` 分层设计：
  1. 预处理层：TextNormalizer + MultilingualTextBuilder + ScreenNumberAllocator
  2. 校验层（闸门）：XmlValidator 全面检查 → 不通过则直接阻断（Fail Fast）
  3. 导入层：唯一允许的导入方式 `Screens.Import(FileInfo, ImportOptions)`
- 强制约束：No Partial Fix、No Hacks、Single Method

#### 2.2.7 `generation_summary.py` — 生成摘要服务

| 项目          | 内容                                                                                                 |
| ----------- | -------------------------------------------------------------------------------------------------- |
| **文件路径**    | `backend/generation_summary.py`                                                                    |
| **核心职责**    | 从 HmiProjectSpec 或 legacy IR 提取生成结果摘要，供 V4.0 API 返回                                                |
| **导出符号**    | `build_generation_summary(project, deployment_result) -> dict`, `build_legacy_summary(ir) -> dict` |
| **被哪些模块调用** | Flask app 路由（V4.0 API）                                                                             |

**详细说明：**

- `build_generation_summary(project, deployment_result)` — 构建完整 V4.0 摘要，含 4 个部分：
  1. understanding：画面数、控件/按钮/指示灯/IO/文本/变量/连接/脚本计数值
  2. tags：变量名、数据类型、方向、作用域、地址、连接、待映射标记、注释
  3. bindings：控件 ID、类型、模板引用、行为模式、事件摘要、绑定摘要
  4. deployment：状态、导入/编译/验证结果摘要
- `build_legacy_summary(ir)` — 从旧 IR dict 构建简化摘要（向后兼容）

---

### 2.3 领域模型（domain/）

#### 2.3.1 `ir_v2.py` — HMI IR V2 数据模型

| 项目          | 内容                                                                                                                                                                                                                                             |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **文件路径**    | `backend/domain/ir_v2.py`                                                                                                                                                                                                                      |
| **核心职责**    | 定义完整工程语义 IR 的 Pydantic v2 数据模型                                                                                                                                                                                                                 |
| **导出符号**    | `DeploymentPolicies`, `ProjectMetadata`, `TargetSpec`, `ConnectionSpec`, `TagSpec`, `GeometrySpec`, `BindingSpec`, `ActionSpec`, `EventSpec`, `ScriptSpec`, `ResourceSpec`, `ScreenItemSpec`, `ScreenSpec`, `HmiProjectSpec`, `schema_version` |
| **被哪些模块调用** | `variable_engine.py`, `legacy_adapter.py`, `validation.py`, `backends/`, `planners/`, `services/`, `generation_summary.py`                                                                                                                     |

**详细说明：**

- 使用 Pydantic v2 BaseModel 定义，不依赖 Flask/pythonnet/Siemens DLL
- `HmiProjectSpec` — 顶层模型，含 schema_version(固定"2.0")/metadata/target/connections/tags/scripts/resources/screens/policies/diagnostics
- `TagSpec` — HMI 变量规格：name/table/scope/data_type/connection/address/acquisition_cycle/comment/direction/metadata
- `BindingSpec` — 动态属性绑定：property/kind/source_tag/config/tag/direction/connection/plc_address
- `ScreenItemSpec` — 画面控件规格：包含 V4.0 新增的 template_ref/prototype_role/behavior/indicator_mode 字段
- `ActionSpec` — 语义动作（不允许直接写死 VBS 或 JavaScript）
- `EventSpec` — 事件规格，关联动作列表

#### 2.3.2 `enums.py` — 枚举定义

| 项目          | 内容                                                                                                                                                                                                                                                                                                                                                                |
| ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **文件路径**    | `backend/domain/enums.py`                                                                                                                                                                                                                                                                                                                                         |
| **核心职责**    | 定义 HMI IR V2 所有枚举类型                                                                                                                                                                                                                                                                                                                                               |
| **导出符号**    | 22 个 Enum 类：`HmiFamily`, `TagScope`, `ConnectionKind`, `ScreenItemType`, `BindingKind`, `SemanticEvent`, `SemanticActionType`, `ScriptLanguage`, `DiagnosticSeverity`, `DeploymentPhase`, `ConflictPolicy`, `UnsupportedFeaturePolicy`, `MissingDependencyPolicy`, `DeploymentStatus`, `OpennessOperationKind`, `ButtonBehavior`, `IndicatorMode`, `TagDirection` |
| **被哪些模块调用** | 几乎所有 domain/ 和上层模块                                                                                                                                                                                                                                                                                                                                                |

**详细说明：**

- `HmiFamily` — HMI 面板家族：BASIC/COMFORT/UNIFIED/AUTO
- `ScreenItemType` — 画面控件类型（10 种）：TEXT/BUTTON/IO_FIELD/SYMBOLIC_IO_FIELD/INDICATOR/RECTANGLE/ELLIPSE/SWITCH/SLIDER/GRAPHIC_VIEW/SCREEN_WINDOW
- `DeploymentPhase` — 部署阶段（10 个按依赖顺序排列的步骤）：P00_DISCOVERY 到 P90_SAVE
- `ButtonBehavior` — V4.0 新增按钮行为：MOMENTARY/TOGGLE/SET/RESET/NAVIGATE/NONE
- `IndicatorMode` — V4.0 新增指示灯模式：BOOL_COLOR/BOOL_BLINK/MULTI_STATE/ALARM/WARNING/STATUS
- `DeploymentStatus` — 严格区分描述生成与真实 TIA 部署的状态机

#### 2.3.3 `diagnostics.py` — 诊断与错误模型

| 项目          | 内容                                    |
| ----------- | ------------------------------------- |
| **文件路径**    | `backend/domain/diagnostics.py`       |
| **核心职责**    | 定义结构化诊断信息模型和标准错误码                     |
| **导出符号**    | `Diagnostic`（类）, `DiagnosticCodes`（类） |
| **被哪些模块调用** | 几乎所有 domain/ 和上层模块                    |

**详细说明：**

- `Diagnostic` — 统一诊断信息模型（Pydantic）：code/severity/phase/object_type/object_name/message/details/remediation
- `DiagnosticCodes` — 标准诊断错误码（49 个常量），覆盖 7 大类：
  - 能力相关：CAP_UNSUPPORTED_EVENT/BINDING/SCREEN_ITEM/FEATURE
  - 依赖相关：DEP_MISSING_CONNECTION/CONTROLLER_TAG/TAG_TABLE/SCRIPT
  - Classic XML：CLASSIC_FRAGMENT_NOT_FOUND/SCHEMA_MISMATCH/BROKEN_LINK/DUPLICATE_ID
  - Unified：UNIFIED_TYPE_NOT_FOUND/EVENT_ENUM_AMBIGUOUS/PROPERTY_NOT_SUPPORTED
  - 脚本：SCRIPT_SECURITY_REJECTED/SYNTAX_FAILED
  - 导入/编译：IMPORT_TIA_EXCEPTION/COMPILE_ERROR/COMPILE_WARNING
  - 验证：VERIFY_TAG_MISSING/EVENT_MISSING/BINDING_MISSING/SCRIPT_MISSING/SCREEN_MISSING
  - V3.2 新增：TAG 导入与引用诊断码（15 个）
  - V4.0 新增：模板绑定校验/模板阶段/导入阶段诊断码（12 个）

#### 2.3.4 `deployment_plan.py` — 部署计划模型

| 项目          | 内容                                       |
| ----------- | ---------------------------------------- |
| **文件路径**    | `backend/domain/deployment_plan.py`      |
| **核心职责**    | 定义部署计划和步骤的数据模型                           |
| **导出符号**    | `DeploymentStep`（类）, `DeploymentPlan`（类） |
| **被哪些模块调用** | `planners/`, `services/`, `backends/`    |

**详细说明：**

- `DeploymentStep` — 单个部署步骤：id/phase/operation/target_type/target_name/depends_on/payload/rollback
- `DeploymentPlan` — 部署计划：plan_id/target/capabilities/steps/diagnostics/dry_run

#### 2.3.5 `deployment_result.py` — 部署结果模型

| 项目          | 内容                                                                                                                                                                                |
| ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **文件路径**    | `backend/domain/deployment_result.py`                                                                                                                                             |
| **核心职责**    | 定义部署结果、验证结果、项目快照的数据模型                                                                                                                                                             |
| **导出符号**    | `ObjectCountSummary`, `CompileResult`, `VerificationResult`, `DeploymentResult`, `TagSnapshot`, `ScreenItemSnapshot`, `ScreenSnapshot`, `ScriptSnapshot`, `ActualProjectSnapshot` |
| **被哪些模块调用** | `backends/`, `services/`, `planners/`                                                                                                                                             |

**详细说明：**

- `ActualProjectSnapshot` — 从真实 TIA 项目查询到的完整对象快照（VerificationService 只能接受此类型作为 found 数据）

#### 2.3.6 `validation.py` — IR V2 校验模块

| 项目          | 内容                                                                                                                                                                                                                                                               |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **文件路径**    | `backend/domain/validation.py`                                                                                                                                                                                                                                   |
| **核心职责**    | 对 HmiProjectSpec 做交叉引用校验和能力感知校验                                                                                                                                                                                                                                  |
| **导出符号**    | `IrV2ValidationError`, `validate_ir_v2(project) -> list[Diagnostic]`, `validate_template_binding_requirements(project) -> list[Diagnostic]`, `validate_or_raise(project) -> HmiProjectSpec`, `_validate_button_binding(...)`, `_validate_indicator_binding(...)` |
| **被哪些模块调用** | `planners/`, `services/`, `variable_engine.py`                                                                                                                                                                                                                   |

**详细说明：**

- `validate_ir_v2(project)` — 9 项交叉引用校验：schema_version/screens 非空/tag 名称唯一性/screen name 唯一性/脚本名称唯一性/资源名称唯一性/控件 tag_binding 引用/事件动作引用
- `validate_template_binding_requirements(project)` — V4.0 模板绑定 10 项校验：
  - 每个 button 必须有 binding.tag（除非 navigate）
  - 每个 indicator 必须有 binding.tag
  - binding.tag 必须存在于 tags
  - 按钮变量类型建议 Bool / 可写性检查
  - 指示灯变量可读性检查
  - template_ref 类型校验
  - 控件/事件不引用不存在的 tag
  - 外部 PLC 变量无地址标记 pending_mapping

#### 2.3.7 `legacy_adapter.py` — 旧 IR 适配器

| 项目          | 内容                                                                                                                                                    |
| ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| **文件路径**    | `backend/domain/legacy_adapter.py`                                                                                                                    |
| **核心职责**    | 将 V2.3 格式的旧 IR dict 转换为 HMI IR V2 (HmiProjectSpec)                                                                                                    |
| **导出符号**    | `LegacyIrAdapter`（类）、`_OLD_TYPE_TO_SCREEN_ITEM_TYPE`, `_HMI_TYPE_TO_FAMILY`, `_SCRIPT_KEY_TO_EVENT`, `_TAG_MODE_TO_ACTIONS`, `_parse_resolution(...)` |
| **被哪些模块调用** | `variable_engine.py`                                                                                                                                  |

**详细说明：**

- `LegacyIrAdapter.convert(legacy_ir)` — 核心转换方法，返回 `(HmiProjectSpec, diagnostics_list)`
- `_OLD_TYPE_TO_SCREEN_ITEM_TYPE` — 旧对象类型到 V2 ScreenItemType 映射（大小写均支持）
- 自动转换绑定和事件（Button: momentary→Press/Release, toggle→Click; Indicator: 颜色离散绑定 + 闪烁绑定）
- V4.0 自动推断 template_ref/behavior/indicator_mode

---

### 2.4 HMI 后端（backends/）

#### 2.4.1 Classic 后端（backends/classic/）

##### `common.py` — Classic 共享基础设施

| 项目          | 内容                                       |
| ----------- | ---------------------------------------- |
| **文件路径**    | `backend/backends/classic/common.py`     |
| **核心职责**    | Basic/Comfort 共享的 Classic XML 生成基础设施     |
| **导出符号**    | `ClassicCommon`（类）, `TEMPLATE_TAG_NAMES` |
| **被哪些模块调用** | `basic_backend.py`, `comfort_backend.py` |

**详细说明：**

- `ClassicCommon` 聚合了 TagXmlBuilder/ScreenXmlBuilder/FunctionListBuilder/DynamicXmlBuilder/LinkResolver/ClassicValidator/ClassicScreenReferenceRewriter
- `TEMPLATE_TAG_NAMES` = `{"Button", "Template_ProcessTag", "Template_TextList"}` — 需重写的模板变量名
- 提供 build_tags_xml/build_screen_xml/rewrite_screen_references/check_template_leaks/validate_xml 等方法

##### `basic_backend.py` — Basic Panel 后端

| 项目          | 内容                                                |
| ----------- | ------------------------------------------------- |
| **文件路径**    | `backend/backends/classic/basic_backend.py`       |
| **核心职责**    | Basic Panel 部署后端，禁止 VBS 脚本                        |
| **导出符号**    | `BasicBackend`（类）                                 |
| **被哪些模块调用** | `services/deployment_service.py` (BackendFactory) |

##### `comfort_backend.py` — Comfort Panel 后端

| 项目          | 内容                                                |
| ----------- | ------------------------------------------------- |
| **文件路径**    | `backend/backends/classic/comfort_backend.py`     |
| **核心职责**    | Comfort Panel 部署后端，支持 VBS 脚本                      |
| **导出符号**    | `ComfortBackend`（类）                               |
| **被哪些模块调用** | `services/deployment_service.py` (BackendFactory) |

##### `dynamic_xml_builder.py` — Dynamic XML 构建器

| 项目          | 内容                                                |
| ----------- | ------------------------------------------------- |
| **文件路径**    | `backend/backends/classic/dynamic_xml_builder.py` |
| **核心职责**    | 生成 Classic HMI 的动态 XML 片段（颜色动态、闪烁等）               |
| **导出符号**    | `DynamicXmlBuilder`（类）, `PROPERTY_ALIASES`        |
| **被哪些模块调用** | `common.py`                                       |

##### `function_list_builder.py` — FunctionList 构建器

| 项目          | 内容                                                                       |
| ----------- | ------------------------------------------------------------------------ |
| **文件路径**    | `backend/backends/classic/function_list_builder.py`                      |
| **核心职责**    | 生成 Classic HMI 的系统 FunctionList                                          |
| **导出符号**    | `FunctionListBuilder`（类）, `ACTION_SYSTEM_FUNCTION_MAP`, `EVENT_ENUM_MAP` |
| **被哪些模块调用** | `common.py`                                                              |

##### `tag_xml_builder.py` — Tag XML 构建器

| 项目          | 内容                                            |
| ----------- | --------------------------------------------- |
| **文件路径**    | `backend/backends/classic/tag_xml_builder.py` |
| **核心职责**    | 生成 Classic HMI 的 Tag XML（批量导出/单变量导出/文本列表）     |
| **导出符号**    | `TagXmlBuilder`（类）, `SUPPORTED_DATA_TYPES`    |
| **被哪些模块调用** | `common.py`                                   |

##### `vbs_builder.py` — VBS 脚本构建器

| 项目          | 内容                                                    |
| ----------- | ----------------------------------------------------- |
| **文件路径**    | `backend/backends/classic/vbs_builder.py`             |
| **核心职责**    | 生成并校验 VBS 脚本                                          |
| **导出符号**    | `VbsBuilder`（类）, `ALLOWED_APIS`, `FORBIDDEN_PATTERNS` |
| **被哪些模块调用** | `comfort_backend.py`                                  |

##### `screen_xml_builder.py` — 画面 XML 构建器

| 项目          | 内容                                               |
| ----------- | ------------------------------------------------ |
| **文件路径**    | `backend/backends/classic/screen_xml_builder.py` |
| **核心职责**    | 从 ScreenSpec 生成 Classic HMI 画面 XML               |
| **导出符号**    | `ScreenXmlBuilder`（类）                            |
| **被哪些模块调用** | `common.py`                                      |

##### `link_resolver.py` — 引用解析器

| 项目          | 内容                                          |
| ----------- | ------------------------------------------- |
| **文件路径**    | `backend/backends/classic/link_resolver.py` |
| **核心职责**    | 解析 Classic XML 中控件之间的引用关系                   |
| **导出符号**    | `LinkResolver`（类）                           |
| **被哪些模块调用** | `common.py`                                 |

##### `classic_validator.py` — Classic 校验器

| 项目          | 内容                                                  |
| ----------- | --------------------------------------------------- |
| **文件路径**    | `backend/backends/classic/classic_validator.py`     |
| **核心职责**    | Classic HMI XML 生成后校验                               |
| **导出符号**    | `ClassicValidationResult`（类）, `ClassicValidator`（类） |
| **被哪些模块调用** | `common.py`                                         |

##### `classic_screen_reference_rewriter.py` — 画面引用重写器

| 项目          | 内容                                                                                                                                                                                                                                                                                                                                                                                                            |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **文件路径**    | `backend/backends/classic/classic_screen_reference_rewriter.py`                                                                                                                                                                                                                                                                                                                                               |
| **核心职责**    | 重写 Classic HMI 画面 XML 中的变量引用（模板变量 → 实际变量）                                                                                                                                                                                                                                                                                                                                                                     |
| **导出符号**    | `TAG_LINK_TYPES`, `CONTROLLER_TAG_LINK_TYPES`, `CONNECTION_LINK_TYPES`, `SCRIPT_LINK_TYPES`, `SCREEN_LINK_TYPES`, `ALL_KNOWN_LINK_TYPES`, `ReferenceMapping`, `ReferenceReplacement`, `ExternalReference`, `ScreenRewriteResult`, `ControlBindingMap`, `ClassicScreenReferenceRewriter`, `rewrite_classic_screen(...)`, `rewrite_classic_screen_references(...)`, `validate_generated_screen_references(...)` |
| **被哪些模块调用** | `common.py`                                                                                                                                                                                                                                                                                                                                                                                                   |

##### `xml_fragment_catalog.py` — XML 片段目录

| 项目          | 内容                                                       |
| ----------- | -------------------------------------------------------- |
| **文件路径**    | `backend/backends/classic/xml_fragment_catalog.py`       |
| **核心职责**    | 管理从黄金参考项目导出的 XML 片段清单                                    |
| **导出符号**    | `ManifestEntry`, `CatalogManifest`, `XmlFragmentCatalog` |
| **被哪些模块调用** | `references/catalog_service.py`                          |

##### `xml_id_registry.py` — XML ID 注册表

| 项目          | 内容                                            |
| ----------- | --------------------------------------------- |
| **文件路径**    | `backend/backends/classic/xml_id_registry.py` |
| **核心职责**    | 保证生成的 XML ID 全局唯一                             |
| **导出符号**    | `XmlIdRegistry`（类）                            |
| **被哪些模块调用** | `common.py`                                   |

#### 2.4.2 Unified 后端（backends/unified/）

##### `__init__.py` — 模块入口

| 项目       | 内容                                                                                                                                                                               |
| -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **文件路径** | `backend/backends/unified/__init__.py`                                                                                                                                           |
| **导出符号** | `UnifiedBackend`, `UnifiedTagBuilder`, `UnifiedScreenBuilder`, `UnifiedPropertyBuilder`, `UnifiedBindingBuilder`, `UnifiedEventBuilder`, `JsBuilder`, `UnifiedReflectionAdapter` |

##### `unified_backend.py` — Unified 后端主类

| 项目          | 内容                                                |
| ----------- | ------------------------------------------------- |
| **文件路径**    | `backend/backends/unified/unified_backend.py`     |
| **核心职责**    | Unified 面板部署后端，通过 UnifiedOpennessExecutor 执行      |
| **导出符号**    | `UnifiedBackend`（类）                               |
| **被哪些模块调用** | `services/deployment_service.py` (BackendFactory) |

##### `tag_builder.py` — Unified Tag 构建器

| 项目       | 内容                                        |
| -------- | ----------------------------------------- |
| **文件路径** | `backend/backends/unified/tag_builder.py` |
| **核心职责** | Unified HMI 变量创建与导出                       |
| **导出符号** | `UnifiedTagBuilder`（类）                    |

##### `screen_builder.py` — Unified Screen 构建器

| 项目       | 内容                                           |
| -------- | -------------------------------------------- |
| **文件路径** | `backend/backends/unified/screen_builder.py` |
| **核心职责** | Unified HMI 画面创建与管理                          |
| **导出符号** | `UnifiedScreenBuilder`（类）                    |

##### `property_builder.py` — Unified 属性构建器

| 项目       | 内容                                             |
| -------- | ---------------------------------------------- |
| **文件路径** | `backend/backends/unified/property_builder.py` |
| **核心职责** | Unified HMI 控件属性设置（几何、颜色、文本等）                  |
| **导出符号** | `UnifiedPropertyBuilder`（类）                    |

##### `binding_builder.py` — Unified 绑定构建器

| 项目       | 内容                                                 |
| -------- | -------------------------------------------------- |
| **文件路径** | `backend/backends/unified/binding_builder.py`      |
| **核心职责** | Unified HMI 动态绑定创建（标签/离散/范围/闪烁等）                   |
| **导出符号** | `UnifiedBindingBuilder`（类）, `KIND_TO_DYNAMIZATION` |

##### `event_builder.py` — Unified 事件构建器

| 项目       | 内容                                           |
| -------- | -------------------------------------------- |
| **文件路径** | `backend/backends/unified/event_builder.py`  |
| **核心职责** | Unified HMI 事件处理创建                           |
| **导出符号** | `UnifiedEventBuilder`（类）, `EVENT_TO_HANDLER` |

##### `js_builder.py` — JavaScript 构建器

| 项目       | 内容                                                   |
| -------- | ---------------------------------------------------- |
| **文件路径** | `backend/backends/unified/js_builder.py`             |
| **核心职责** | Unified HMI JavaScript 脚本生成与校验                       |
| **导出符号** | `JsBuilder`（类）, `ALLOWED_APIS`, `FORBIDDEN_PATTERNS` |

##### `reflection_adapter.py` — Unified 反射适配器

| 项目       | 内容                                                                                         |
| -------- | ------------------------------------------------------------------------------------------ |
| **文件路径** | `backend/backends/unified/reflection_adapter.py`                                           |
| **核心职责** | 通过 .NET 反射适配 Unified Openness API 的类型/方法/属性/事件差异                                           |
| **导出符号** | `UnifiedReflectionAdapter`（类）, `UNIFIED_TYPE_KEYS`, `PROPERTY_ALIASES`, `EVENT_CANDIDATES` |

---

### 2.5 Openness 集成层

#### 2.5.1 `session_manager.py` — 会话管理器

| 项目          | 内容                                    |
| ----------- | ------------------------------------- |
| **文件路径**    | `backend/openness/session_manager.py` |
| **核心职责**    | TIA Portal 会话管理：诊断、连接、打开项目、断开         |
| **导出符号**    | `SessionManager`（类）                   |
| **被哪些模块调用** | `openness_manager.py`                 |

#### 2.5.2 `device_discovery.py` — 设备发现

| 项目          | 内容                                                        |
| ----------- | --------------------------------------------------------- |
| **文件路径**    | `backend/openness/device_discovery.py`                    |
| **核心职责**    | 遍历项目设备找到 HMI 软件对象，识别 HMI 家族（Basic/Comfort/Unified），列出已有画面 |
| **导出符号**    | `DeviceDiscovery`（类）、`logger`                             |
| **被哪些模块调用** | `openness_manager.py`                                     |

**详细说明：**

- `find_hmi_software(project, tia_module)` — 遍历设备树查找 HMI 软件对象
- `detect_family(sw, device, item)` — 区分 Basic/Comfort/Unified，综合类型名/设备名/型号/配置多源信息
- `list_screens(hmi_software)` — 递归收集所有画面名称（含子文件夹）

#### 2.5.3 `compiler.py` — 编译器

| 项目          | 内容                                                 |
| ----------- | -------------------------------------------------- |
| **文件路径**    | `backend/openness/compiler.py`                     |
| **核心职责**    | 触发 TIA Portal HMI 编译（ICompilable.Compile()）并递归收集结果 |
| **导出符号**    | `HmiCompiler`（类）                                   |
| **被哪些模块调用** | `openness_manager.py`                              |

**详细说明：**

- `compile(hmi_software)` — 触发编译，递归遍历 CompilerResult.Messages（支持子 Messages 递归结构）
- `syntax_check(script_body, language)` — 脚本语法检查
- 编译结果包含 errors/warnings/infos 计数和详细消息列表

#### 2.5.4 `classic_executor.py` — Classic Openness 执行器

| 项目          | 内容                                                                                                                                                  |
| ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| **文件路径**    | `backend/openness/classic_executor.py`                                                                                                              |
| **核心职责**    | 执行 Classic HMI 的部署步骤（变量导出/导入、画面导入、编译）                                                                                                               |
| **导出符号**    | `ClassicTagImportKind`, `TagXmlKind`, `detect_tag_import_kind(...)`, `classify_tag_xml_strict(...)`, `ClassicStepResult`, `ClassicOpennessExecutor` |
| **被哪些模块调用** | `backends/classic/basic_backend.py`, `backends/classic/comfort_backend.py`                                                                          |

#### 2.5.5 `unified_executor.py` — Unified Openness 执行器

| 项目          | 内容                                                              |
| ----------- | --------------------------------------------------------------- |
| **文件路径**    | `backend/openness/unified_executor.py`                          |
| **核心职责**    | 执行 Unified HMI 的部署步骤                                            |
| **导出符号**    | `UnifiedStepResult`, `UnifiedOpennessExecutor`, `_TYPE_KEY_MAP` |
| **被哪些模块调用** | `backends/unified/unified_backend.py`                           |

#### 2.5.6 `assembly_loader.py` — 程序集加载器

| 项目          | 内容                                    |
| ----------- | ------------------------------------- |
| **文件路径**    | `backend/openness/assembly_loader.py` |
| **核心职责**    | 加载 Siemens.Engineering DLL 并提取版本元数据   |
| **导出符号**    | `AssemblyMetadata`, `AssemblyLoader`  |
| **被哪些模块调用** | `openness_manager.py`                 |

#### 2.5.7 `exception_mapper.py` — 异常映射器

| 项目          | 内容                                     |
| ----------- | -------------------------------------- |
| **文件路径**    | `backend/openness/exception_mapper.py` |
| **核心职责**    | 将 .NET 异常转换为统一 Diagnostic 诊断信息         |
| **导出符号**    | `ExceptionMapper`（类）                   |
| **被哪些模块调用** | `openness_manager.py`                  |

#### 2.5.8 `diagnostics_utils.py` — 诊断工具函数

| 项目          | 内容                                                                                                                                      |
| ----------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| **文件路径**    | `backend/openness/diagnostics_utils.py`                                                                                                 |
| **核心职责**    | Openness 诊断辅助函数集合                                                                                                                       |
| **导出符号**    | `collect_exception_chain(...)`, `describe_dotnet_object(...)`, `enumerate_tag_names(...)`, `find_tag(...)`, `inspect_xml_document(...)` |
| **被哪些模块调用** | `classic_executor.py`, `unified_executor.py` 等                                                                                          |

#### 2.5.9 `runtime_contract.py` — 运行时契约

| 项目          | 内容                                         |
| ----------- | ------------------------------------------ |
| **文件路径**    | `backend/openness/runtime_contract.py`     |
| **核心职责**    | 记录并验证 Unified Openness API 的运行时类型/方法/属性/事件 |
| **导出符号**    | `RuntimeContract`（类）, `RuntimeProber`（类）   |
| **被哪些模块调用** | `backends/unified/unified_backend.py`      |

#### 2.5.10 `object_query_service.py` — 对象查询服务

| 项目          | 内容                                         |
| ----------- | ------------------------------------------ |
| **文件路径**    | `backend/openness/object_query_service.py` |
| **核心职责**    | 查询 TIA 项目中已存在的 HMI 对象（供验证服务使用）             |
| **导出符号**    | `ObjectQueryService`（类）                    |
| **被哪些模块调用** | `services/verification_service.py`         |

---

### 2.6 规划与服务层

#### 2.6.1 `planners/deployment_planner.py` — 部署计划器

| 项目          | 内容                                            |
| ----------- | --------------------------------------------- |
| **文件路径**    | `backend/planners/deployment_planner.py`      |
| **核心职责**    | 从 HmiProjectSpec 按依赖顺序自动生成 DeploymentPlan     |
| **导出符号**    | `DeploymentPlanner`（类）                        |
| **被哪些模块调用** | `backends/`, `services/deployment_service.py` |

**详细说明：**

- `build_plan(spec, dry_run, plan_id)` — 核心方法，生成 10 个阶段的部署步骤：
  - P00 发现 → P10 依赖验证 → P20 连接 → P30 变量表与变量 → P40 脚本与资源 → P50 画面 → P60 绑定与事件 → P70 编译 → P80 验证 → P90 保存
- 集成 IR V2 交叉引用校验和能力验证，不通过时返回空步骤

#### 2.6.2 `planners/dependency_graph.py` — 部署依赖图

| 项目          | 内容                                                  |
| ----------- | --------------------------------------------------- |
| **文件路径**    | `backend/planners/dependency_graph.py`              |
| **核心职责**    | 构建部署步骤的拓扑排序顺序                                       |
| **导出符号**    | `DependencyGraph`（类）, `build_dependency_order(...)` |
| **被哪些模块调用** | `planners/deployment_planner.py`                    |

**详细说明：**

- `DependencyGraph` — 简单有向无环图 (DAG)，支持添加节点/边、环检测、拓扑排序
- `build_dependency_order(...)` — 为部署构建标准依赖顺序：连接 → 变量 → 脚本/资源 → 画面 → 绑定/事件 → 编译 → 验证 → 保存

#### 2.6.3 `services/deployment_service.py` — 统一部署服务

| 项目          | 内容                                                                                           |
| ----------- | -------------------------------------------------------------------------------------------- |
| **文件路径**    | `backend/services/deployment_service.py`                                                     |
| **核心职责**    | 完整部署流水线编排，状态机管理                                                                              |
| **导出符号**    | `RuntimeContext`（类）, `StepLog`（类）, `_now_iso()`, `BackendFactory`（类）, `DeploymentService`（类） |
| **被哪些模块调用** | Flask app 路由（V3.2+ API）                                                                      |

**详细说明：**

- 状态机：DRY_RUN → NOT_CONNECTED → BLOCKED → DEPLOYING → DEPLOYED（或 FAILED/VERIFICATION_FAILED/COMPILE_FAILED）
- `BackendFactory` — 根据 HMI 家族自动创建对应后端实例（BasicBackend/ComfortBackend/UnifiedBackend）
- `DeploymentService` — 编排 Legacy IR → VariableEngine.enrich → validate_ir_v2 → BackendFactory → backend.build_plan → backend.execute → backend.verify → compile

#### 2.6.4 `services/verification_service.py` — 验证服务

| 项目          | 内容                                            |
| ----------- | --------------------------------------------- |
| **文件路径**    | `backend/services/verification_service.py`    |
| **核心职责**    | 语义级部署后验证（V3.2 增强为语义验证，非仅数量）                   |
| **导出符号**    | `VerificationService`（类）                      |
| **被哪些模块调用** | `services/deployment_service.py`, `backends/` |

**详细说明：**

- `verify_full(...)` — 完整语义验证，connected=False 时返回失败
- 验证维度：tags（名称/类型/scope/连接/PLC 引用）、screens、events、bindings、scripts
- V3.2 增强：verify_button_events、verify_dynamizations、verify_no_template_references、verify_tag_tables

#### 2.6.5 `capabilities/capability_service.py` — 能力服务

| 项目          | 内容                                                                 |
| ----------- | ------------------------------------------------------------------ |
| **文件路径**    | `backend/capabilities/capability_service.py`                       |
| **核心职责**    | 目标设备能力解析与项目可行性校验                                                   |
| **导出符号**    | `CapabilitySet`（类）, `CapabilityService`（类）                         |
| **被哪些模块调用** | `planners/deployment_planner.py`, `services/deployment_service.py` |

#### 2.6.6 `capabilities/static_matrix.py` — 静态能力矩阵

| 项目          | 内容                                                                                      |
| ----------- | --------------------------------------------------------------------------------------- |
| **文件路径**    | `backend/capabilities/static_matrix.py`                                                 |
| **核心职责**    | 定义 Basic/Comfort/Unified 三大面板家族的静态能力矩阵                                                  |
| **导出符号**    | `CapabilityEntry`（类）, `STATIC_CAPABILITY_MATRIX`, `get_capability(name, family) -> str` |
| **被哪些模块调用** | `capabilities/capability_service.py`                                                    |

**详细说明：**

- `STATIC_CAPABILITY_MATRIX` — 16 项能力矩阵，每项标注 basic/comfort/unified 三列值（yes/no/limited/device）：
  - 画面导入/创建、HMI变量表导入/创建、外部变量、内部变量
  - 系统FunctionList（Basic yes/Comfort yes/Unified no）
  - VBS（Basic no/Comfort yes/Unified no）
  - JavaScript（Basic no/Comfort no/Unified yes）
  - 标签动态化、离散颜色动态、闪烁动态、动态可操作性
  - Popup/Slide-in、Faceplate、直接强类型创建ScreenItem
  - TextList、GraphicList

#### 2.6.7 `references/catalog_service.py` — Catalog 服务

| 项目          | 内容                                                  |
| ----------- | --------------------------------------------------- |
| **文件路径**    | `backend/references/catalog_service.py`             |
| **核心职责**    | 黄金参考工程 catalog 服务，查找/加载 manifest，提供 fragment lookup |
| **导出符号**    | `CatalogService`（类）                                 |
| **被哪些模块调用** | `backends/classic/`                                 |

---

### 2.7 模板系统

#### 2.7.1 `template/template_profile.py` — 模板原型数据模型

| 项目          | 内容                                                                                                  |
| ----------- | --------------------------------------------------------------------------------------------------- |
| **文件路径**    | `backend/template/template_profile.py`                                                              |
| **核心职责**    | 定义模板原型相关数据模型（ControlPrototype, EventPattern, BindingPattern 等）                                      |
| **导出符号**    | `ItemKind`, `TagReference`, `EventPattern`, `BindingPattern`, `ControlPrototype`, `TemplateProfile` |
| **被哪些模块调用** | `template/prototype_extractor.py`, `template/prototype_registry.py`, `template_xml_generator.py`    |

#### 2.7.2 `template/xml_utils.py` — XML 工具函数

| 项目          | 内容                                                                                                                                                                                                                                                                                                             |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **文件路径**    | `backend/template/xml_utils.py`                                                                                                                                                                                                                                                                                |
| **核心职责**    | 兼容命名空间的 XML 节点操作工具集                                                                                                                                                                                                                                                                                            |
| **导出符号**    | `local_name(...)`, `get_attr_case_insensitive(...)`, `node_to_string(...)`, `deepcopy_xml_node(...)`, `iter_nodes(...)`, `find_text_like_values(...)`, `detect_control_name(...)`, `detect_control_type(...)`, `assign_new_ids(...)`, `collect_existing_ids(...)`, `find_parent(...)`, `build_parent_map(...)` |
| **被哪些模块调用** | 模板系统内所有模块                                                                                                                                                                                                                                                                                                      |

#### 2.7.3 `template/binding_pattern_extractor.py` — 绑定模式提取器

| 项目          | 内容                                              |
| ----------- | ----------------------------------------------- |
| **文件路径**    | `backend/template/binding_pattern_extractor.py` |
| **核心职责**    | 从模板 XML 控件节点提取动态绑定模式                            |
| **导出符号**    | `extract_binding_patterns(...)`                 |
| **被哪些模块调用** | `template/prototype_extractor.py`               |

#### 2.7.4 `template/event_pattern_extractor.py` — 事件模式提取器

| 项目          | 内容                                            |
| ----------- | --------------------------------------------- |
| **文件路径**    | `backend/template/event_pattern_extractor.py` |
| **核心职责**    | 从模板 XML 控件节点提取事件模式                            |
| **导出符号**    | `extract_event_patterns(...)`                 |
| **被哪些模块调用** | `template/prototype_extractor.py`             |

#### 2.7.5 `template/prototype_extractor.py` — 原型提取器

| 项目          | 内容                                                 |
| ----------- | -------------------------------------------------- |
| **文件路径**    | `backend/template/prototype_extractor.py`          |
| **核心职责**    | 分析模板画面 XML，提取所有控件原型（TemplateProfile）               |
| **导出符号**    | `analyze_template_screen(...)`, `_NAME_PREFIX_MAP` |
| **被哪些模块调用** | `template_xml_generator.py` (V4.0)                 |

#### 2.7.6 `template/prototype_registry.py` — 原型注册表

| 项目          | 内容                                            |
| ----------- | --------------------------------------------- |
| **文件路径**    | `backend/template/prototype_registry.py`      |
| **核心职责**    | 根据 IR 控件查找最合适的模板原型（5 级匹配优先级）                  |
| **导出符号**    | `PrototypeNotFoundError`, `PrototypeRegistry` |
| **被哪些模块调用** | `template_xml_generator.py` (V4.0)            |

#### 2.7.7 `template/xml_rewrite_rules.py` — XML 重写规则

| 项目          | 内容                                                                                                                                                                                                                                    |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **文件路径**    | `backend/template/xml_rewrite_rules.py`                                                                                                                                                                                               |
| **核心职责**    | 定义模板原型克隆后的替换函数                                                                                                                                                                                                                        |
| **导出符号**    | `RewritePlan`, `replace_control_name(...)`, `replace_control_text(...)`, `replace_geometry(...)`, `replace_all_tag_references(...)`, `ensure_no_placeholder_tags(...)`, `assign_unique_control_ids(...)`, `clone_prototype_node(...)` |
| **被哪些模块调用** | `template_xml_generator.py` (V4.0)                                                                                                                                                                                                    |

#### 2.7.8 `template/template_binding_validator.py` — 模板绑定校验器

| 项目          | 内容                                                    |
| ----------- | ----------------------------------------------------- |
| **文件路径**    | `backend/template/template_binding_validator.py`      |
| **核心职责**    | 导入前检查生成的 Screen XML 完整性                               |
| **导出符号**    | `validate_generated_screen_xml(...)`, `_CONTROL_TAGS` |
| **被哪些模块调用** | `template_xml_generator.py` (V4.0)                    |

---

## 3. 未使用文件清单

| 文件                                               | 原定用途（从文件内容推断）                                                                                                                                                                       |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `backend/import_engine.py`                       | TIA 导入引擎 — 管线的第五层终端层。**完全未被任何生产代码或测试代码导入**。其功能已完全迁移至 `services/deployment_service.py` 和各后端（`basic_backend.py`, `comfort_backend.py`, `unified_backend.py`）的 XML 导入方法中。该文件保留但无实际调用方。 |
| `backend/template/binding_pattern_extractor.py`  | 绑定模式提取器。**仅被测试文件导入**，生产流程（SimaticML/Template XML 模式）均不经过此文件。                                                                                                                        |
| `backend/template/event_pattern_extractor.py`    | 事件模式提取器。**仅被测试文件导入**。                                                                                                                                                               |
| `backend/template/prototype_extractor.py`        | 模板原型提取器。**仅被测试文件导入**（4个测试文件）。                                                                                                                                                       |
| `backend/template/prototype_registry.py`         | 原型注册表。**仅被测试文件导入**（3个测试文件）。                                                                                                                                                         |
| `backend/template/template_binding_validator.py` | 模板绑定校验器。**仅被测试文件导入**（2个测试文件）。                                                                                                                                                       |
| `backend/template/template_profile.py`           | 模板画像数据模型。**仅被测试文件导入**。                                                                                                                                                              |
| `backend/template/xml_rewrite_rules.py`          | XML 重写规则引擎。**仅被测试文件导入**（5个测试文件）。                                                                                                                                                    |
| `backend/template/xml_utils.py`                  | XML 工具函数。**仅被测试文件导入**（4个测试文件）。                                                                                                                                                      |

---

## 4. 变量全景图

### 4.1 入口层模块级变量/常量

| 文件                          | 变量名                            | 类型   | 默认值/取值                                                                                                            | 用途                       |
| --------------------------- | ------------------------------ | ---- | ----------------------------------------------------------------------------------------------------------------- | ------------------------ |
| `llm_client.py`             | `DEPTH_MAP`                    | dict | `{"关闭": {use_reasoner:False,...}, "低": {effort:"low",...}, "中": {effort:"medium",...}, "高": {effort:"high",...}}` | 思考深度到模型参数的映射             |
| `prompts.py`                | `SYSTEM_PROMPT`                | str  | 完整系统提示词                                                                                                           | 发送给 LLM 的核心系统提示词         |
| `prompts.py`                | `IR_SCHEMA_DOC`                | str  | 完整 IR JSON Schema 文档                                                                                              | LLM 输出格式约束               |
| `prompts.py`                | `TEXT_CONVENTIONS`             | str  | 文字与命名规范（7 条）                                                                                                      | 提示词中的文字规范节               |
| `prompts.py`                | `TAG_CONVENTIONS`              | str  | 变量绑定规范（6 条）                                                                                                       | 提示词中的变量规范节               |
| `prompts.py`                | `VBS_CONVENTIONS`              | str  | VBS 脚本规范（6 条）                                                                                                     | 提示词中的脚本规范节               |
| `prompts.py`                | `LAYOUT_CONVENTIONS`           | str  | 布局排版规范（11 条）                                                                                                      | 提示词中的布局规范节               |
| `prompts.py`                | `JSON_SELF_CHECK`              | str  | 输出前自检（7 项）                                                                                                        | 提示词中的自检要求                |
| `prompts.py`                | `FEW_SHOT_USER`                | str  | "一个电机启停控制画面..."                                                                                                   | Few-shot 示例的用户输入         |
| `prompts.py`                | `FEW_SHOT_ASSISTANT`           | str  | 完整 IR JSON 示例                                                                                                     | Few-shot 示例的模型输出         |
| `hmi_ir.py`                 | `VALID_OBJECT_TYPES`           | set  | `{"IOField", "SymbolicIOField", "Button", "Indicator", "Text"}`                                                   | 合法 HMI 对象类型集合            |
| `hmi_ir.py`                 | `VALID_MODES`                  | set  | `{"Input", "Output", "InputOutput"}`                                                                              | IO 域合法模式                 |
| `hmi_ir.py`                 | `VALID_FORMATS`                | set  | `{"Decimal", "String", "Hex", "Binary"}`                                                                          | IO 域合法显示格式               |
| `hmi_ir.py`                 | `VALID_DATATYPES`              | set  | `{"Bool", "Int", "DInt", "Real", "Word", "String"}`                                                               | 合法数据类型                   |
| `hmi_ir.py`                 | `VALID_HMI_TYPES`              | set  | `{"Basic", "Comfort", "Unified"}`                                                                                 | 合法 HMI 类型                |
| `hmi_ir.py`                 | `VALID_TAG_MODES`              | set  | `{"momentary", "toggle"}`                                                                                         | 合法按钮模式                   |
| `hmi_ir.py`                 | `TAG_PREFIX_MAP`               | dict | `{"Button":"BTN_", "Indicator":"STS_", "IOField":"IO_", "SymbolicIOField":"SIO_"}`                                | 对象类型到变量名前缀映射             |
| `hmi_ir.py`                 | `VALID_RES`                    | set  | `{"1920x1080", "1280x800", "1024x768", "800x480", "480x272", "640x480", "320x240"}`                               | 标准分辨率                    |
| `config_manager.py`         | `DEFAULT_CONFIG`               | dict | 完整默认配置                                                                                                            | 应用的默认配置                  |
| `simaticml_generator.py`    | `SIMATICML_NS`                 | str  | `"http://www.siemens.com/automation/SimaticML"`                                                                   | SimaticML 命名空间 URI       |
| `template_xml_generator.py` | `_PREFIX_TYPE_MAP`             | dict | `{"TXT_":"Text", "BTN_":"Button", "IO_":"IOField", "SIO_":"SymbolicIOField", "LMP_":"Indicator"}`                 | 名称前缀到 IR 类型映射            |
| `template_xml_generator.py` | `_XML_TAG_TO_IR_TYPE`          | dict | `{"IOField":"IOField", "Button":"Button", ...}` 兼容 Circle→Indicator 等                                             | XML 标签到 IR 类型映射          |
| `template_xml_generator.py` | `_IR_TYPE_TO_XML_TAG`          | dict | `{"IOField":"IOField", "Button":"Button", ...}`                                                                   | IR 类型到 XML 标签反向映射        |
| `template_xml_generator.py` | `_RICH_TEXT_COMPOSITIONS`      | set  | `{"Text", "TextOff", "TextOn", "Caption", "DisplayText"}`                                                         | 需要富文本结构的 CompositionName |
| `review_prompts.py`         | `SIEMENS_COLOR_REFERENCE`      | str  | 10 种标准色定义                                                                                                         | 审查时参考的 Siemens 标准色       |
| `review_prompts.py`         | `HMI_REVIEW_TASK`              | str  | 完整审查模板（6 个评估维度）                                                                                                   | MiMo 视觉审查任务              |
| `review_prompts.py`         | `IMAGE_ANALYSIS_TASK`          | str  | 图片分析任务模板                                                                                                          | MiMo 图片分析任务              |
| `review_prompts.py`         | `REGENERATION_SYSTEM_ADDENDUM` | str  | 修正模式系统提示词附加                                                                                                       | LLM 修正模式的系统提示词附加         |
| `mimo_client.py`            | `SUPPORTED_MIME_TYPES`         | set  | `{"image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp"}`                                             | MiMo 支持的图片 MIME 类型       |
| `mimo_client.py`            | `MIMO_SYSTEM_PROMPT`           | str  | "You are a precise multimodal visual perception engine..."                                                        | MiMo 系统提示词               |
| `mimo_client.py`            | `SCHEMA_HINTS`                 | dict | 9 种 schema 提示词映射                                                                                                  | output_schema 到提示词映射     |
| `preview_renderer.py`       | `_DRAW_DISPATCH`               | dict | `{"Text": _draw_text, "IOField": _draw_io_field, ...}`                                                            | 对象类型到绘制函数映射              |
| `preview_renderer.py`       | `_font_cache`                  | dict | `{(size, bold): ImageFont}`                                                                                       | 字体缓存字典                   |
| `preview_renderer.py`       | `_DEFAULT_FONT_PATHS`          | list | 8 个系统字体路径                                                                                                         | 字体探测路径列表                 |

### 4.2 文本处理模块级变量/常量

| 文件                             | 变量名                       | 类型         | 默认值/取值                                                    | 用途                            |
| ------------------------------ | ------------------------- | ---------- | --------------------------------------------------------- | ----------------------------- |
| `text_normalizer.py`           | `_FORBIDDEN_HTML_PATTERN` | re.Pattern | 匹配约 80 个 HTML5 标签名                                        | 已知禁止的 HTML 标签正则               |
| `text_normalizer.py`           | `_HTML_ENTITIES`          | dict       | 14 个 HTML 实体映射                                            | HTML 实体解码表                    |
| `text_normalizer.py`           | `_ILLEGAL_CONTROL`        | re.Pattern | `[\x00-\x08\x0B\x0C\x0E-\x1F]`                            | XML 1.0 禁止的控制字符               |
| `tia_text_sanitizer.py`        | `_FORBIDDEN_HTML_TAGS`    | re.Pattern | 同 `_FORBIDDEN_HTML_PATTERN`                               | 向后兼容的 HTML 标签名正则              |
| `multilingual_text_builder.py` | `SUPPORTED_LANGUAGES`     | set        | 11 种语言代码                                                  | MultilingualTextBuilder 支持的语言 |
| `multilingual_text_builder.py` | `RICH_TEXT_COMPOSITIONS`  | set        | `{"Text", "TextOff", "TextOn", "Caption", "DisplayText"}` | 需要富文本结构的 CompositionName      |
| `xml_validator.py`             | `_HTML_PATTERN`           | re.Pattern | 同 `_FORBIDDEN_HTML_PATTERN`                               | HTML 标签检测正则                   |
| `xml_validator.py`             | `_ALLOWED_TIA_RICH_TAGS`  | set        | `{"body", "p"}`                                           | TIA 允许的合法富文本标签                |
| `xml_validator.py`             | `_RICH_TEXT_COMPOSITIONS` | set        | `{"Text", "TextOff", "TextOn", "Caption", "DisplayText"}` | 需要富文本结构的 CompositionName      |

### 4.3 领域模型模块级变量/常量

| 文件                  | 变量名                             | 类型      | 默认值/取值                                                                      | 用途                                  |
| ------------------- | ------------------------------- | ------- | --------------------------------------------------------------------------- | ----------------------------------- |
| `ir_v2.py`          | `schema_version`                | Literal | `"2.0"`                                                                     | HmiProjectSpec 的 schema 版本号         |
| `legacy_adapter.py` | `_OLD_TYPE_TO_SCREEN_ITEM_TYPE` | dict    | 含 11 个映射项                                                                   | 旧对象类型到 V2 ScreenItemType 映射（大小写均支持） |
| `legacy_adapter.py` | `_HMI_TYPE_TO_FAMILY`           | dict    | `{"Basic": BASIC, "Comfort": COMFORT, "Unified": UNIFIED}`                  | HMI 类型字符串到家族枚举映射                    |
| `legacy_adapter.py` | `_SCRIPT_KEY_TO_EVENT`          | dict    | `{"press_script": PRESS, "release_script": RELEASE, "click_script": CLICK}` | 旧脚本键到语义事件映射                         |
| `legacy_adapter.py` | `_TAG_MODE_TO_ACTIONS`          | dict    | `{"momentary": [SET_BIT, RESET_BIT], "toggle": [TOGGLE_BIT]}`               | tag_mode 到语义动作类型映射                  |
| `diagnostics.py`    | `DiagnosticCodes`               | class   | 49 个错误码常量                                                                   | 标准诊断错误码定义                           |

### 4.4 Classic 后端模块级变量/常量

| 文件                                     | 变量名                          | 类型       | 默认值/取值                                                   | 用途                    |
| -------------------------------------- | ---------------------------- | -------- | -------------------------------------------------------- | --------------------- |
| `common.py`                            | `TEMPLATE_TAG_NAMES`         | set      | `{"Button", "Template_ProcessTag", "Template_TextList"}` | 需要从模板 XML 中重写的变量名称    |
| `dynamic_xml_builder.py`               | `PROPERTY_ALIASES`           | dict     | 属性名别名映射                                                  | Unified/Custom 属性名标准化 |
| `function_list_builder.py`             | `ACTION_SYSTEM_FUNCTION_MAP` | dict     | 动作类型到系统函数映射                                              | 语义动作 → SimaticML 系统函数 |
| `function_list_builder.py`             | `EVENT_ENUM_MAP`             | dict     | 事件枚举映射表                                                  | 事件名到 .NET 枚举值映射       |
| `tag_xml_builder.py`                   | `SUPPORTED_DATA_TYPES`       | dict/set | TIA 支持的数据类型集合                                            | Tag 变量数据类型校验          |
| `vbs_builder.py`                       | `ALLOWED_APIS`               | set      | 允许的 VBS API 集合                                           | VBS 安全白名单             |
| `vbs_builder.py`                       | `FORBIDDEN_PATTERNS`         | list     | 禁止的代码模式列表                                                | VBS 安全黑名单             |
| `classic_screen_reference_rewriter.py` | `TAG_LINK_TYPES`             | set      | 变量链接类型集合                                                 | 需重写的变量引用类型            |
| `classic_screen_reference_rewriter.py` | `CONTROLLER_TAG_LINK_TYPES`  | set      | 控制器变量链接类型                                                | 需重写的控制器变量引用           |
| `classic_screen_reference_rewriter.py` | `CONNECTION_LINK_TYPES`      | set      | 连接链接类型                                                   | 需重写的连接引用              |
| `classic_screen_reference_rewriter.py` | `SCRIPT_LINK_TYPES`          | set      | 脚本链接类型                                                   | 需重写的脚本引用              |
| `classic_screen_reference_rewriter.py` | `SCREEN_LINK_TYPES`          | set      | 画面链接类型                                                   | 需重写的画面引用              |
| `classic_screen_reference_rewriter.py` | `ALL_KNOWN_LINK_TYPES`       | set      | 所有已知链接类型合集                                               | 引用重写覆盖范围              |

### 4.5 Unified 后端模块级变量/常量

| 文件                      | 变量名                    | 类型   | 默认值/取值                          | 用途                   |
| ----------------------- | ---------------------- | ---- | ------------------------------- | -------------------- |
| `binding_builder.py`    | `KIND_TO_DYNAMIZATION` | dict | BindingKind 到 Dynamization 类型映射 | 绑定类型 → Unified 动态化类型 |
| `event_builder.py`      | `EVENT_TO_HANDLER`     | dict | SemanticEvent 到 EventHandler 映射 | 事件 → Unified 事件处理器   |
| `js_builder.py`         | `ALLOWED_APIS`         | set  | 允许的 JS API 集合                   | JavaScript 安全白名单     |
| `js_builder.py`         | `FORBIDDEN_PATTERNS`   | list | 禁止的代码模式列表                       | JavaScript 安全黑名单     |
| `reflection_adapter.py` | `UNIFIED_TYPE_KEYS`    | list | Unified 类型键名列表                  | 反射适配时的类型查找键          |
| `reflection_adapter.py` | `PROPERTY_ALIASES`     | dict | 属性名别名映射                         | Unified 属性名标准化       |
| `reflection_adapter.py` | `EVENT_CANDIDATES`     | list | 事件名候选列表                         | 事件反射探测顺序             |

### 4.6 Openness 层模块级变量/常量

| 文件                    | 变量名             | 类型     | 默认值/取值                        | 用途                            |
| --------------------- | --------------- | ------ | ----------------------------- | ----------------------------- |
| `device_discovery.py` | `logger`        | Logger | `logging.getLogger(__name__)` | 模块日志记录器                       |
| `unified_executor.py` | `_TYPE_KEY_MAP` | dict   | 控件类型到 Unified 类型键映射           | ScreenItemType → Unified 创建类型 |

### 4.7 变量引擎模块级变量/常量

| 文件                   | 变量名                              | 类型   | 默认值                                                                                            | 用途            |
| -------------------- | -------------------------------- | ---- | ---------------------------------------------------------------------------------------------- | ------------- |
| `variable_engine.py` | `BTN_PREFIX_MOMENTARY`           | str  | `"BTN_"`                                                                                       | 瞬时按钮变量前缀      |
| `variable_engine.py` | `BTN_PREFIX_TOGGLE`              | str  | `"MEM_"`                                                                                       | 自保持按钮变量前缀     |
| `variable_engine.py` | `INDICATOR_PREFIX_STATUS`        | str  | `"STS_"`                                                                                       | 状态指示灯变量前缀     |
| `variable_engine.py` | `INDICATOR_PREFIX_ALARM`         | str  | `"LMP_"`                                                                                       | 报警指示灯变量前缀     |
| `variable_engine.py` | `IOFIELD_PREFIX`                 | str  | `"IO_"`                                                                                        | 数值 IO 域变量前缀   |
| `variable_engine.py` | `SYMBOLIC_IOFIELD_PREFIX`        | str  | `"SIO_"`                                                                                       | 符号 IO 域变量前缀   |
| `variable_engine.py` | `DEFAULT_DATA_TYPES`             | dict | `{"Bool":"Bool", "Int":"Int", "DInt":"DInt", "Real":"Real", "Word":"Word", "String":"String"}` | 默认数据类型映射      |
| `variable_engine.py` | `VBS_TOGGLE_TEMPLATE`            | str  | `SmartTags("{tag_name}") = Not SmartTags("{tag_name}")`                                        | 切换按钮脚本模板      |
| `variable_engine.py` | `VBS_MOMENTARY_PRESS_TEMPLATE`   | str  | `SmartTags("{tag_name}") = 1`                                                                  | 瞬时按下脚本模板      |
| `variable_engine.py` | `VBS_MOMENTARY_RELEASE_TEMPLATE` | str  | `SmartTags("{tag_name}") = 0`                                                                  | 瞬时释放脚本模板      |
| `variable_engine.py` | `TOGGLE_KEYWORDS`                | set  | 10 个关键词                                                                                        | 自保持/切换按钮检测关键词 |
| `variable_engine.py` | `ALARM_KEYWORDS`                 | set  | 15 个关键词                                                                                        | 报警指示灯检测关键词    |

### 4.8 模板系统模块级变量/常量

| 文件                                       | 变量名                | 类型       | 取值                                                                                    | 用途             |
| ---------------------------------------- | ------------------ | -------- | ------------------------------------------------------------------------------------- | -------------- |
| `template/template_profile.py`           | `ItemKind`         | Literal  | `"button" \| "indicator" \| "io_field" \| "symbolic_io_field" \| "text" \| "unknown"` | 控件类型字面量        |
| `template/prototype_extractor.py`        | `_NAME_PREFIX_MAP` | dict     | 名称前缀到控件类型映射                                                                           | 根据控件名推断类型      |
| `template/template_binding_validator.py` | `_CONTROL_TAGS`    | set/list | 已知控件 XML 标签名集合                                                                        | 控件标签类型集合（用于校验） |

### 4.9 能力矩阵模块级变量/常量

| 文件                              | 变量名                        | 类型                    | 行数   | 用途                                  |
| ------------------------------- | -------------------------- | --------------------- | ---- | ----------------------------------- |
| `capabilities/static_matrix.py` | `STATIC_CAPABILITY_MATRIX` | list[CapabilityEntry] | 16 项 | Basic/Comfort/Unified 三大面板家族的静态能力矩阵 |

---

> **文档结束** — 所有内容均来自对后端源代码文件的直接分析，未做任何推测性补充。

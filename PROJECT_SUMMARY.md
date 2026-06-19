# Siemens HMI Assistant V2.3 - 项目总结

## 📋 项目概述

**Siemens HMI Assistant** 是一款基于 AI 大模型的西门子 HMI 画面自动生成工具，能够将中文自然语言需求转换为可直接导入 TIA Portal 的 HMI 画面。项目采用 Flask 后端 + Web 前端架构，集成了多阶段生成流水线、视觉审查、变量引擎等先进特性。

### 核心定位

- **目标用户**：工业自动化工程师、HMI 开发人员
- **核心价值**：通过 AI 自动生成 HMI 画面，大幅降低开发时间
- **技术栈**：Python 3.10+ / Flask / DeepSeek / MiMo-V2.5 / TIA Portal Openness

---

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Web 前端 (templates/)                      │
│         HTML + CSS + JavaScript (SSE 实时流式显示)            │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP API
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    Flask 后端 (app.py)                        │
│    路由: /api/generate, /api/build, /api/openness/*          │
└───────────┬───────────┬───────────┬───────────┬─────────────┘
            │           │           │           │
            ▼           ▼           ▼           ▼
    ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐
    │ LLMClient │ │ VariableEngine │ │ SimaticML │ │ Openness  │
    │ (AI 生成) │ │ (变量绑定) │ │ (XML 生成) │ │ (TIA 连接)│
    └───────────┘ └───────────┘ └───────────┘ └───────────┘
            │                                   │
            ▼                                   ▼
    ┌───────────────────┐               ┌───────────────────┐
    │  DeepSeek API     │               │ TIA Portal V16+   │
    │  (大模型推理)      │               │ (HMI 画面导入)     │
    └───────────────────┘               └───────────────────┘
```

---

## 📁 目录结构

```
SiemensHmi_Assistant/
├── app.py                          # Flask 主程序（路由定义）
├── config.yaml                     # 应用配置文件
├── requirements.txt                # Python 依赖
│
├── backend/                        # 后端核心模块
│   ├── __init__.py
│   ├── llm_client.py               # 大模型客户端（DeepSeek/OpenAI 兼容）
│   ├── mimo_client.py              # MiMo 视觉 API 客户端
│   ├── prompts.py                  # 提示词工程（系统提示词 + Few-shot）
│   ├── hmi_ir.py                   # HMI 画面中间表示(IR)校验与归一化
│   ├── variable_engine.py          # 变量引擎（自动绑定 + VBS 脚本生成）
│   ├── simaticml_generator.py      # SimaticML XML 生成器
│   ├── template_xml_generator.py   # 模板 XML 改写生成器
│   ├── pipeline_orchestrator.py    # 多阶段流水线编排器
│   ├── openness_manager.py         # TIA Portal Openness 连接管理
│   ├── preview_renderer.py         # IR 预览图渲染
│   ├── config_manager.py           # 配置文件管理
│   ├── review_prompts.py           # 视觉审查提示词
│   ├── text_normalizer.py          # 文本清洗（HTML/控制字符）
│   ├── multilingual_text_builder.py# MultilingualText DOM 构建
│   ├── screen_number_allocator.py  # Screen Number 分配器
│   ├── xml_validator.py            # TIA XML 校验器
│   ├── tia_text_sanitizer.py       # TIA 文本字段清洗
│   └── import_engine.py            # 导入引擎
│
├── templates/                      # Flask HTML 模板
│   └── index.html                  # 主界面
│
├── static/                         # 静态资源
│   ├── app.js                      # 前端 JavaScript
│   └── style.css                   # 样式表
│
├── exports/                        # 生成结果输出目录
│   ├── templates/                  # 模板 XML 文件
│   └── generated_from_template/    # 基于模板生成的 XML
│
└── tests/                          # 单元测试
    ├── test_hmi_ir.py
    ├── test_flask_api.py
    ├── test_openness_manager.py
    └── test_template_xml_generator.py
```

---

## 🔧 核心模块详解

### 1. **app.py** - Flask 主程序

**功能**：定义所有 HTTP API 路由，协调各模块工作。

**主要路由**：
| 路由 | 方法 | 功能 |
|------|------|------|
| `/api/generate` | POST | 流式生成 HMI 画面 IR（SSE） |
| `/api/generate/with_review` | POST | 带视觉审查的多阶段生成 |
| `/api/build` | POST | 校验 IR → 生成 SimaticML XML |
| `/api/build/template-xml` | POST | 基于模板生成 XML |
| `/api/openness/connect` | POST | 连接 TIA Portal |
| `/api/openness/import` | POST | 导入画面到博途 |
| `/api/openness/sync-tags` | POST | 同步变量到 HMI 变量表 |
| `/api/openness/export-reference` | POST | 导出参考画面 XML |

**关键特性**：

- SSE（Server-Sent Events）实时流式输出
- 支持 PDF/图片/文本文件上传解析
- 全局 Openness 连接管理（单例模式）

---

### 2. **llm_client.py** - 大模型客户端

**功能**：对接 DeepSeek/OpenAI 兼容的大模型 API。

**核心特性**：

- **多层思考深度**：关闭/低/中/高，映射到 `reasoning_effort`
- **原生推理支持**：DeepSeek-reasoner 等模型的 `reasoning_content` 字段
- **诱导式思考**：非原生推理模型通过 `<thinking>` 标签实现
- **流式输出**：逐块产出 `(kind, text)` 元组

**代码位置**：`backend/llm_client.py:35-229`

```python
class LLMClient:
    def stream(self, messages) -> Generator[Tuple[str, str], None, None]:
        """流式生成：yield (kind, text)，kind ∈ {'thinking','content','error'}"""
        ...
```

---

### 3. **hmi_ir.py** - HMI 画面中间表示（IR）

**功能**：校验、归一化、自动排版优化大模型产出的 JSON IR。

**支持的对象类型**：

- `IOField` - 数值/字符串输入输出域
- `SymbolicIOField` - 符号 IO 域（枚举选择）
- `Button` - 按钮（支持瞬时/自保持）
- `Indicator` - 指示灯（圆+动画）
- `Text` - 静态文本

**关键函数**：

```python
def validate_ir(ir: dict) -> dict:
    """校验并返回归一化后的 IR；不合法则抛 IRValidationError。"""
    # 1. 结构检查
    # 2. 补默认值
    # 3. 交叉引用校验
    # 4. 自动排版优化（_optimize_layout）
    ...

def scale_ir_to_resolution(ir: dict, target_resolution: str) -> dict:
    """把 IR 缩放到目标分辨率。"""
    ...
```

**自动排版优化**（`_optimize_layout`）：

- 标题居中吸附顶部
- 同行控件水平对齐
- 最小间距修复（按钮≥24px，IO域≥20px）
- 多轮全局重叠修复
- 边界裁剪

**代码位置**：`backend/hmi_ir.py:18-526`

---

### 4. **variable_engine.py** - 变量引擎

**功能**：自动为 IR 对象生成工程级变量绑定。

**变量命名规则**：
| 对象类型 | 前缀 | 示例 |
|---------|------|------|
| 瞬时按钮 | `BTN_` | BTN_Start |
| 自保持按钮 | `MEM_` | MEM_Mode |
| 运行指示灯 | `STS_` | STS_Run |
| 报警指示灯 | `LMP_` | LMP_Fault |
| 数值 IO 域 | `IO_` | IO_Speed |
| 符号 IO 域 | `SIO_` | SIO_State |

**自动检测逻辑**：

- **按钮类型检测**：通过关键词（切换/自保持/手动自动）或 ID 前缀（MEM_）
- **指示灯类型检测**：通过颜色（红色系）、关键词（故障/报警）、blink 属性
- **数据类型推断**：根据 `display_format` 推断（Decimal→Real，String→String）

**VBS 脚本生成**：

```python
# 自保持按钮
VBS_TOGGLE_TEMPLATE = "' {purpose}\nSmartTags(\"{tag_name}\") = Not SmartTags(\"{tag_name}\")\n"

# 瞬时按钮
VBS_MOMENTARY_PRESS_TEMPLATE = "' {purpose} — 按下置位\nSmartTags(\"{tag_name}\") = 1\n"
VBS_MOMENTARY_RELEASE_TEMPLATE = "' {purpose} — 释放复位\nSmartTags(\"{tag_name}\") = 0\n"
```

**代码位置**：`backend/variable_engine.py:93-687`

---

### 5. **simaticml_generator.py** - SimaticML XML 生成器

**功能**：将校验后的 IR 转换成带 SimaticML 命名空间的 XML。

**生成的对象 XML 结构**：

```xml
<ScreenItem ID="uuid" Name="IO_Speed" Type="IOField">
  <Geometry>
    <X>100</X>
    <Y>120</Y>
    <Width>140</Width>
    <Height>40</Height>
  </Geometry>
  <Properties>
    <Mode>Output</Mode>
    <OutputFormat>Decimal</OutputFormat>
    <FontSize>16</FontSize>
  </Properties>
  <Connection>
    <ProcessTag>Motor_Speed</ProcessTag>
  </Connection>
</ScreenItem>
```

**MultilingualText 标准**：

```xml
<MultilingualText>
  <Text Language="zh-CN">安全文本</Text>
</MultilingualText>
```

**关键特性**：

- 自动从参考 XML 提取命名空间和结构信息
- 支持 Basic/Comfort/Unified 不同 HMI 类型
- XML 校验 + 自动修复（`repair_tia_xml`）

**代码位置**：`backend/simaticml_generator.py:1-702`

---

### 6. **pipeline_orchestrator.py** - 多阶段流水线

**功能**：将生成 → 预览 → MiMo 视觉审查 → 修正 → 再审查串联为 SSE 事件流。

**流水线状态机**：

```
pipeline_start
    → [image_analysis]           # 可选：分析上传的参考图片
    → generate_start             # Stage 1: 初始生成
    → review_start               # 审查开始
    → review_result              # 审查结果
        ├─ review_pass → pipeline_done  # 审查通过
        ├─ 达到最大迭代 → pipeline_done
        └─ regenerate_start → (回到 generate_start)
```

**SSE 事件类型**：
| 事件 | 数据 |
|------|------|
| `pipeline_start` | `{max_iterations}` |
| `thinking` | 思考过程增量文本 |
| `content` | 正文增量文本 |
| `parsed_ok` | `{hint}` |
| `review_start` | `{iteration}` |
| `review_result` | `{pass, score, categories, summary, critical_issues, suggestions}` |
| `variable_bind` | `{summary}` |
| `pipeline_done` | `{ir, iterations, final_score, passed}` |

**代码位置**：`backend/pipeline_orchestrator.py:131-354`

---

### 7. **openness_manager.py** - TIA Portal Openness 连接管理

**功能**：通过 pythonnet 加载 Siemens.Engineering.dll，连接 TIA Portal 并导入画面。

**支持的生成模式**：
| 模式 | 说明 | 适用 HMI 类型 |
|------|------|--------------|
| `unified_direct` | 通过 Openness 对象模型直接创建 | Unified |
| `classic_template_xml` | 基于模板 XML 改写后导入 | Basic/Comfort |
| `simaticml` | 从零生成 SimaticML XML | 通用 |
| `auto` | 自动选择最佳模式 | - |

**关键功能**：

- **环境诊断**：检查 OS、pythonnet、DLL 路径、TIA 进程
- **连接管理**：附加到运行中的博途实例
- **画面导入**：`Screens.Import(FileInfo, ImportOptions.Override)`
- **变量同步**：`sync_tags()` 写入 HMI 变量表
- **参考画面导出**：`export_reference_screen()` 用于格式校准

**XML 预处理流水线**：

1. TextNormalizer — HTML 清洗 + 控制字符移除
2. MultilingualTextBuilder — DOM 级重建
3. ScreenNumberAllocator — 删除 `<Number>` 节点
4. Screen size 对齐 — 自动缩放到目标 HMI 尺寸
5. Screen name 冲突检测 — 自动重命名
6. XmlValidator — 最终校验

**代码位置**：`backend/openness_manager.py:31-2282`

---

### 8. **mimo_client.py** - MiMo 视觉 API 客户端

**功能**：调用 MiMo-V2.5 进行视觉分析，用于 HMI 画面审查。

**支持的输出模式**：

- `brief` - 简要摘要
- `detailed` - 详细分析
- `ui` - UI 状态分析（用于 HMI 审查）
- `drawing` - 工程图纸分析

**代码位置**：`backend/mimo_client.py:203-324`

---

### 9. **prompts.py** - 提示词工程

**功能**：定义系统级提示词，指导大模型生成高质量 HMI 画面 IR。

**提示词结构**：

- `SYSTEM_PROMPT` - 系统角色定义 + 工作方式说明
- `TEXT_CONVENTIONS` - 文字与命名规范
- `TAG_CONVENTIONS` - 变量绑定硬性规范
- `VBS_CONVENTIONS` - VBS 脚本规范
- `LAYOUT_CONVENTIONS` - 布局与排版硬性规范
- `JSON_SELF_CHECK` - 输出前自检清单
- `IR_SCHEMA_DOC` - IR JSON Schema 文档

**Few-shot 示例**：

```python
FEW_SHOT_USER = "一个电机启停控制画面：启动/停止/复位三个按钮，运行指示灯、故障指示灯（故障时闪烁），显示电机转速（rpm）和当前运行模式（停止/手动/自动）。"
```

**代码位置**：`backend/prompts.py:1-400`

---

## 🔄 核心工作流程

### 流程 1：简单生成（无审查）

```
用户输入需求 → LLMClient.stream() → 流式输出 IR JSON
    → validate_ir() → VariableEngine.generate()
    → generate_simaticml() → 输出 XML 文件
```

### 流程 2：带视觉审查的生成（推荐）

```
用户输入需求 → [图片分析] → LLMClient.stream() → 初始 IR
    → validate_ir() → VariableEngine.generate()
    → render_ir_to_png() → MiMo 视觉审查
    ├── 审查通过 → 输出最终 IR
    └── 审查不通过 → 基于反馈修正 → 再次审查（最多 N 轮）
    → generate_simaticml() → 输出 XML
```

### 流程 3：导入到 TIA Portal

```
IR JSON → OpennessManager.import_or_generate_from_ir()
    ├── Unified HMI → create_unified_screen_from_ir()
    ├── Classic HMI + 模板 → template_xml_generator → import_screen_xml()
    └── 通用 → generate_simaticml() → import_screen()
    → sync_tags() → 同步变量到 HMI 变量表
    → [可选] compile + save
```

---

## 📊 配置说明

**配置文件**：`config.yaml`

```yaml
llm:
  active_provider: deepseek      # 活跃的 LLM 提供商
  thinking_depth: 中              # 思考深度：关闭/低/中/高
  providers:
    deepseek:
      base_url: https://api.deepseek.com
      api_key: sk-xxx
      chat_model: deepseek-v4-pro
      reasoner_model: deepseek-reasoner

openness:
  tia_version: V16                # TIA Portal 版本
  dll_path: C:\...\Siemens.Engineering.dll
  hmi_device: HMI_1               # HMI 设备名称
  generation_mode: auto           # 生成模式
  classic_template:
    enabled: true
    template_xml_path: exports/templates/画面_1_template.xml

mimo:
  enabled: true                   # 启用 MiMo 视觉审查
  api_key: sk-xxx
  max_iterations: 6               # 最大审查迭代次数
  review_pass_threshold: 80       # 审查通过阈值（0-100）

hmi_defaults:
  resolution: 800x480             # 默认分辨率
  hmi_type: Basic                 # 默认 HMI 类型
  background_color: '#D9DEE5'
```

---

## 🛠️ 技术亮点

### 1. **多阶段流水线架构**

- 生成 → 预览 → 审查 → 修正的闭环流程
- SSE 实时流式输出，用户体验流畅
- 支持多轮迭代优化（最多 6 轮）

### 2. **智能变量引擎**

- 自动识别按钮类型（瞬时/自保持）
- 自动推断指示灯类型（状态/报警）
- 根据 display_format 推断数据类型
- 自动生成 VBS 脚本

### 3. **自动排版优化**

- 控件对齐（同行水平对齐）
- 最小间距保证（按钮≥24px，IO域≥20px）
- 多轮重叠修复
- 边界裁剪

### 4. **TIA Portal 深度集成**

- 支持 Basic/Comfort/Unified 全系列 HMI
- 自动检测 HMI 设备类型
- 多种生成模式自动路由
- 变量表自动同步

### 5. **健壮的 XML 处理**

- MultilingualText DOM 级重建
- HTML 标签自动清洗
- 控制字符移除
- Screen Number 冲突检测
- Screen Size 自动对齐

---

## 📦 依赖项

```
flask>=2.0
requests>=2.25
pyyaml>=5.4
pdfplumber>=0.6        # PDF 解析
Pillow>=8.0            # 图片处理
pythonnet>=3.0         # TIA Portal Openness（仅 Windows）
```

---

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 config.yaml

- 填写 DeepSeek API Key
- 配置 TIA Portal DLL 路径
- 设置 HMI 设备名称

### 3. 启动服务

```bash
python app.py
```

### 4. 访问界面

打开浏览器访问 `http://127.0.0.1:5000`

---

## 🧪 测试

```bash
# 运行所有测试
pytest tests/

# 运行特定测试
pytest tests/test_hmi_ir.py
pytest tests/test_flask_api.py
pytest tests/test_openness_manager.py
```

---

## 📝 版本历史

| 版本   | 日期      | 主要更新           |
| ---- | ------- | -------------- |
| V1.0 | 2024-01 | 基础功能实现         |
| V2.0 | 2024-03 | 支持 Basic 系列    |
| V2.1 | 2024-05 | 排版优化           |
| V2.2 | 2024-07 | 前端界面修复         |
| V2.3 | 2024-09 | 变量引擎 + 视觉审查流水线 |

---

## 🎯 未来规划

- [ ] 支持更多 HMI 控件类型（趋势图、报警视图等）
- [ ] 多语言支持（英文界面）
- [ ] 画面模板库
- [ ] 批量画面生成
- [ ] 与 PLC 程序联动
- [ ] 云端部署方案

---

## 📄 许可证

本项目为私有项目，仅供内部使用。

---

## 👥 贡献者

- **sunny** - 项目负责人 & 主要开发者

---

*最后更新：2026-06-19*

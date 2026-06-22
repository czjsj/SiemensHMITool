# Siemens HMI 画面助手 - 后端工程架构分析文档

> **版本**: V6.5  
> **分析日期**: 2026-06-22  
> **技术栈**: Python 3.10+ / Flask / 大模型API / TIA Portal Openness

---

## 一、项目概述

### 1.1 项目定位

Siemens HMI 画面助手是一款基于 AI 大模型的西门子 HMI 画面自动生成工具。用户通过中文自然语言描述需求，系统自动生成可导入 TIA Portal 的 HMI 画面 XML。

### 1.2 核心能力

- **AI 画面生成**: 将中文需求转换为 HMI 画面中间表示（IR）
- **多模型支持**: DeepSeek、OpenAI 兼容接口
- **视觉审查**: MiMo 视觉模型审查生成的 HMI 画面
- **TIA Portal 集成**: 通过 Openness API 自动导入画面到博途
- **多 HMI 类型支持**: Basic / Comfort / Unified 面板

---

## 二、后端目录结构

```
backend/
├── __init__.py                    # 包初始化
├── hmi_ir.py                      # HMI画面IR校验与归一化（核心）
├── pipeline_orchestrator.py       # 多阶段流水线编排器（核心）
├── llm_client.py                  # 大模型客户端（DeepSeek/OpenAI）
├── mimo_client.py                 # MiMo视觉审查客户端
├── variable_engine.py             # HMI变量引擎（核心）
├── import_engine.py               # TIA导入引擎
├── simaticml_generator.py         # SimaticML XML生成器
├── openness_manager.py            # TIA Portal Openness连接管理器
├── config_manager.py              # 配置文件读写
├── prompts.py                     # AI提示词系统
├── review_prompts.py              # 视觉审查提示词
├── generation_summary.py          # 生成摘要
├── preview_renderer.py            # 预览图渲染
├── text_normalizer.py             # 文本清洗器
├── multilingual_text_builder.py   # 多语言文本构建器
├── screen_number_allocator.py     # 画面编号分配器
├── xml_validator.py               # XML校验器
├── tag_binding_normalizer.py      # 变量绑定规范化器
├── tia_text_sanitizer.py          # TIA文本清洗器
├── template_xml_generator.py      # 模板XML生成器
│
├── domain/                        # 领域模型层
│   ├── ir_v2.py                   # HMI IR V2数据模型（Pydantic）
│   ├── enums.py                   # 枚举定义
│   ├── diagnostics.py             # 诊断信息
│   ├── deployment_plan.py         # 部署计划
│   ├── deployment_result.py       # 部署结果
│   ├── validation.py              # 验证逻辑
│   └── legacy_adapter.py          # 旧格式适配器
│
├── backends/                      # 后端实现层
│   ├── base.py                    # HmiBackend抽象基类
│   ├── classic/                   # Basic/Comfort经典HMI后端
│   │   ├── basic_backend.py       # Basic面板后端
│   │   ├── comfort_backend.py     # Comfort面板后端
│   │   ├── tag_xml_builder.py     # 变量XML构建器
│   │   ├── screen_xml_builder.py  # 画面XML构建器
│   │   ├── function_list_builder.py # 函数列表构建器
│   │   ├── dynamic_xml_builder.py # 动态XML构建器
│   │   ├── vbs_builder.py         # VBS脚本构建器
│   │   ├── xml_id_registry.py     # XML ID注册表
│   │   ├── link_resolver.py       # 链接解析器
│   │   ├── classic_validator.py   # 经典后端校验器
│   │   ├── xml_fragment_catalog.py # XML片段目录
│   │   └── classic_screen_reference_rewriter.py # 画面引用重写器
│   │
│   └── unified/                   # WinCC Unified后端
│       ├── unified_backend.py     # Unified后端实现
│       ├── tag_builder.py         # Unified变量构建器
│       ├── screen_builder.py      # Unified画面构建器
│       ├── property_builder.py    # 属性构建器
│       ├── binding_builder.py     # 绑定构建器
│       ├── event_builder.py       # 事件构建器
│       ├── js_builder.py          # JavaScript构建器
│       └── reflection_adapter.py  # 反射适配器
│
├── openness/                      # Openness运行时层
│   ├── assembly_loader.py         # DLL加载与版本元数据
│   ├── session_manager.py         # TIA Portal会话管理
│   ├── device_discovery.py        # HMI设备查找与类型识别
│   ├── compiler.py                # HMI编译触发
│   ├── exception_mapper.py        # .NET异常→Diagnostic转换
│   ├── classic_executor.py        # 经典后端执行器
│   ├── unified_executor.py        # Unified后端执行器
│   ├── object_query_service.py    # 对象查询服务
│   ├── reflection_utils.py        # 反射工具
│   ├── runtime_contract.py        # 运行时契约
│   └── diagnostics_utils.py       # 诊断工具
│
├── planners/                      # 部署规划层
│   ├── dependency_graph.py        # 依赖图构建与拓扑排序
│   └── deployment_planner.py      # 部署计划器
│
├── services/                      # 服务层
│   ├── deployment_service.py      # 部署服务
│   └── verification_service.py    # 验证服务
│
├── capabilities/                  # 设备能力层
│   ├── static_matrix.py           # 静态设备能力对照表
│   └── capability_service.py      # 能力服务
│
├── template/                      # 模板原型系统
│   ├── prototype_extractor.py     # 原型提取器
│   ├── prototype_registry.py      # 原型注册表
│   ├── template_profile.py        # 模板配置文件
│   ├── binding_pattern_extractor.py # 绑定模式提取器
│   ├── event_pattern_extractor.py # 事件模式提取器
│   ├── template_binding_validator.py # 模板绑定校验器
│   ├── xml_rewrite_rules.py       # XML重写规则
│   └── xml_utils.py               # XML工具
│
├── validation/                    # 校验层
│   └── tag_binding_gate.py        # 变量绑定校验闸门
│
├── references/                    # 参考资料
│   └── catalog_service.py         # 目录服务
│
├── utils/                         # 工具层
│   └── tag_prefix_utils.py        # 变量前缀工具
│
└── debug/                         # 调试工具
    └── tag_pipeline_debug.py      # 变量管道调试
```

---

## 三、核心模块详解

### 3.1 HMI IR（中间表示）- `hmi_ir.py`

**职责**: 对大模型产出的 JSON 做结构检查、补默认值、交叉引用校验。

**核心功能**:
- IR 结构校验与归一化
- 支持 Basic / Comfort / Unified 三种 HMI 类型
- 接受常见分辨率及合法自定义 WxH 分辨率
- 轻量级自动排版优化（控件重叠、行间距、对齐）

**支持的对象类型**:
- `IOField` - 数值/字符串输入输出域
- `SymbolicIOField` - 符号IO域（文本列表选择）
- `Button` - 按钮（瞬时/自保持）
- `Indicator` - 指示灯（状态/报警）
- `Text` - 静态文本

**变量命名前缀规则**:
```python
TAG_PREFIX_MAP = {
    "Button":    "BTN_",        # 瞬时按钮
    "Indicator": "STS_",        # 运行/状态指示灯（报警类用 LMP_）
    "IOField":   "IO_",
    "SymbolicIOField": "SIO_",
}
```

---

### 3.2 多阶段流水线编排器 - `pipeline_orchestrator.py`

**职责**: 将「生成 → 预览渲染 → MiMo 视觉审查 → 修正 → 再审查」串联为 SSE 事件生成器。

**流水线状态机**:
```
pipeline_start → [image_analysis] → generate_start →
review_start → review_result →
  ├─ review_pass → pipeline_done
  ├─ 达到最大迭代 → pipeline_done
  └─ regenerate_start → (回到 generate_start 的下一轮)
```

**处理流程**:
1. **图片分析** (可选): 用 MiMo 分析上传的参考图片
2. **初始生成**: 调用大模型生成 HMI IR JSON
3. **IR 校验**: `validate_ir()` 结构检查与归一化
4. **分辨率适配**: 将 IR 坐标适配到目标 HMI 分辨率
5. **文本清洗**: `sanitize_ir_text_fields()` 去除 HTML/富文本
6. **变量引擎**: `VariableEngine.generate()` 自动绑定变量
7. **视觉审查循环** (可选): MiMo 审查 → 修正 → 再审查

---

### 3.3 大模型客户端 - `llm_client.py`

**职责**: 通过 OpenAI 兼容接口调用大模型，支持流式输出。

**支持的模型**:
- DeepSeek (deepseek-chat / deepseek-reasoner)
- OpenAI 兼容接口 (gpt-4o-mini 等)

**思考深度控制**:
```python
DEPTH_MAP = {
    "关闭": {"use_reasoner": False, "effort": None,     "hint_tokens": 0},
    "低":   {"use_reasoner": True,  "effort": "low",    "hint_tokens": 512},
    "中":   {"use_reasoner": True,  "effort": "medium", "hint_tokens": 1500},
    "高":   {"use_reasoner": True,  "effort": "high",   "hint_tokens": 4000},
}
```

**输出格式**:
- `("thinking", text)` - 思考过程增量
- `("content", text)` - 正文增量
- `("error", text)` - 错误信息

---

### 3.4 HMI 变量引擎 - `variable_engine.py`

**职责**: 将 IR 中的画面对象自动映射为工程级 HMI 变量系统。

**核心功能**:
1. **自动变量命名**: BTN_/MEM_/STS_/LMP_/IO_/SIO_ 前缀规则
2. **Button 行为模式检测**: momentary（瞬时）/ toggle（自保持）
3. **Indicator 动态颜色与闪烁变量绑定**
4. **IOField 数据类型自动推断**
5. **完整 HMI Tags 列表生成**

**V3.0 语义模型**:
- `enrich()` - 将旧 IR 转换为语义 HmiProjectSpec
- `generate()` - 旧兼容入口

**变量类型推断规则**:
- 按钮/开关 → `Bool`
- 指示灯 → `Bool`
- SymbolicIO → `Int`
- IOField → 根据显式 data_type 或文本语义推断（温度/压力等 → `Real`）

**PLC 地址映射（四层策略）**:
1. 精确变量名匹配
2. 去掉 BTN_/STS_/LMP_ 前缀后匹配
3. 按 item id 匹配
4. 按中文文本匹配

---

### 3.5 TIA 导入引擎 - `import_engine.py`

**职责**: 通过 Openness API 将已校验的 XML 安全导入 TIA Portal。

**强制约束（Error Protection）**:
- ✅ Fail Fast: 任何 XML 不合法 → 直接阻断
- ✅ No Partial Fix: 不"修一半继续导入"
- ✅ No Hacks: 禁止 ScreenComposition.Import、反射 Import
- ✅ Single Method: 唯一允许的导入方式：`Screens.Import(FileInfo, ImportOptions.Override)`

**管线流程**:
```
TextNormalizer → MultilingualTextBuilder → ScreenNumberAllocator
→ XmlValidator（闸门） → ImportEngine（终端）
```

---

### 3.6 SimaticML 生成器 - `simaticml_generator.py`

**职责**: 把校验后的 IR 转换成带 SimaticML 命名空间的 XML。

**支持的对象类型**:
- IOField → `<ScreenItem Type="IOField">`
- SymbolicIOField → `<ScreenItem Type="SymbolicIOField">`
- Button → `<ScreenItem Type="Button">`
- Indicator → `<ScreenItem Type="Circle">` + 动画
- Text → `<ScreenItem Type="TextField">`

**MultilingualText 标准**:
```xml
<MultilingualText>
  <Text Language="zh-CN">安全文本</Text>
</MultilingualText>
```

---

### 3.7 Openness 连接管理器 - `openness_manager.py`

**职责**: 通过 pythonnet 加载 Siemens.Engineering.dll，附加到正在运行的博途实例。

**运行前提**:
- 操作系统：Windows
- 已安装 TIA Portal 与 Openness
- 用户已加入 "Siemens TIA Openness" 用户组
- Siemens.Engineering.dll 路径正确

**核心功能**:
1. **环境诊断**: `diagnose()` - 检查运行环境
2. **连接管理**: `connect()` - 附加到博途实例
3. **HMI 类型识别**: `get_hmi_capabilities()` - 识别 Basic/Comfort/Unified
4. **变量同步**: `sync_tags()` - 将 HMI Tags 写入 TIA
5. **画面导入**: `import_screen()` / `import_screen_xml()`
6. **Unified 直接生成**: `create_unified_screen_from_ir()`
7. **模板导出**: `export_screen_xml_template()`

**V4.2 家族感知路由**:
- Classic (Basic/Comfort) → TagXmlBuilder + ClassicOpennessExecutor
- Unified → UnifiedOpennessExecutor
- Unknown → 反射探测 + 结构化诊断

---

## 四、领域模型层 - `domain/`

### 4.1 HMI IR V2 数据模型 - `ir_v2.py`

使用 Pydantic v2 定义，不依赖 Flask、pythonnet 或 Siemens DLL。

**核心模型**:
```python
class HmiProjectSpec(BaseModel):
    """HMI 工程完整语义 IR — 顶层模型。"""
    schema_version: Literal["2.0"] = "2.0"
    metadata: ProjectMetadata
    target: TargetSpec
    connections: list[ConnectionSpec]
    tags: list[TagSpec]
    scripts: list[ScriptSpec]
    resources: list[ResourceSpec]
    screens: list[ScreenSpec]
    policies: DeploymentPolicies
    diagnostics: list[Diagnostic]
```

**主要模型说明**:
- `TargetSpec` - 目标 HMI 设备规格（family, tia_version, device_name, resolution）
- `TagSpec` - HMI 变量规格（name, data_type, scope, address）
- `ScreenSpec` - 画面规格（name, width, height, items）
- `ScreenItemSpec` - 画面控件规格（type, geometry, properties, bindings, events）
- `BindingSpec` - 动态属性绑定（direct_tag, discrete, flashing 等）
- `EventSpec` / `ActionSpec` - 事件与动作模型

### 4.2 枚举定义 - `enums.py`

**HMI 家族**:
```python
class HmiFamily(str, Enum):
    BASIC = "basic"
    COMFORT = "comfort"
    UNIFIED = "unified"
    AUTO = "auto"
```

**画面控件类型**:
```python
class ScreenItemType(str, Enum):
    TEXT = "text"
    BUTTON = "button"
    IO_FIELD = "io_field"
    SYMBOLIC_IO_FIELD = "symbolic_io_field"
    INDICATOR = "indicator"
    # ... 更多类型
```

**部署阶段**:
```python
class DeploymentPhase(str, Enum):
    P00_DISCOVERY = "P00_DISCOVERY"
    P10_VALIDATE_DEPENDENCIES = "P10_VALIDATE_DEPENDENCIES"
    P20_CONNECTIONS = "P20_CONNECTIONS"
    P30_TAG_TABLES_AND_TAGS = "P30_TAG_TABLES_AND_TAGS"
    P40_SCRIPTS_AND_RESOURCES = "P40_SCRIPTS_AND_RESOURCES"
    P50_SCREENS = "P50_SCREENS"
    P60_BINDINGS_AND_EVENTS = "P60_BINDINGS_AND_EVENTS"
    P70_COMPILE = "P70_COMPILE"
    P80_VERIFY = "P80_VERIFY"
    P90_SAVE = "P90_SAVE"
```

---

## 五、后端实现层 - `backends/`

### 5.1 抽象基类 - `base.py`

```python
class HmiBackend(ABC):
    """HMI 部署后端统一接口。"""

    @abstractmethod
    def supports(self, target: TargetSpec) -> bool:
        """判断是否支持目标设备。"""

    @abstractmethod
    def build_plan(self, spec: HmiProjectSpec, context: dict | None = None) -> DeploymentPlan:
        """构建部署计划。"""

    @abstractmethod
    def execute(self, plan: DeploymentPlan, context: dict | None = None) -> DeploymentResult:
        """执行部署。"""

    @abstractmethod
    def verify(self, spec: HmiProjectSpec, context: dict | None = None) -> VerificationResult:
        """验证部署结果。"""
```

### 5.2 Classic 后端 - `backends/classic/`

适用于 Basic 和 Comfort 面板，通过 XML 导入方式生成画面。

**核心组件**:
- `TagXmlBuilder` - 生成 HMI 变量表 XML
- `ScreenXmlBuilder` - 生成画面 XML
- `FunctionListBuilder` - 生成函数列表 XML
- `DynamicXmlBuilder` - 生成动态属性 XML
- `VbsBuilder` - 生成 VBS 脚本
- `XmlIdRegistry` - 管理 XML ID 唯一性
- `LinkResolver` - 解析变量链接
- `ClassicValidator` - 校验 Classic XML

### 5.3 Unified 后端 - `backends/unified/`

适用于 WinCC Unified 面板，通过 Openness 对象模型直接创建画面。

**核心组件**:
- `UnifiedBackend` - Unified 后端主类
- `UnifiedTagBuilder` - 创建 Unified 变量
- `UnifiedScreenBuilder` - 创建 Unified 画面
- `UnifiedPropertyBuilder` - 设置控件属性
- `UnifiedBindingBuilder` - 创建动态绑定
- `UnifiedEventBuilder` - 创建事件处理
- `JsBuilder` - 生成 JavaScript 代码
- `UnifiedReflectionAdapter` - .NET 反射适配器

---

## 六、提示词系统 - `prompts.py`

### 6.1 系统提示词结构

```
SYSTEM_PROMPT = """
你是一名资深的西门子 WinCC / 博途(TIA Portal) HMI 画面工程师...

【工作方式】
- 先梳理需求涉及的状态量、操作量、显示量
- 优先做"工程可交付"的版式

【文字与命名规范】
- 画面上所有面向操作员的可见文字一律使用简体中文
- 变量名、对象ID、画面名、脚本名一律使用英文 + 下划线

【变量绑定硬性规范】
- 所有 Button / Indicator / IOField / SymbolicIOField 都必须包含 process_tag
- 变量名强制格式：{类型前缀}_{控件/设备名}_{具体功能}

【VBS 脚本规范】
- 读写变量统一使用 SmartTags("变量名")

【布局与排版硬性规范】
- 先分区，再放控件
- 页面四周留边距
- 同一行控件必须顶部或中心对齐

【V4.0 模板绑定约束】
- 你不能直接生成 TIA XML
- 你只能输出 HMI IR JSON

【输出格式】
{IR_SCHEMA_DOC}
"""
```

### 6.2 Few-Shot 示例

系统包含一个完整的电机控制画面示例，展示：
- 变量命名规范（BTN_Motor_Start, STS_Motor_Running 等）
- 对象布局规范（标题区、控制区、状态区、参数显示区）
- VBS 脚本规范（SmartTags 读写）

---

## 七、配置管理 - `config_manager.py`

### 7.1 配置结构

```yaml
llm:
  active_provider: "deepseek"
  thinking_depth: "中"  # 关闭 / 低 / 中 / 高
  providers:
    deepseek:
      base_url: "https://api.deepseek.com"
      api_key: ""
      chat_model: "deepseek-chat"
      reasoner_model: "deepseek-reasoner"

openness:
  tia_version: "V18"
  dll_path: "C:\\Program Files\\Siemens\\Automation\\Portal V18\\..."
  attach_running: True
  hmi_device: "HMI_1"
  generation_mode: "auto"  # auto | unified_direct | classic_template_xml | simaticml

hmi_defaults:
  resolution: "1280x800"
  hmi_type: "Comfort"  # Basic | Comfort | Unified

mimo:
  enabled: False
  api_key: ""
  max_iterations: 3
  review_pass_threshold: 70
```

---

## 八、Openness 运行时层 - `openness/`

### 8.1 模块职责

| 模块 | 职责 |
|------|------|
| `assembly_loader` | DLL 加载与版本元数据 |
| `session_manager` | TIA Portal 会话（Attach/Open/Dispose） |
| `device_discovery` | HMI 设备查找与类型识别 |
| `compiler` | HMI 编译触发 |
| `exception_mapper` | .NET 异常 → Diagnostic 转换 |
| `classic_executor` | 经典后端执行器（XML 导入） |
| `unified_executor` | Unified 后端执行器（直接对象模型） |

### 8.2 设备能力识别

```python
def get_hmi_capabilities(self) -> dict:
    """返回当前 HMI 设备的能力信息。"""
    return {
        "connected": True,
        "hmi_family": "Comfort",  # Basic | Comfort | Unified | Unknown
        "is_unified": False,
        "is_classic": True,
        "supports_direct_screen_items": False,
        "supports_screen_xml_export_import": True,
        "recommended_mode": "classic_template_xml",
        "available_screens": ["Screen_1", "Screen_2"],
    }
```

---

## 九、部署规划层 - `planners/`

### 9.1 依赖图

```python
class DependencyGraph:
    """构建部署任务的依赖图，支持拓扑排序。"""
    def add_task(self, task_id: str, dependencies: list[str] = None)
    def topological_sort(self) -> list[str]
```

### 9.2 部署计划器

```python
class DeploymentPlanner:
    """从 HmiProjectSpec 构建 DeploymentPlan。"""
    def plan(self, spec: HmiProjectSpec) -> DeploymentPlan
```

**部署阶段顺序**:
1. P00_DISCOVERY - 发现目标设备
2. P10_VALIDATE_DEPENDENCIES - 验证依赖
3. P20_CONNECTIONS - 创建连接
4. P30_TAG_TABLES_AND_TAGS - 创建变量表和变量
5. P40_SCRIPTS_AND_RESOURCES - 创建脚本和资源
6. P50_SCREENS - 创建画面
7. P60_BINDINGS_AND_EVENTS - 创建绑定和事件
8. P70_COMPILE - 编译
9. P80_VERIFY - 验证
10. P90_SAVE - 保存

---

## 十、测试结构

```
tests/
├── test_hmi_ir.py                    # IR 校验测试
├── test_variable_engine_v2.py        # 变量引擎测试
├── test_variable_engine_tag_types.py # 变量类型测试
├── test_tag_binding_normalizer.py    # 变量绑定规范化测试
├── test_classic_builders.py          # Classic 构建器测试
├── test_unified_backend.py           # Unified 后端测试
├── test_openness_manager.py          # Openness 管理器测试
├── test_deployment_pipeline.py       # 部署管道测试
├── test_planners.py                  # 部署规划器测试
├── test_capabilities.py              # 设备能力测试
├── test_domain_ir_v2.py              # 领域模型测试
├── test_domain_diagnostics.py        # 诊断信息测试
├── test_domain_legacy_adapter.py     # 旧格式适配器测试
├── test_flask_api.py                 # Flask API 测试
├── test_generation_summary.py        # 生成摘要测试
├── test_template_xml_generator.py    # 模板XML生成器测试
├── test_verification.py              # 验证服务测试
├── test_v55_integration_regression.py # V5.5 集成回归测试
└── test_tag_xml_generation_and_validation.py # 变量XML生成测试
```

---

## 十一、技术特点总结

### 11.1 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Flask API 层 (app.py)                     │
├─────────────────────────────────────────────────────────────┤
│                  流水线编排层 (pipeline_orchestrator)         │
├─────────────────────────────────────────────────────────────┤
│    AI 生成层     │    变量引擎层    │    XML 生成层          │
│  (llm_client)   │ (variable_engine)│ (simaticml_generator)  │
├─────────────────────────────────────────────────────────────┤
│                  领域模型层 (domain/)                         │
├─────────────────────────────────────────────────────────────┤
│    Classic 后端  │   Unified 后端   │   模板系统             │
│  (backends/)    │  (backends/)    │   (template/)          │
├─────────────────────────────────────────────────────────────┤
│              Openness 运行时层 (openness/)                    │
├─────────────────────────────────────────────────────────────┤
│              TIA Portal Openness API (.NET)                  │
└─────────────────────────────────────────────────────────────┘
```

### 11.2 关键设计决策

1. **IR 作为核心中间表示**: 所有生成和导入都基于统一的 IR 格式
2. **家族感知路由**: 根据 HMI 类型自动选择 Classic 或 Unified 路径
3. **Fail Fast 原则**: XML 校验不通过直接阻断，不尝试修复
4. **变量命名强制规范**: BTN_/MEM_/STS_/LMP_/IO_/SIO_ 前缀规则
5. **MultilingualText 标准**: 所有用户可见文本必须使用多语言文本包裹
6. **非 Windows 诊断模式**: 无 pythonnet 环境自动进入诊断模式，不崩溃

### 11.3 依赖项

```txt
Flask>=3.0.0          # Web 框架
PyYAML>=6.0           # 配置文件读写
requests>=2.31.0      # HTTP 客户端
pdfplumber>=0.10.0    # PDF 解析
Pillow>=10.0.0        # 图片处理
pythonnet>=3.0.3      # .NET 互操作（仅 Windows）
```

---

## 十二、总结

Siemens HMI 画面助手的后端工程采用了清晰的分层架构，将 AI 生成、变量引擎、XML 生成、TIA Portal 集成等职责分离。通过统一的 IR 中间表示和家族感知路由机制，支持多种 HMI 面板类型。严格的校验机制和 Fail Fast 原则确保了生成的 XML 能够成功导入 TIA Portal。

项目代码结构清晰，模块职责明确，测试覆盖全面，是一个工程化程度较高的工业自动化辅助工具。

# Claude Code 执行任务书：Siemens HMI Assistant 全自动 HMI 生成器增强计划

## 总目标

在现有 Siemens HMI Assistant 后端基础上，实现完整闭环：

自然语言输入  
→ AI 理解需求  
→ 输出 HMI 语义 IR / HmiProjectSpec  
→ 自动生成变量  
→ 自动生成画面控件  
→ 按钮继承模板按钮事件  
→ 指示灯继承模板指示灯动态绑定  
→ 变量导入 TIA Portal / 博途  
→ 画面导入 TIA Portal / 博途  
→ 控件自动连接对应变量  
→ 编译与验证通过。

核心原则：

1. AI 只输出语义 IR，不直接生成 TIA XML 事件细节。

2. 按钮、指示灯的事件和动态绑定必须来自模板控件。

3. 新控件通过克隆模板控件生成，只替换名称、位置、尺寸、文本、变量引用、事件变量引用。

4. 导入前必须验证 XML、变量、控件、事件、动态绑定完整性。

5. 导入后必须验证变量存在、画面存在、控件存在、绑定无残留模板变量。

---

# 阶段 0：代码基线检查与保护

## 目标

在动手改造前，确认现有代码结构、测试方式、运行入口和关键函数，避免破坏已有流水线。

## 需要检查的文件

- backend/pipeline_orchestrator.py

- backend/variable_engine.py

- backend/template_xml_generator.py

- backend/simaticml_generator.py

- backend/import_engine.py

- backend/xml_validator.py

- backend/openness_manager.py

- backend/domain/ir_v2.py

- backend/domain/validation.py

- backend/services/deployment_service.py

- backend/services/verification_service.py

- backend/backends/classic/*

- backend/backends/unified/*

## 执行步骤

1. 搜索所有现有入口函数：
   
   - generate_from_template_xml
   
   - generate_simaticml
   
   - validate_ir
   
   - validate_ir_v2
   
   - VariableEngine
   
   - import_or_generate_from_ir
   
   - sync_tags
   
   - build_plan
   
   - execute
   
   - verify

2. 建立一份当前调用链说明，写入：
   
   - docs/auto_hmi_generation_call_chain.md

3. 新建测试目录，如果已有则复用：
   
   - tests/template/
   
   - tests/variable/
   
   - tests/deployment/
   
   - tests/fixtures/

4. 新建样例 fixture：
   
   - tests/fixtures/template_button_indicator.xml
   
   - tests/fixtures/ir_motor_control.json

5. 不要删除任何现有接口。

6. 所有新功能尽量以新增模块方式接入，减少对旧逻辑的破坏。

7. 保持向后兼容：旧 dict IR 仍然可通过 legacy_adapter 转换。

## 验收标准

- 项目能正常启动。

- 现有导入路径没有被移除。

- 新增 docs/auto_hmi_generation_call_chain.md。

- 新增 tests/fixtures 目录。

- 当前所有测试能通过，或至少没有新增语法错误。

---

# 阶段 1：新增模板原型系统

## 目标

从模板 XML 中自动识别按钮和指示灯控件，将它们注册为可复用原型。后续生成的按钮和指示灯不从零生成 XML，而是克隆模板原型。

## 新增目录

backend/template/

## 新增文件

- backend/template/**init**.py

- backend/template/template_profile.py

- backend/template/prototype_extractor.py

- backend/template/prototype_registry.py

- backend/template/event_pattern_extractor.py

- backend/template/binding_pattern_extractor.py

- backend/template/xml_rewrite_rules.py

- backend/template/xml_utils.py

## 1.1 定义 TemplateProfile 数据模型

文件：backend/template/template_profile.py

需要定义：

```python
from dataclasses import dataclass, field
from typing import Any, Literal

ItemKind = Literal["button", "indicator", "io_field", "symbolic_io_field", "text", "unknown"]

@dataclass
class TagReference:
    tag_name: str
    location: str
    xml_path: str | None = None
    raw_value: str | None = None

@dataclass
class EventPattern:
    event_name: str
    action_type: str | None = None
    tag_references: list[TagReference] = field(default_factory=list)
    raw_xml: str | None = None

@dataclass
class BindingPattern:
    binding_kind: str
    property_name: str | None = None
    tag_references: list[TagReference] = field(default_factory=list)
    raw_xml: str | None = None

@dataclass
class ControlPrototype:
    prototype_id: str
    source_name: str
    item_kind: ItemKind
    behavior: str | None = None
    indicator_mode: str | None = None
    xml_node: Any | None = None
    tag_references: list[TagReference] = field(default_factory=list)
    event_patterns: list[EventPattern] = field(default_factory=list)
    binding_patterns: list[BindingPattern] = field(default_factory=list)
    replaceable_tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class TemplateProfile:
    screen_name: str | None = None
    buttons: list[ControlPrototype] = field(default_factory=list)
    indicators: list[ControlPrototype] = field(default_factory=list)
    others: list[ControlPrototype] = field(default_factory=list)
    all_tag_references: list[TagReference] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)

    def all_prototypes(self) -> list[ControlPrototype]:
        return self.buttons + self.indicators + self.others
```

## 1.2 实现 XML 工具函数

文件：backend/template/xml_utils.py

需要实现：

```python
def local_name(tag: str) -> str:
    """去掉 XML namespace，返回本地标签名。"""

def get_attr_case_insensitive(node, *names: str) -> str | None:
    """大小写不敏感地读取属性。"""

def node_to_string(node) -> str:
    """将 XML 节点转字符串。"""

def deepcopy_xml_node(node):
    """深拷贝 XML 节点。"""

def iter_nodes(root):
    """遍历所有节点。"""

def find_text_like_values(node) -> list[str]:
    """查找可能含有文本、变量名、表达式的属性和文本内容。"""

def detect_control_name(node) -> str | None:
    """识别控件名称，例如 Name、ObjectName、名称属性等。"""

def detect_control_type(node) -> str:
    """根据标签名、属性名、控件名推断 button / indicator / io_field / text。"""

def assign_new_ids(node, id_registry=None) -> None:
    """为克隆节点分配新的 SimaticML ID / UId / ID，避免重复。"""
```

注意：

- 必须兼容 namespace。

- 不要假设 XML 标签名完全一致。

- 所有 XML 解析必须使用 ElementTree 或 lxml，优先复用项目现有 XML 处理方式。

- 不要使用字符串正则直接大规模改 XML，除非只是作为兜底。

## 1.3 实现事件模式提取器

文件：backend/template/event_pattern_extractor.py

需要实现：

```python
def extract_event_patterns(control_node) -> list[EventPattern]:
    """
    从控件 XML 节点中提取事件模式。
    重点识别：
    - Click
    - Press
    - Release
    - MouseDown
    - MouseUp
    - TouchDown
    - TouchUp
    - SetBit
    - ResetBit
    - ToggleBit
    - SetValue
    - Screen navigation
    - VBS / JS script references
    """
```

需要识别的内容：

1. 事件节点名称。

2. 事件动作类型。

3. 事件中引用的变量名。

4. 脚本中引用的变量名。

5. FunctionList 里的变量引用。

6. 动作参数中的变量引用。

输出示例：

```python
EventPattern(
    event_name="Press",
    action_type="set_bit",
    tag_references=[
        TagReference(
            tag_name="Template_BTN_Start",
            location="event",
            xml_path=".../EventHandlers/.../TagName"
        )
    ]
)
```

## 1.4 实现动态绑定模式提取器

文件：backend/template/binding_pattern_extractor.py

需要实现：

```python
def extract_binding_patterns(control_node) -> list[BindingPattern]:
    """
    从控件 XML 节点中提取动态绑定模式。
    重点识别：
    - ProcessValue
    - ColorAnimation
    - FlashAnimation
    - Visibility
    - Enable
    - Text
    - Dynamization
    - Animation
    """
```

需要识别：

1. 指示灯颜色绑定变量。

2. 指示灯闪烁绑定变量。

3. IO 域过程值绑定变量。

4. 可见性绑定变量。

5. 使能绑定变量。

输出示例：

```python
BindingPattern(
    binding_kind="color",
    property_name="BackColor",
    tag_references=[
        TagReference(
            tag_name="Template_LMP_Run",
            location="dynamization",
            xml_path=".../Dynamizations/.../TagName"
        )
    ]
)
```

## 1.5 实现模板原型提取器

文件：backend/template/prototype_extractor.py

需要实现：

```python
def analyze_template_screen(template_xml: str) -> TemplateProfile:
    """
    输入模板画面 XML，输出 TemplateProfile。
    """
```

内部步骤：

1. 解析 XML。

2. 查找所有 ScreenItem / Object / HMI 控件节点。

3. 识别控件名称。

4. 根据控件名称前缀和 XML 类型判断控件种类：
   
   - BTN_ → button
   
   - Button → button
   
   - LMP_ → indicator
   
   - Lamp → indicator
   
   - Indicator → indicator
   
   - IO_ → io_field
   
   - TXT_ → text

5. 对每个控件提取：
   
   - 控件名称
   
   - 控件类型
   
   - 引用变量
   
   - 事件模式
   
   - 动态绑定模式
   
   - 原始 XML 节点

6. 推断按钮 behavior：
   
   - 同时存在 Press/Release 或 MouseDown/MouseUp 且变量一致 → momentary
   
   - Click + Toggle → toggle
   
   - Click + SetBit → set
   
   - Click + ResetBit → reset
   
   - ScreenActivate / ChangeScreen → navigate

7. 推断指示灯 indicator_mode：
   
   - 有颜色动画 → bool_color
   
   - 有闪烁动画 → bool_blink
   
   - 多状态颜色 → multi_state
   
   - 红色/报警关键词 → alarm

8. 生成 prototype_id：
   
   - 按钮：BTN_MOMENTARY_TEMPLATE、BTN_TOGGLE_TEMPLATE、BTN_SET_TEMPLATE、BTN_RESET_TEMPLATE
   
   - 指示灯：LMP_STATUS_TEMPLATE、LMP_ALARM_TEMPLATE、LMP_WARNING_TEMPLATE
   
   - 如果无法判断则用 BTN_DEFAULT_TEMPLATE 或 LMP_DEFAULT_TEMPLATE

## 1.6 实现 PrototypeRegistry

文件：backend/template/prototype_registry.py

需要实现：

```python
class PrototypeRegistry:
    def __init__(self, profile: TemplateProfile):
        ...

    def find_for_item(self, item) -> ControlPrototype:
        """
        根据 IR 控件查找最合适模板原型。
        匹配优先级：
        1. item.template_ref 精确匹配 prototype_id
        2. item.type + behavior 匹配
        3. item.type + indicator_mode 匹配
        4. item.name / tag 前缀匹配
        5. 默认同类型原型
        6. 找不到则抛出明确异常
        """
```

## 验收标准

新增测试：

- tests/template/test_prototype_extractor.py

- tests/template/test_event_pattern_extractor.py

- tests/template/test_binding_pattern_extractor.py

- tests/template/test_prototype_registry.py

测试必须覆盖：

1. 能从模板 XML 中识别按钮。

2. 能从模板 XML 中识别指示灯。

3. 能识别按钮事件变量。

4. 能识别指示灯动态绑定变量。

5. 能识别 momentary 按钮。

6. 能识别 toggle 按钮。

7. 能根据 template_ref 精确匹配原型。

8. 找不到原型时抛出可读错误。

---

# 阶段 2：升级 IR V2 语义字段

## 目标

让 AI 输出的 IR 能明确表达按钮行为、指示灯模式、模板引用和变量绑定，不再依赖后端猜测。

## 修改文件

- backend/domain/ir_v2.py

- backend/domain/enums.py

- backend/domain/validation.py

- backend/domain/legacy_adapter.py

- backend/hmi_ir.py

## 2.1 扩展枚举

文件：backend/domain/enums.py

新增或确认存在：

```python
class ButtonBehavior(str, Enum):
    MOMENTARY = "momentary"
    TOGGLE = "toggle"
    SET = "set"
    RESET = "reset"
    NAVIGATE = "navigate"
    NONE = "none"

class IndicatorMode(str, Enum):
    BOOL_COLOR = "bool_color"
    BOOL_BLINK = "bool_blink"
    MULTI_STATE = "multi_state"
    ALARM = "alarm"
    WARNING = "warning"
    STATUS = "status"

class TagDirection(str, Enum):
    READ = "read"
    WRITE = "write"
    READ_WRITE = "read_write"

class TagScope(str, Enum):
    HMI_INTERNAL = "hmi_internal"
    PLC_EXTERNAL = "plc_external"
    DERIVED = "derived"
```

## 2.2 扩展 ScreenItemSpec

文件：backend/domain/ir_v2.py

确保 ScreenItemSpec 支持：

```python
template_ref: str | None = None
prototype_role: str | None = None
behavior: ButtonBehavior | None = None
indicator_mode: IndicatorMode | None = None
binding: BindingSpec | None = None
events: list[EventSpec] = []
metadata: dict = {}
```

## 2.3 扩展 BindingSpec

确保 BindingSpec 支持：

```python
tag: str
direction: TagDirection = TagDirection.READ_WRITE
connection: str | None = None
plc_address: str | None = None
binding_kind: BindingKind | None = None
```

## 2.4 扩展 TagSpec

确保 TagSpec 支持：

```python
name: str
data_type: str
direction: TagDirection = TagDirection.READ_WRITE
scope: TagScope = TagScope.HMI_INTERNAL
connection: str | None = None
address: str | None = None
comment: str | None = None
metadata: dict = {}
```

## 2.5 强化 validation.py

新增校验规则：

```python
def validate_template_binding_requirements(spec: HmiProjectSpec) -> list[Diagnostic]:
    """
    校验按钮和指示灯是否满足模板绑定要求。
    """
```

必须检查：

1. 每个 button 必须有 binding.tag，除非 behavior=navigate。

2. 每个 indicator 必须有 binding.tag。

3. binding.tag 必须存在于 tags。

4. button tag 类型建议为 Bool。

5. momentary/toggle/set/reset 按钮 tag 必须可写。

6. indicator tag 必须可读。

7. template_ref 如果存在，必须是字符串。

8. 不允许控件引用不存在的 tag。

9. 不允许事件引用不存在的 tag。

10. 外部 PLC 变量如果没有 address，可以允许，但必须标记为 symbolic_placeholder 或 metadata.pending_mapping=true。

## 2.6 更新 legacy_adapter.py

旧 IR 转 HmiProjectSpec 时：

1. button 自动补 behavior：
   
   - 如果原 IR 有 momentary，则 momentary
   
   - 如果原 IR 有 toggle，则 toggle
   
   - 否则默认 momentary

2. indicator 自动补 indicator_mode：
   
   - 默认 bool_color

3. 根据控件类型自动补 template_ref：
   
   - button + momentary → BTN_MOMENTARY_TEMPLATE
   
   - button + toggle → BTN_TOGGLE_TEMPLATE
   
   - indicator → LMP_STATUS_TEMPLATE

4. 将旧字段 tag / variable / binding_tag 统一映射到 binding.tag。

## 验收标准

新增测试：

- tests/domain/test_ir_v2_template_fields.py

- tests/domain/test_ir_v2_validation_bindings.py

- tests/domain/test_legacy_adapter_template_fields.py

测试必须覆盖：

1. button 无 binding.tag 时校验失败。

2. indicator 无 binding.tag 时校验失败。

3. binding.tag 不存在时校验失败。

4. momentary button 自动补 template_ref。

5. legacy IR 能转换为含 template_ref、behavior、binding 的 IR V2。

---

# 阶段 3：升级 Prompt，让 AI 输出稳定语义 IR

## 目标

修改 LLM 提示词，让 AI 输出按钮行为、指示灯模式、变量、模板引用，禁止 AI 直接生成底层 XML 事件。

## 修改文件

- backend/prompts.py

- backend/review_prompts.py，如需要

- docs/ai_ir_contract.md

## 3.1 新增 AI 输出契约文档

新增文件：

docs/ai_ir_contract.md

内容包含：

1. AI 只能输出 HMI IR / HmiProjectSpec JSON。

2. AI 不能输出 TIA XML。

3. AI 不能臆造 VBS / JS 事件结构。

4. 按钮必须包含：
   
   - type = button
   
   - behavior
   
   - binding.tag
   
   - template_ref 或 prototype_role

5. 指示灯必须包含：
   
   - type = indicator
   
   - indicator_mode
   
   - binding.tag
   
   - states，如适用
   
   - template_ref 或 prototype_role

6. 所有 binding.tag 必须出现在 tags 列表。

7. 未提供 PLC 地址时 address 必须为 null，不得编造地址。

8. 变量命名规则：
   
   - BTN_：按钮写入变量
   
   - STS_：状态变量
   
   - LMP_：灯变量
   
   - IO_：输入输出域变量
   
   - MEM_：HMI 内部变量

## 3.2 修改 prompts.py

在系统提示词中加入硬约束：

```text
你不能直接生成 TIA XML。
你不能生成底层 EventHandler XML。
你不能生成底层 Dynamization XML。
你只能输出 HMI IR JSON。

按钮必须输出：
- behavior: momentary | toggle | set | reset | navigate
- binding.tag
- template_ref

指示灯必须输出：
- indicator_mode: bool_color | bool_blink | multi_state | alarm | warning | status
- binding.tag
- template_ref

所有控件引用的变量必须出现在 tags 列表中。
如果用户没有提供 PLC 地址，address 必须为 null，metadata.pending_mapping=true。
```

## 3.3 增加 Few-shot 示例

增加电机控制画面示例：

用户输入：

```text
生成一个电机控制画面，有启动、停止按钮，运行和故障指示灯。
```

AI 输出应该类似：

```json
{
  "schema_version": "2.0",
  "project": {
    "name": "MotorControl"
  },
  "tags": [
    {
      "name": "BTN_Motor_Start",
      "data_type": "Bool",
      "direction": "write",
      "scope": "hmi_internal",
      "address": null,
      "metadata": {
        "pending_mapping": true
      }
    },
    {
      "name": "BTN_Motor_Stop",
      "data_type": "Bool",
      "direction": "write",
      "scope": "hmi_internal",
      "address": null,
      "metadata": {
        "pending_mapping": true
      }
    },
    {
      "name": "STS_Motor_Running",
      "data_type": "Bool",
      "direction": "read",
      "scope": "plc_external",
      "address": null,
      "metadata": {
        "pending_mapping": true
      }
    },
    {
      "name": "STS_Motor_Fault",
      "data_type": "Bool",
      "direction": "read",
      "scope": "plc_external",
      "address": null,
      "metadata": {
        "pending_mapping": true
      }
    }
  ],
  "screens": [
    {
      "name": "Motor_Control",
      "title": "电机控制画面",
      "items": [
        {
          "id": "btn_start",
          "name": "BTN_Start",
          "type": "button",
          "text": "启动",
          "behavior": "momentary",
          "template_ref": "BTN_MOMENTARY_TEMPLATE",
          "binding": {
            "tag": "BTN_Motor_Start",
            "direction": "write"
          },
          "geometry": {
            "x": 80,
            "y": 120,
            "w": 120,
            "h": 50
          }
        },
        {
          "id": "lmp_running",
          "name": "LMP_Running",
          "type": "indicator",
          "text": "运行",
          "indicator_mode": "bool_color",
          "template_ref": "LMP_STATUS_TEMPLATE",
          "binding": {
            "tag": "STS_Motor_Running",
            "direction": "read"
          },
          "geometry": {
            "x": 260,
            "y": 120,
            "w": 60,
            "h": 60
          }
        }
      ]
    }
  ]
}
```

## 验收标准

1. prompts.py 中明确禁止 AI 生成 XML。

2. prompts.py 中明确要求 button/indicator 输出 template_ref 和 binding.tag。

3. 新增 docs/ai_ir_contract.md。

4. 单元测试或快照测试确认 prompt 包含关键约束词：
   
   - template_ref
   
   - behavior
   
   - indicator_mode
   
   - binding.tag
   
   - 不得编造 PLC 地址
   
   - 不能生成 TIA XML

---

# 阶段 4：升级 VariableEngine

## 目标

保证所有按钮、指示灯、IO 域都有明确变量，并且变量表可以先于画面导入博途。

## 修改文件

- backend/variable_engine.py

- backend/backends/classic/tag_xml_builder.py

- backend/backends/unified/tag_builder.py

- backend/openness_manager.py

- backend/services/deployment_service.py

## 4.1 统一变量生成规则

在 VariableEngine 中固化规则：

| 控件类型              | 默认变量前缀      | 类型                | 方向         |
| ----------------- | ----------- | ----------------- | ---------- |
| button momentary  | BTN_        | Bool              | write      |
| button toggle     | MEM_ 或 BTN_ | Bool              | read_write |
| indicator status  | STS_ 或 LMP_ | Bool              | read       |
| indicator alarm   | STS_ 或 LMP_ | Bool              | read       |
| io_field          | IO_         | Real / Int / DInt | read_write |
| symbolic_io_field | SIO_        | Int / Word        | read_write |

## 4.2 新增 enrich_project_spec

实现或增强：

```python
class VariableEngine:
    def enrich_project_spec(self, spec: HmiProjectSpec) -> HmiProjectSpec:
        """
        1. 补全缺失 tag
        2. 规范变量名
        3. 补全 data_type
        4. 补全 direction
        5. 补全 scope
        6. 补全 address=null + pending_mapping
        7. 确保所有控件 binding.tag 存在
        """
```

## 4.3 增加变量冲突处理

规则：

1. 同名同类型变量允许复用。

2. 同名不同类型变量必须报错。

3. 同名不同地址必须报错。

4. 变量名非法字符统一替换为下划线。

5. 变量名必须符合 TIA 命名要求。

## 4.4 增加 PLC 映射入口

支持用户提供：

```json
{
  "plc_tag_mapping": {
    "Motor_Start": "DB10.DBX0.0",
    "Motor_Stop": "DB10.DBX0.1",
    "Motor_Running": "DB10.DBX2.0",
    "Motor_Fault": "DB10.DBX2.1"
  }
}
```

VariableEngine 需要做语义匹配：

1. 精确匹配变量名。

2. 去掉 BTN_/STS_/LMP_ 前缀后匹配。

3. 按 item id 匹配。

4. 按中文文本匹配，如“启动”“停止”“运行”“故障”。

不要强行猜测地址。匹配不到就保留 address=null。

## 验收标准

新增测试：

- tests/variable/test_variable_engine_project_spec.py

- tests/variable/test_variable_name_normalization.py

- tests/variable/test_plc_tag_mapping.py

测试必须覆盖：

1. button 自动生成 Bool 写变量。

2. indicator 自动生成 Bool 读变量。

3. binding.tag 缺失时自动补。

4. 变量名非法字符被修复。

5. plc_tag_mapping 能填充地址。

6. 未映射地址不被编造，而是 pending_mapping=true。

7. 同名不同类型报错。

---

# 阶段 5：实现模板克隆与变量/事件/动态替换

## 目标

增强 template_xml_generator.py，使它不只是改普通变量连接，还能完整替换按钮事件和指示灯动态绑定中的变量引用。

## 修改文件

- backend/template_xml_generator.py

- backend/template/xml_rewrite_rules.py

- backend/template/xml_utils.py

- backend/backends/classic/screen_xml_builder.py，如需要

- backend/backends/classic/dynamic_xml_builder.py，如需要

- backend/backends/classic/function_list_builder.py，如需要

## 5.1 新增 RewritePlan

文件：backend/template/xml_rewrite_rules.py

定义：

```python
@dataclass
class RewritePlan:
    item_id: str
    item_name: str
    prototype_id: str
    old_tags: list[str]
    new_tag: str | None
    new_text: str | None
    geometry: dict
    replacements: dict[str, str]
```

## 5.2 实现核心替换函数

```python
def replace_control_name(node, new_name: str) -> None:
    ...

def replace_control_text(node, new_text: str) -> None:
    ...

def replace_geometry(node, geometry: dict) -> None:
    ...

def replace_all_tag_references(node, old_tags: list[str], new_tag: str) -> None:
    """
    必须替换：
    - 属性中的变量名
    - 文本节点中的变量名
    - EventHandlers 中变量名
    - FunctionList 中变量名
    - Dynamizations 中变量名
    - Animations 中变量名
    - 脚本文本中的变量名
    """

def ensure_no_placeholder_tags(node, placeholder_tags: list[str]) -> None:
    """
    如果残留模板变量，抛出异常。
    """

def assign_unique_control_ids(node, id_registry) -> None:
    ...
```

## 5.3 改造 generate_from_template_xml

当前入口保持不变：

```python
generate_from_template_xml(ir, template_xml)
```

内部改成：

1. 将 ir 转换为 HmiProjectSpec。

2. 调用 analyze_template_screen(template_xml) 得到 TemplateProfile。

3. 构造 PrototypeRegistry。

4. 遍历每个 screen item。

5. 对 button / indicator：
   
   - find_for_item()
   
   - deepcopy prototype.xml_node
   
   - replace_control_name
   
   - replace_control_text
   
   - replace_geometry
   
   - replace_all_tag_references
   
   - assign_unique_control_ids
   
   - ensure_no_placeholder_tags

6. 对其他控件：
   
   - 继续使用现有旧逻辑。

7. 合并生成新的 screen XML。

8. 运行现有 XML 清洗与校验。

9. 返回 XML。

## 5.4 替换规则必须覆盖这些位置

必须覆盖：

```text
Name
ObjectName
Left
Top
Width
Height
Text
MultilingualText
TextItem
EventHandlers
Events
FunctionList
Dynamizations
Animations
ColorAnimation
FlashAnimation
ProcessValue
TagName
VariableName
Expression
ScriptCode
```

## 5.5 防止误替换

replace_all_tag_references 不能简单全局 replace。

要求：

1. 优先基于 XML 节点结构替换。

2. 对脚本文本可以做安全 replace，但必须只替换完整变量名。

3. 避免把 `BTN_A` 错替换到 `BTN_ABC` 中。

4. 使用边界匹配或 tokenizer。

5. 替换前后记录 diagnostics。

## 验收标准

新增测试：

- tests/template/test_template_rewrite_button.py

- tests/template/test_template_rewrite_indicator.py

- tests/template/test_template_rewrite_no_placeholder.py

- tests/template/test_template_rewrite_unique_ids.py

测试必须覆盖：

1. 克隆按钮后，按钮文本被替换。

2. 克隆按钮后，位置尺寸被替换。

3. 克隆按钮后，事件里的模板变量被替换为新变量。

4. 克隆指示灯后，动态绑定里的模板变量被替换。

5. 生成 XML 中无 Template_BTN_Tag。

6. 生成 XML 中无 Template_LMP_Tag。

7. 多个按钮生成时 ID 不重复。

8. 多个指示灯生成时 ID 不重复。

9. 不误替换相似变量名。

---

# 阶段 6：导入顺序与部署计划增强

## 目标

保证变量先导入，脚本其次，画面最后导入；导入失败时能够定位是哪一阶段失败。

## 修改文件

- backend/services/deployment_service.py

- backend/planners/deployment_planner.py

- backend/domain/deployment_plan.py

- backend/backends/classic/basic_backend.py

- backend/backends/classic/comfort_backend.py

- backend/openness/classic_executor.py

- backend/openness_manager.py

## 6.1 固定部署阶段

部署阶段建议：

```text
P00_PRECHECK
P10_CONNECTIONS
P20_TAGS
P30_TEXT_LISTS
P40_SCRIPTS
P50_SCREENS
P60_COMPILE
P70_VERIFY
P80_REPORT
P90_ROLLBACK
```

## 6.2 build_plan 必须输出明确步骤

每个步骤包含：

```python
DeploymentStep(
    phase="P20_TAGS",
    name="Import HMI tags",
    payload={...},
    depends_on=["P10_CONNECTIONS"]
)
```

## 6.3 Classic 执行顺序

classic_executor.py 必须按顺序执行：

1. connections

2. tags

3. text_lists

4. scripts

5. screens

6. compile

7. verify

禁止 screen 先于 tags 导入。

## 6.4 sync_tags 增强

openness_manager.sync_tags() 必须支持：

1. 创建不存在的 HMI Tag Table。

2. 创建或更新变量。

3. 保留已有变量时可选择 override / skip。

4. 返回详细结果：
   
   - created
   
   - updated
   
   - skipped
   
   - failed
   
   - diagnostics

## 验收标准

新增测试：

- tests/deployment/test_deployment_plan_order.py

- tests/deployment/test_classic_import_order.py

- tests/deployment/test_sync_tags_payload.py

测试必须覆盖：

1. P20_TAGS 一定早于 P50_SCREENS。

2. P60_COMPILE 一定晚于 P50_SCREENS。

3. P70_VERIFY 一定晚于 P60_COMPILE。

4. 变量导入失败时不继续导入画面。

5. screen XML 生成失败时不调用 Openness 导入。

---

# 阶段 7：导入前验证增强

## 目标

在调用 TIA Portal Openness 之前，阻断所有明显错误，避免污染博途项目。

## 修改文件

- backend/xml_validator.py

- backend/domain/validation.py

- backend/services/verification_service.py

- backend/template_xml_generator.py

## 7.1 新增 TemplateBindingValidator

可以新增文件：

backend/template/template_binding_validator.py

实现：

```python
def validate_generated_screen_xml(
    xml: str,
    expected_tags: list[str],
    forbidden_placeholder_tags: list[str],
    expected_items: list[str],
) -> list[Diagnostic]:
    """
    导入前检查生成 XML。
    """
```

必须检查：

1. XML 可解析。

2. 控件名唯一。

3. SimaticML ID 唯一。

4. expected_tags 都出现在 XML 中，或至少在对应控件中出现。

5. forbidden_placeholder_tags 不得出现。

6. 所有按钮事件目标变量存在。

7. 所有指示灯动态绑定变量存在。

8. 不存在空 TagName。

9. 不存在空 EventHandler。

10. 不存在空 Dynamization 引用。

## 7.2 接入 template_xml_generator

generate_from_template_xml 返回前必须调用：

```python
validate_generated_screen_xml(...)
```

如果有 error 级别 diagnostic，直接抛异常，不允许导入。

## 7.3 接入 ImportEngine 前

import_engine.py 调用原有 XmlValidator 前后，增加模板绑定验证结果汇总。

## 验收标准

新增测试：

- tests/template/test_template_binding_validator.py

- tests/deployment/test_pre_import_blocking.py

测试必须覆盖：

1. 有模板变量残留时阻断。

2. 有空 TagName 时阻断。

3. 控件 ID 重复时阻断。

4. 控件名重复时阻断。

5. 正常 XML 可以通过。

---

# 阶段 8：导入后验证增强

## 目标

导入博途后，验证变量、画面、控件、事件绑定是否成功。

## 修改文件

- backend/services/verification_service.py

- backend/openness/object_query_service.py

- backend/openness_manager.py

- backend/domain/deployment_result.py

## 8.1 VerificationService 增强

实现：

```python
class VerificationService:
    def verify_tags_exist(self, expected_tags: list[str]) -> VerificationResult:
        ...

    def verify_screen_exists(self, screen_name: str) -> VerificationResult:
        ...

    def verify_screen_items_exist(self, screen_name: str, expected_items: list[str]) -> VerificationResult:
        ...

    def verify_no_template_placeholder(self, screen_name: str, forbidden_tags: list[str]) -> VerificationResult:
        ...

    def verify_compile_success(self, compile_result) -> VerificationResult:
        ...

    def verify_deployment(self, plan, expected_spec) -> DeploymentResult:
        ...
```

## 8.2 object_query_service 增强

需要提供：

1. 查询 HMI tags。

2. 查询 screen。

3. 查询 screen items。

4. 查询 screen item properties。

5. 如 Openness API 支持，查询事件和动态绑定。

6. 如不支持，至少基于导入前 XML 和导入后对象存在性做验证。

## 8.3 部署结果结构

DeploymentResult 应该输出：

```json
{
  "status": "DEPLOYED",
  "tags": {
    "expected": 6,
    "created": 6,
    "missing": []
  },
  "screens": {
    "expected": 1,
    "created": 1,
    "missing": []
  },
  "items": {
    "expected": 8,
    "found": 8,
    "missing": []
  },
  "compile": {
    "success": true,
    "diagnostics": []
  },
  "warnings": []
}
```

## 验收标准

新增测试：

- tests/deployment/test_verification_service.py

测试必须覆盖：

1. expected tag 缺失时报错。

2. expected screen 缺失时报错。

3. expected screen item 缺失时报错。

4. 编译失败时 deployment status=FAILED。

5. 验证通过时 deployment status=DEPLOYED。

---

# 阶段 9：Pipeline 接入

## 目标

把新 IR、变量引擎、模板原型、验证服务接入现有 SSE 流水线。

## 修改文件

- backend/pipeline_orchestrator.py

- backend/app.py

- backend/services/deployment_service.py

- backend/config_manager.py

## 9.1 pipeline_orchestrator 增加阶段事件

SSE 事件建议：

```text
llm_start
llm_content
ir_extracted
ir_validated
variables_generated
template_analyzed
prototype_matched
preview_rendered
review_completed
xml_generated
pre_import_validated
tags_imported
screen_imported
compile_completed
verify_completed
deployment_completed
deployment_failed
```

## 9.2 生成阶段调用顺序

pipeline_orchestrator 应按下面顺序：

1. LLM 生成 IR。

2. extract_json。

3. legacy_adapter 或 HmiProjectSpec parse。

4. validate_ir_v2。

5. VariableEngine.enrich_project_spec。

6. validate_template_binding_requirements。

7. render preview。

8. MiMo review，如启用。

9. 如果用户选择导入：
   
   - analyze_template_screen
   
   - generate_from_template_xml
   
   - validate_generated_screen_xml
   
   - deployment_service.deploy

10. 返回完整 DeploymentResult。

## 9.3 配置项

config_manager.py 增加：

```yaml
template:
  enabled: true
  require_prototype_for_button: true
  require_prototype_for_indicator: true
  fail_on_placeholder_remaining: true
  default_button_template: BTN_MOMENTARY_TEMPLATE
  default_indicator_template: LMP_STATUS_TEMPLATE

deployment:
  import_tags_before_screens: true
  compile_after_import: true
  verify_after_compile: true
```

## 验收标准

新增测试：

- tests/pipeline/test_pipeline_template_flow.py

测试必须覆盖：

1. pipeline 能输出 template_analyzed 事件。

2. pipeline 能输出 prototype_matched 事件。

3. pipeline 能输出 variables_generated 事件。

4. template 缺失时返回明确错误。

5. button 找不到 prototype 时返回明确错误。

6. indicator 找不到 prototype 时返回明确错误。

---

# 阶段 10：API 与前端输出数据结构

## 目标

让前端可以展示 AI 理解结果、变量表、控件绑定、导入结果。

## 修改文件

- backend/app.py

- backend/pipeline_orchestrator.py

- 前端相关文件，如 frontend/src/api/*、frontend/src/views/*、frontend/src/components/*

## 10.1 后端返回 summary

生成结果应包含：

```json
{
  "understanding": {
    "screen_name": "Motor_Control",
    "screen_title": "电机控制画面",
    "items_count": 8,
    "button_count": 3,
    "indicator_count": 2
  },
  "tags": [
    {
      "name": "BTN_Motor_Start",
      "data_type": "Bool",
      "direction": "write",
      "address": null,
      "pending_mapping": true,
      "comment": "电机启动按钮"
    }
  ],
  "bindings": [
    {
      "item_name": "BTN_Start",
      "item_type": "button",
      "template_ref": "BTN_MOMENTARY_TEMPLATE",
      "tag": "BTN_Motor_Start",
      "event_summary": "Press=1, Release=0"
    },
    {
      "item_name": "LMP_Running",
      "item_type": "indicator",
      "template_ref": "LMP_STATUS_TEMPLATE",
      "tag": "STS_Motor_Running",
      "event_summary": "Bool color animation"
    }
  ],
  "deployment": {
    "tags_imported": true,
    "screen_imported": true,
    "compile_success": true,
    "verify_success": true
  }
}
```

## 10.2 前端显示四块

前端建议展示：

1. AI 理解结果。

2. 变量表。

3. 控件绑定表。

4. 导入/编译/验证结果。

## 验收标准

1. 用户能看到每个按钮绑定了哪个变量。

2. 用户能看到每个指示灯绑定了哪个变量。

3. 用户能看到每个控件使用了哪个模板原型。

4. 导入失败时能看到失败阶段和原因。

---

# 阶段 11：端到端测试

## 目标

用一个最小电机控制画面验证完整闭环。

## 新增测试 fixture

tests/fixtures/ir_motor_control_full.json

内容包括：

1. 一个画面 Motor_Control。

2. 两个按钮：
   
   - 启动 momentary
   
   - 停止 momentary

3. 两个指示灯：
   
   - 运行 bool_color
   
   - 故障 alarm 或 bool_blink

4. 四个变量：
   
   - BTN_Motor_Start
   
   - BTN_Motor_Stop
   
   - STS_Motor_Running
   
   - STS_Motor_Fault

## 新增测试

- tests/e2e/test_motor_control_template_generation.py

测试内容：

1. 加载模板 XML。

2. 加载 IR。

3. VariableEngine enrich。

4. analyze_template_screen。

5. generate_from_template_xml。

6. validate_generated_screen_xml。

7. 检查生成 XML：
   
   - 包含 BTN_Motor_Start
   
   - 包含 BTN_Motor_Stop
   
   - 包含 STS_Motor_Running
   
   - 包含 STS_Motor_Fault
   
   - 不包含 Template_BTN_Tag
   
   - 不包含 Template_LMP_Tag
   
   - 包含启动、停止、运行、故障文本
   
   - 控件名唯一
   
   - ID 唯一

不要在普通单元测试中真实连接 TIA Portal。真实 Openness 测试应单独标记 integration。

## 验收标准

1. 不连接 TIA Portal 的情况下，完整 XML 生成测试通过。

2. 所有模板变量被替换。

3. 所有控件 ID 唯一。

4. 所有 button / indicator 都能找到模板原型。

5. 可选 integration 测试在有 TIA 环境时通过导入、编译、验证。

---

# 阶段 12：错误处理与诊断

## 目标

任何失败都要给出清晰原因，而不是只返回“导入失败”。

## 修改文件

- backend/domain/diagnostics.py

- backend/openness/exception_mapper.py

- backend/services/deployment_service.py

- backend/template/prototype_registry.py

- backend/template/template_binding_validator.py

## 12.1 新增诊断码

建议新增：

```python
TEMPLATE_XML_PARSE_FAILED
TEMPLATE_NO_BUTTON_PROTOTYPE
TEMPLATE_NO_INDICATOR_PROTOTYPE
TEMPLATE_PROTOTYPE_TAG_NOT_FOUND
TEMPLATE_PLACEHOLDER_REMAINING
TEMPLATE_EVENT_TAG_REPLACE_FAILED
TEMPLATE_DYNAMIC_TAG_REPLACE_FAILED
IR_BUTTON_BINDING_MISSING
IR_INDICATOR_BINDING_MISSING
IR_TAG_REFERENCE_MISSING
TAG_IMPORT_FAILED
SCREEN_XML_PRECHECK_FAILED
SCREEN_IMPORT_FAILED
COMPILE_FAILED
VERIFY_TAG_MISSING
VERIFY_SCREEN_MISSING
VERIFY_SCREEN_ITEM_MISSING
```

## 12.2 错误信息要求

错误信息必须包含：

1. 阶段。

2. 控件名。

3. 变量名。

4. 模板原型 ID。

5. 建议修复方式。

示例：

```text
阶段：模板原型匹配
错误：按钮 BTN_Start 需要 behavior=momentary，但模板中没有找到 BTN_MOMENTARY_TEMPLATE。
建议：请在模板画面中加入一个已配置 Press/Release 事件的点动按钮，或修改 item.template_ref。
```

## 验收标准

1. 缺少按钮模板时报错清楚。

2. 缺少指示灯模板时报错清楚。

3. 模板变量残留时报错清楚。

4. 变量不存在时报错清楚。

5. 前端可以显示 diagnostics。

---

# 阶段 13：兼容策略与兜底路线

## 目标

在模板不可用或设备能力有限时，系统有明确兜底，不静默生成错误画面。

## 修改文件

- backend/capabilities/capability_service.py

- backend/capabilities/static_matrix.py

- backend/template_xml_generator.py

- backend/simaticml_generator.py

- backend/services/deployment_service.py

## 13.1 Classic HMI 规则

如果目标为 Basic / Comfort：

1. 优先使用模板 XML。

2. 如果没有模板：
   
   - 允许配置 fallback_to_simaticml=true 时走 simaticml_generator。
   
   - 否则阻断，并提示需要模板。

3. Basic 面板如果不支持脚本，不能生成 VBS 脚本。

4. 如果模板事件依赖脚本但目标面板不支持，必须阻断或降级为 FunctionList。

## 13.2 Unified HMI 规则

如果目标为 Unified：

1. 优先走 unified_executor 直接对象模型。

2. 仍然使用相同语义 IR。

3. event_builder / binding_builder 根据语义生成 Unified API 绑定。

4. 不要求使用 Classic XML 模板。

5. 如果用户指定使用模板，也可以复用模板语义分析，但不直接导入 Classic XML。

## 13.3 兜底配置

```yaml
template:
  fallback_to_simaticml: false
  allow_missing_indicator_template: false
  allow_missing_button_template: false
```

默认应该严格，不要静默兜底。

## 验收标准

1. Classic 无模板且 fallback=false 时阻断。

2. Classic 无模板且 fallback=true 时走 simaticml_generator。

3. Basic 不支持脚本时不生成 VBS。

4. Unified 不依赖 Classic XML 模板也能部署。

---

# 阶段 14：最终验收清单

## 功能验收

必须能完成：

1. 用户输入自然语言：
   
   - “生成一个电机控制画面，有启动、停止按钮，运行、故障指示灯。”

2. LLM 输出 IR。

3. VariableEngine 生成变量：
   
   - BTN_Motor_Start
   
   - BTN_Motor_Stop
   
   - STS_Motor_Running
   
   - STS_Motor_Fault

4. 系统分析模板 XML。

5. 系统找到按钮模板。

6. 系统找到指示灯模板。

7. 系统克隆按钮。

8. 系统克隆指示灯。

9. 系统替换事件变量。

10. 系统替换动态绑定变量。

11. 系统生成 screen XML。

12. 系统导入 tags。

13. 系统导入 screen。

14. 系统 compile。

15. 系统 verify。

16. 前端展示变量和控件绑定结果。

## XML 验收

生成 XML 必须满足：

1. 无模板变量残留。

2. 无重复控件名。

3. 无重复 SimaticML ID。

4. 按钮事件变量已替换。

5. 指示灯动态变量已替换。

6. XML 可被 XmlValidator 通过。

7. 可被 ImportEngine 导入。

## 代码质量验收

1. 所有新增模块有类型标注。

2. 所有核心函数有 docstring。

3. 所有异常使用 Diagnostic 或明确异常类。

4. 不使用大范围字符串拼接生成关键事件 XML。

5. 不破坏旧接口。

6. 单元测试覆盖模板提取、变量生成、XML 改写、导入前验证。

7. TIA Openness 真实导入测试单独标记 integration，不影响普通 CI。

---

# 推荐提交顺序

请按以下顺序分批提交：

1. feat(template): add template prototype model and xml utils

2. feat(template): extract button and indicator prototypes

3. feat(domain): extend IR v2 for template binding

4. feat(prompts): enforce semantic IR contract

5. feat(variable): enrich project spec tags and bindings

6. feat(template): clone prototypes and rewrite tag references

7. feat(validation): add template binding pre-import validator

8. feat(deployment): enforce tags-before-screens deployment order

9. feat(verification): verify deployed tags screens and items

10. feat(pipeline): integrate template prototype flow into SSE pipeline

11. feat(api): return generation summary, tags, bindings, deployment result

12. test(e2e): add motor control template generation test

13. docs: add auto HMI generation implementation notes

---

# Claude Code 执行约束

请严格遵守：

1. 不要删除现有功能。

2. 不要绕过 ImportEngine。

3. 不要跳过 XmlValidator。

4. 不要让 AI 直接生成 TIA XML 事件。

5. 不要在没有 PLC 地址时编造地址。

6. 不要静默忽略模板变量替换失败。

7. 不要在生成 XML 中残留模板变量。

8. 不要把 screen 导入放在 tag 导入之前。

9. 不要让普通单元测试依赖真实 TIA Portal 环境。

10. 所有失败必须返回可读 diagnostics。

最终目标是让系统从“生成 HMI 画面”升级为“生成可导入、变量已连接、事件已配置、编译可验证的自动化 HMI 项目片段”。

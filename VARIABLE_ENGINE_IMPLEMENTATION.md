# Siemens HMI 变量系统工程级升级 — 完整实施文档

> **实施日期:** 2026-06-18  
> **基于方案:** `Siemens_HMI_变量系统_工程级完整方案.md`  
> **测试结果:** 47/47 全部通过 (0.98s)

---

## 目录

1. [概述](#1-概述)
2. [新增模块: variable_engine.py](#2-新增模块-variable_enginepy)
3. [修改: hmi_ir.py](#3-修改-hmi_irpy)
4. [修改: prompts.py](#4-修改-promptspy)
5. [修改: simaticml_generator.py](#5-修改-simaticml_generatorpy)
6. [修改: openness_manager.py](#6-修改-openness_managerpy)
7. [修改: pipeline_orchestrator.py](#7-修改-pipeline_orchestratorpy)
8. [修改: app.py](#8-修改-apppy)
9. [数据流对比](#9-数据流对比)
10. [验证结果](#10-验证结果)

---

## 1. 概述

### 升级目标

将 Siemens HMI 画面助手从"画面生成器"升级为**工业级 HMI 自动工程系统**，新增三大核心能力：

| 能力   | 升级前                 | 升级后                  |
| ---- | ------------------- | -------------------- |
| 变量规划 | ❌ 无自动变量生成           | ✅ 按前缀规则自动生成 HMI Tags |
| 控件绑定 | ❌ 需手动填写 process_tag | ✅ 自动推断并绑定            |
| 工程同步 | ❌ 变量需手动在 TIA 创建     | ✅ 导入后自动写入 HMI 变量表    |

### 影响的模块

```
新增: backend/variable_engine.py    (410行, 核心引擎)
修改: backend/hmi_ir.py             (变量默认值 + tag_mode + blink_tag)
修改: backend/prompts.py            (TAG_CONVENTIONS 规范)
修改: backend/simaticml_generator.py (Button行为 + Indicator闪烁)
修改: backend/openness_manager.py   (sync_tags 方法 + 自动同步)
修改: backend/pipeline_orchestrator.py (集成 VariableEngine)
修改: app.py                         (4处集成 + 新增 API)
```

---

## 2. 新增模块: variable_engine.py

**文件路径:** `backend/variable_engine.py` (410行)

### 2.1 模块架构

```
VariableEngine
├── 命名规则常量
│   ├── BTN_PREFIX_MOMENTARY = "BTN_"    # 瞬时按钮
│   ├── BTN_PREFIX_TOGGLE    = "MEM_"    # 自保持按钮
│   ├── INDICATOR_PREFIX_STATUS = "STS_" # 状态指示灯
│   ├── INDICATOR_PREFIX_ALARM  = "LMP_" # 报警指示灯
│   ├── IOFIELD_PREFIX      = "IO_"      # 数值IO域
│   └── SYMBOLIC_IOFIELD_PREFIX = "SIO_" # 符号IO域
│
├── VBS 脚本模板
│   ├── VBS_TOGGLE_TEMPLATE           # NOT 翻转
│   ├── VBS_MOMENTARY_PRESS_TEMPLATE  # = 1 置位
│   └── VBS_MOMENTARY_RELEASE_TEMPLATE # = 0 复位
│
├── 关键词检测
│   ├── TOGGLE_KEYWORDS   # 切换/自保持/手动自动/正转反转...
│   └── ALARM_KEYWORDS    # 故障/报警/急停/过载/联锁...
│
├── 公共方法
│   ├── generate(ir)        # 主入口: 原地修改 IR + 返回引用
│   ├── get_tag_table(ir)   # 静态: 提取完整 Tag Table
│   ├── get_tag_names(ir)   # 静态: 提取所有变量名
│   └── get_binding_summary(ir)  # 静态: 变量绑定摘要
│
└── 便捷函数
    └── auto_bind_variables(ir, plc_prefix)  # 一行调用
```

### 2.2 核心逻辑详解

#### generate(ir) — 主入口

**处理流程:**

```
输入 IR
│
├─ 遍历 objects[]
│  │
│  ├─ type == "Button"
│  │   ├─ _detect_toggle() → tag_mode = "momentary" | "toggle"
│  │   ├─ _make_tag_name() → process_tag = BTN_xxx | MEM_xxx
│  │   ├─ 生成 tags 条目 (data_type: Bool)
│  │   ├─ toggle → _add_toggle_scripts()   (NOT 翻转 VBS)
│  │   └─ momentary → _add_momentary_scripts() (Press=1, Release=0 VBS)
│  │
│  ├─ type == "Indicator"
│  │   ├─ _detect_alarm() → alarm-like?
│  │   ├─ _make_tag_name() → process_tag = STS_xxx | LMP_xxx
│  │   ├─ 生成 tags 条目 (data_type: Bool)
│  │   ├─ alarm → blink_tag = process_tag, color_on = "#E25563"
│  │   └─ status → blink_tag = None, color_on = "#27D17F"
│  │
│  ├─ type == "IOField"
│  │   ├─ _make_tag_name() → process_tag = IO_xxx
│  │   ├─ _infer_iofield_datatype() → Real | Int | String | Word
│  │   └─ 生成 tags 条目 (含单位注释)
│  │
│  ├─ type == "SymbolicIOField"
│  │   ├─ _make_tag_name() → process_tag = SIO_xxx
│  │   └─ 生成 tags 条目 (data_type: Int)
│  │
│  └─ type == "Text" → 跳过 (无需变量)
│
├─ 合并到 ir["tags"] (去重)
├─ 合并到 ir["scripts"] (去重)
└─ 标记 _variable_engine_applied = True
```

#### _detect_toggle(obj, oid) — 自保持检测

**判断优先级（任一满足即返回 True）:**

```
1. obj["self_holding"] == True  或  obj["tag_mode"] == "toggle"
2. obj["text"] / obj["label"] / oid 包含 TOGGLE_KEYWORDS
   关键词: 切换/自保持/自锁/手动自动/手自动/本地远程/正转反转/启动停止/开关
3. oid 以 "MEM_" 开头
```

#### _detect_alarm(obj, oid) — 报警检测

**判断优先级（任一满足即返回 True）:**

```
1. obj["blink"] == True
2. obj["color_on"] 为红色系 (#E25563 / #FF0000 / ...)
3. obj["label"] / oid 包含 ALARM_KEYWORDS
   关键词: 故障/报警/急停/过载/超温/过流/过压/欠压/断线/跳闸/异常/联锁
4. oid 以 "LMP_" 开头
```

#### _infer_iofield_datatype(obj) — 数据类型推断

```
display_format == "String"  → data_type = "String"
display_format == "Hex"     → data_type = "Word"
display_format == "Binary"  → data_type = "Word"
display_format == "Decimal" → decimal_digits > 0 → "Real"
                            → decimal_digits = 0 → "Int"
未指定                      → "Real" (默认)
```

#### VBS 脚本生成

**toggle 按钮:**

```vb
' 切换按钮「手动/自动」— 翻转变量 MEM_Mode_Switch
SmartTags("MEM_Mode_Switch") = Not SmartTags("MEM_Mode_Switch")
```

- 脚本名: `Sub_{oid}_Toggle`
- 事件: `click_script`
- press_script / release_script → 清空

**momentary 按钮:**

```vb
' 按钮「启动」— 按下置位 BTN_Start
SmartTags("BTN_Start") = 1
```

```vb
' 按钮「启动」— 释放复位 BTN_Start
SmartTags("BTN_Start") = 0
```

- Press 脚本名: `Sub_{oid}_Press`
- Release 脚本名: `Sub_{oid}_Release`
- 事件: `press_script` / `release_script`

#### get_binding_summary(ir) — 绑定摘要

```python
返回:
{
    "total_tags": 6,
    "by_type": {"Bool": 4, "Real": 1, "Int": 1},
    "by_prefix": {
        "BTN_": ["BTN_Start", "BTN_Stop"],
        "MEM_": ["MEM_Mode_Switch"],
        "LMP_": ["LMP_Fault", "LMP_Run"],
        "IO_":  ["IO_Speed"]
    },
    "objects_bound": 6,
    "objects_unbound": []
}
```

---

## 3. 修改: hmi_ir.py

**文件路径:** `backend/hmi_ir.py`

### 3.1 新增常量 (行 18-28)

```python
# 变更前: 无 tag_mode 相关常量
# 变更后:
VALID_TAG_MODES = {"momentary", "toggle"}

TAG_PREFIX_MAP = {
    "Button":    "BTN_",
    "Indicator": "STS_",
    "IOField":   "IO_",
    "SymbolicIOField": "SIO_",
}
```

### 3.2 IOField / SymbolicIOField — process_tag 自动生成 (行 356-376)

**变更前:**

```python
tag = _req(o, "process_tag", where)   # 必填，缺失抛异常
if tag not in tag_names:
    warnings.append(...)
```

**变更后:**

```python
prefix = TAG_PREFIX_MAP.get(otype, "IO_")
tag = o.get("process_tag") or f"{prefix}{oid}"  # 自动默认
if tag not in tag_names:
    # 自动补全到 tags 列表
    ir.setdefault("tags", []).append({
        "name": tag, "data_type": dtype,
        "address": o.get("address", ""),
        "comment": f"自动生成 — {o.get('label', oid)}",
    })
    tag_names.add(tag)
```

**影响:** IOField/SymbolicIOField 的 `process_tag` 从必填变为可选，缺失时自动按前缀规则生成。

同时 SymbolicIOField 的 `text_list` 也从必填改为可选（仅警告）。

### 3.3 Button — 新增 process_tag + tag_mode (行 378-387)

**变更前:**

```python
elif otype == "Button":
    base["width"] = ...
    base["text"] = ...
    # 无 process_tag
    for ev in ("press_script", ...):
        ...
```

**变更后:**

```python
elif otype == "Button":
    base["width"] = ...
    base["text"] = ...
    # 新增: tag_mode 归一化
    tag_mode = o.get("tag_mode") or "momentary"
    if tag_mode not in VALID_TAG_MODES:
        tag_mode = "momentary"
    base["tag_mode"] = tag_mode
    # 新增: process_tag 自动生成
    btn_prefix = "MEM_" if tag_mode == "toggle" else "BTN_"
    btn_tag = o.get("process_tag") or f"{btn_prefix}{oid}"
    if btn_tag not in tag_names:
        ir.setdefault("tags", []).append({...})  # 自动补全
    base["process_tag"] = btn_tag
    # 保留原有事件引用逻辑
    ...
```

**影响:** Button 现在有了 `process_tag` 和 `tag_mode` 两个新字段，缺失时自动补全。

### 3.4 Indicator — process_tag 自动生成 + blink_tag (行 389-398)

**变更前:**

```python
elif otype == "Indicator":
    tag = _req(o, "process_tag", where)  # 必填
    ...
```

**变更后:**

```python
elif otype == "Indicator":
    # 自动推断报警/状态类
    is_alarm_like = bool(
        o.get("blink") or
        (o.get("color_on") or "").startswith("#E2") or
        (o.get("color_on") or "").startswith("#e2")
    )
    ind_prefix = "LMP_" if is_alarm_like else "STS_"
    ind_tag = o.get("process_tag") or f"{ind_prefix}{oid}"
    if ind_tag not in tag_names:
        ir.setdefault("tags", []).append({...})  # 自动补全
    base["process_tag"] = ind_tag
    # 新增: blink_tag
    base["blink_tag"] = o.get("blink_tag") or (ind_tag if o.get("blink") else None)
    ...
```

**影响:** Indicator 的 `process_tag` 从必填变为自动生成；新增 `blink_tag` 字段用于指定闪烁绑定的变量。

---

## 4. 修改: prompts.py

**文件路径:** `backend/prompts.py`

### 4.1 新增 TAG_CONVENTIONS (行 135-155)

在 `TEXT_CONVENTIONS` 和 `VBS_CONVENTIONS` 之间新增：

```python
TAG_CONVENTIONS = r"""
【变量绑定硬性规范 — 必须严格遵守】
1. 所有 Button / Indicator / IOField / SymbolicIOField 对象都必须包含 process_tag 字段。
2. 变量名（process_tag）命名前缀规则：
   - 临时按钮 → BTN_ 前缀，例如 BTN_Start、BTN_Stop
   - 自保持/切换按钮 → MEM_ 前缀，例如 MEM_Mode、MEM_HandAuto
   - 运行/状态指示灯 → STS_ 前缀，例如 STS_Run、STS_Ready
   - 故障/报警指示灯 → LMP_ 前缀，例如 LMP_Fault、LMP_Alarm
   - 数值 IO 域 → IO_ 前缀，例如 IO_Speed、IO_Temp
   - 符号 IO 域 → SIO_ 前缀，例如 SIO_Mode、SIO_State
3. 每个声明的 process_tag 对应的变量必须出现在 tags 数组中。
4. 按钮必须标注 tag_mode：
   - "momentary"：瞬时按钮（按下置1，释放置0）
   - "toggle"：自保持切换按钮（每次按下翻转状态）
5. 指示灯对象可选 blink_tag 字段。
6. 不允许使用没有意义的变量名如 var1、tag2、temp。
"""
```

### 4.2 SYSTEM_PROMPT 注入 (行 235)

```python
# 变更前:
{TEXT_CONVENTIONS}
{VBS_CONVENTIONS}
{LAYOUT_CONVENTIONS}

# 变更后:
{TEXT_CONVENTIONS}
{TAG_CONVENTIONS}      # 新增
{VBS_CONVENTIONS}
{LAYOUT_CONVENTIONS}
```

### 4.3 IR_SCHEMA_DOC 更新

**Button schema — 新增字段:**

```json
{
  "id": "BTN_Start",
  "type": "Button",
  // ...原有字段...
  "process_tag": "关联的变量名，如 BTN_Start；必须出现在 tags 中",   // 新增
  "tag_mode": "枚举：momentary（瞬时）| toggle（自保持切换）",       // 新增
}
```

**Indicator schema — 新增字段:**

```json
{
  "id": "LMP_Run",
  "type": "Indicator",
  // ...原有字段...
  "blink_tag": "可选，闪烁绑定的变量（通常与 process_tag 相同）",    // 新增
}
```

---

## 5. 修改: simaticml_generator.py

**文件路径:** `backend/simaticml_generator.py`

### 5.1 _button_lines() — Button XML 生成 (行 136-195)

**变更内容:**

1. **新增 process_tag Connection 段:**
   
   ```python
   # 新增代码块
   pt = o.get("process_tag", "").strip()
   if pt:
    lines.append("<Connection>")
    lines.extend(_ind("", _elem("ProcessTag", text=pt)))
    lines.append("</Connection>")
   ```

2. **按 tag_mode 区分事件生成:**
   
   ```python
   # 变更前: 所有按钮统一 press/release/click
   event_keys = [("Press", "press_script"), ("Release", "release_script"),
              ("Click", "click_script")]
   ```

# 变更后:

if tag_mode == "toggle":
    # 自保持按钮：只需要 click_script
    sc = o.get("click_script")
    if sc:
        lines.append("<Events>")
        lines.extend(_ind("", [
            f"<Event Name=\"Click\">",
            _ind("", _elem("VBSFunction", text=sc)),
            "</Event>",
        ]))
        lines.append("</Events>")
else:
    # 瞬时按钮：press_script + release_script (+ 可选 click_script)
    event_keys = [("Press", "press_script"), ("Release", "release_script"),
                  ("Click", "click_script")]
    ...

```
### 5.2 _indicator_lines() — Indicator XML 生成 (行 180-225)

**变更内容:**

FlashAnimation 的 Tag 从硬编码 `process_tag` 改为可配置的 `blink_tag`:

```python
# 变更前:
f'<FlashAnimation Tag="{xml_escape(o["process_tag"])}">'

# 变更后:
blink_tag = xml_escape(o.get("blink_tag") or o["process_tag"])
f'<FlashAnimation Tag="{blink_tag}">'
```

---

## 6. 修改: openness_manager.py

**文件路径:** `backend/openness_manager.py`

### 6.1 新增 sync_tags() 方法 (行 911-1000)

```python
def sync_tags(self, tags: list) -> dict:
    """将 HMI Tags 自动写入 TIA Portal 项目的 HMI 变量表。"""
```

**核心逻辑:**

```
输入: tags 数组 [{name, data_type, address, comment}, ...]
│
├─ 获取 HMI 软件对象
├─ 获取或创建默认变量表 (sw.TagTables[0])
├─ 收集已有变量名 (table.Tags)
├─ 遍历 tags:
│  ├─ 跳过空名/已存在的变量
│  ├─ 映射 data_type → TIA 类型名 (Bool/Int/DInt/Real/Word/String)
│  ├─ table.Tags.Create(name, tia_type)
│  ├─ 设置 Address (如有)
│  └─ 设置 Comment (如有)
│
└─ 返回: {"ok": True/False, "created": [...], "skipped": [...], "errors": [...]}
```

### 6.2 import_or_generate_from_ir() — 自动同步 (行 1666-1682, 1742-1762)

在 **classic_template_xml** 和 **simaticml** 两个分支的导入成功后自动调用 `sync_tags()`:

```python
# 统一在导入成功后执行
import_result = self.import_screen_xml(...)

# ---- 自动同步 HMI 变量表 ----
tag_sync_result = None
if import_result.get("imported") and ir.get("tags"):
    try:
        tag_sync_result = self.sync_tags(ir["tags"])
        if tag_sync_result.get("created"):
            warnings.append(
                f"已同步 {len(tag_sync_result['created'])} 个变量到 HMI 变量表"
            )
    except Exception as sync_e:
        warnings.append(f"HMI 变量表同步异常：{sync_e}")

return {
    ...
    "tag_sync": tag_sync_result,   # 新增字段
}
```

---

## 7. 修改: pipeline_orchestrator.py

**文件路径:** `backend/pipeline_orchestrator.py`

### 7.1 导入 VariableEngine (行 29)

```python
from .variable_engine import VariableEngine
```

### 7.2 初始生成阶段集成 (行 218-224)

```python
# 变更前:
ir = sanitize_ir_text_fields(ir)

# ---- 如果审查未启用，直接返回 ----

# 变更后:
ir = sanitize_ir_text_fields(ir)

# ---- 变量引擎：自动绑定 process_tag + 生成 HMI Tags + VBS 脚本 ----
var_engine = VariableEngine()
ir = var_engine.generate(ir)
yield ("variable_bind", {
    "summary": VariableEngine.get_binding_summary(ir),
})

# ---- 如果审查未启用，直接返回 ----
```

### 7.3 修正阶段集成 (行 336-340)

```python
# 变更前:
current_ir = sanitize_ir_text_fields(current_ir)
yield ("parsed_ok", ...)

# 变更后:
current_ir = sanitize_ir_text_fields(current_ir)
# ---- 变量引擎：重新绑定（修正后可能有新对象） ----
current_ir = var_engine.generate(current_ir)
yield ("parsed_ok", ...)
```

---

## 8. 修改: app.py

**文件路径:** `app.py`

### 8.1 导入 VariableEngine (行 33)

```python
from backend.variable_engine import VariableEngine
```

### 8.2 /api/build — 集成 VariableEngine (行 274)

```python
# 变更前:
ir = extract_json(raw)
ir = validate_ir(ir)

# 变更后:
ir = extract_json(raw)
ir = validate_ir(ir)
# ---- 变量引擎：自动绑定 process_tag + 生成 HMI Tags + VBS 脚本 ----
ir = VariableEngine().generate(ir)
```

### 8.3 /api/build/template-xml — 集成 VariableEngine (行 417)

```python
# 变更前:
ir = validate_ir(ir_data)

# 变更后:
ir = validate_ir(ir_data)
# ---- 变量引擎 ----
ir = VariableEngine().generate(ir)
```

### 8.4 /api/openness/import — 集成 VariableEngine (行 464)

```python
# 变更前:
if ir_data:
    if mode in (...):
        result = get_openness().import_or_generate_from_ir(ir_data, mode)

# 变更后:
if ir_data:
    # ---- 变量引擎预处理（统一在导入前绑定变量） ----
    try:
        ir_data = validate_ir(ir_data)
        ir_data = VariableEngine().generate(ir_data)
    except (IRValidationError, ValueError) as e:
        return jsonify({"ok": False, "error": f"IR 校验失败：{e}"}), 400
    if mode in (...):
        result = get_openness().import_or_generate_from_ir(ir_data, mode)
```

### 8.5 新增 /api/openness/sync-tags 端点 (行 493)

```python
@app.route("/api/openness/sync-tags", methods=["POST"])
def openness_sync_tags():
    """手动同步变量到 TIA HMI 变量表。"""
    body = request.get_json(force=True)
    tags = body.get("tags") or []
    if not tags:
        return jsonify({"ok": False, "error": "tags 数组为空"}), 400
    return jsonify(get_openness().sync_tags(tags))
```

---

## 9. 数据流对比

### 升级前

```
用户需求
  ↓
LLM 生成 IR (JSON)
  ↓
validate_ir() — 校验 (process_tag 必须手动填写)
  ↓
SimaticML 生成
  ↓
TIA Openness 导入
  ↓
❌ 变量需在 TIA 中手动创建
```

### 升级后

```
用户需求
  ↓
LLM 生成 IR (JSON)
  ├─ prompts.py 注入 TAG_CONVENTIONS
  └─ LLM 主动按 BTN_/MEM_/STS_/LMP_/IO_ 规则命名
  ↓
validate_ir() — 校验 + 自动补全缺失的 process_tag
  ↓
VariableEngine.generate()
  ├─ 检测 tag_mode (momentary/toggle)
  ├─ 检测报警/状态指示灯
  ├─ 生成 VBS 脚本 (toggle NOT / momentary Set+Reset)
  ├─ 生成完整 tags[] 数组
  └─ 返回绑定摘要
  ↓
SimaticML 生成
  ├─ Button: 按 tag_mode 输出不同事件结构
  └─ Indicator: blink_tag 支持
  ↓
TIA Openness 导入
  ├─ Screens.Import(FileInfo, ImportOptions)
  └─ sync_tags(ir["tags"]) → HMI 变量表自动创建 ✅
```

---

## 10. 验证结果

### 10.1 测试套件

```
============================= test session starts =============================
platform win32 -- Python 3.13.0

tests/test_flask_api.py ............. 12 passed
tests/test_hmi_ir.py ................  8 passed
tests/test_openness_manager.py ..... 16 passed
tests/test_template_xml_generator.py 11 passed

============================= 47 passed in 0.98s ==============================
```

### 10.2 VariableEngine 功能验证

**输入 IR (带混合控件):**

```json
{
  "meta": {"screen_name": "Test"},
  "objects": [
    {"id": "BTN_Start", "type": "Button", "text": "启动"},
    {"id": "BTN_Stop",  "type": "Button", "text": "停止"},
    {"id": "Mode_Switch", "type": "Button", "text": "手动/自动"},
    {"id": "LMP_Run",   "type": "Indicator", "radius": 22},
    {"id": "LMP_Fault", "type": "Indicator", "radius": 22, "blink": true},
    {"id": "IO_Speed",  "type": "IOField", "decimal_digits": 1,
     "label": "转速", "unit": "rpm"}
  ]
}
```

**输出:**

| 对象 ID       | process_tag     | tag_mode  | 变量类型 |
| ----------- | --------------- | --------- | ---- |
| BTN_Start   | BTN_Start       | momentary | Bool |
| BTN_Stop    | BTN_Stop        | momentary | Bool |
| Mode_Switch | MEM_Mode_Switch | toggle    | Bool |
| LMP_Run     | LMP_Run         | —         | Bool |
| LMP_Fault   | LMP_Fault       | —         | Bool |
| IO_Speed    | IO_Speed        | —         | Real |

**自动生成的 VBS 脚本:**

| 脚本名                    | 功能                                                                |
| ---------------------- | ----------------------------------------------------------------- |
| Sub_BTN_Start_Press    | `SmartTags("BTN_Start") = 1`                                      |
| Sub_BTN_Start_Release  | `SmartTags("BTN_Start") = 0`                                      |
| Sub_BTN_Stop_Press     | `SmartTags("BTN_Stop") = 1`                                       |
| Sub_BTN_Stop_Release   | `SmartTags("BTN_Stop") = 0`                                       |
| Sub_Mode_Switch_Toggle | `SmartTags("MEM_Mode_Switch") = Not SmartTags("MEM_Mode_Switch")` |

**绑定摘要:**

```json
{
  "total_tags": 6,
  "by_type": {"Bool": 5, "Real": 1},
  "by_prefix": {
    "BTN_": ["BTN_Start", "BTN_Stop"],
    "MEM_": ["MEM_Mode_Switch"],
    "LMP_": ["LMP_Fault", "LMP_Run"],
    "IO_":  ["IO_Speed"]
  },
  "objects_bound": 6,
  "objects_unbound": []
}
```

### 10.3 hmi_ir 自动补全验证

**输入:** 不含 `process_tag` 的裸对象

```python
# IOField — 自动生成 IO_Speed
{"id": "Speed", "type": "IOField", ...}
→ process_tag = "IO_Speed"

# Indicator (无blink) — 自动生成 STS_Run
{"id": "Run", "type": "Indicator", ...}
→ process_tag = "STS_Run", blink_tag = None

# Indicator (blink) — 自动生成 LMP_Alarm
{"id": "Alarm", "type": "Indicator", "blink": true}
→ process_tag = "LMP_Alarm", blink_tag = "LMP_Alarm"

# Button — 自动生成 BTN_Start
{"id": "Start", "type": "Button", ...}
→ process_tag = "BTN_Start", tag_mode = "momentary"
```

---

## 附录 A: 变量命名规则速查表

| 对象类型            | 场景             | 前缀     | 示例          |
| --------------- | -------------- | ------ | ----------- |
| Button          | 瞬时操作（启动/停止/复位） | `BTN_` | `BTN_Start` |
| Button          | 自保持切换（手动/自动）   | `MEM_` | `MEM_Mode`  |
| Indicator       | 运行/状态指示        | `STS_` | `STS_Run`   |
| Indicator       | 故障/报警指示        | `LMP_` | `LMP_Fault` |
| IOField         | 数值显示/输入        | `IO_`  | `IO_Speed`  |
| SymbolicIOField | 枚举选择           | `SIO_` | `SIO_Mode`  |

## 附录 B: 自保持按钮检测关键词

```
切换, 自保持, 自锁, toggle, latch, 保持,
手动/自动, 手自动, 本地/远程, 就地/远方,
启动/停止, 正转/反转, 开/关
```

## 附录 C: 报警指示灯检测关键词

```
故障, 报警, alarm, fault, error, 警告,
急停, 过载, 超温, 过流, 过压, 欠压,
断线, 跳闸, 异常, 联锁
```

## 附录 D: 新增 SSE 事件类型

| 事件名             | 触发时机                 | data 内容                 |
| --------------- | -------------------- | ----------------------- |
| `variable_bind` | VariableEngine 执行完成后 | `{summary: {...}}` 绑定摘要 |

## 附录 E: 新增 API 端点

| 方法   | 路径                        | 功能                  |
| ---- | ------------------------- | ------------------- |
| POST | `/api/openness/sync-tags` | 手动同步变量到 TIA HMI 变量表 |

**请求体:**

```json
{
  "tags": [
    {"name": "BTN_Start", "data_type": "Bool", "address": "", "comment": "启动按钮"},
    {"name": "IO_Speed", "data_type": "Real", "address": "", "comment": "转速"}
  ]
}
```

**响应:**

```json
{
  "ok": true,
  "created": ["BTN_Start", "IO_Speed"],
  "skipped": [],
  "errors": []
}
```

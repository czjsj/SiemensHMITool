
# Siemens HMI 工程级变量系统完整接入方案（Claude Code 用）

## 0. 目标说明

本方案基于当前 Siemens HMI 画面生成系统（IR → SimaticML → TIA Openness），实现：

### ✔ 三大工程能力升级
1. 自动变量（HMI Tags）生成
2. Button / Indicator / IOField 统一绑定规则
3. IR → PLC/HMI变量全自动映射
4. TIA 可直接导入工程级一致性

---

# 1. 当前系统分析（基于你的项目）

你的系统已经具备：

### ✔ 已有能力
- LLM → IR 生成（prompts.py）
- IR 校验（hmi_ir.py）
- XML生成（simaticml_generator.py）
- TIA导入（openness_manager.py）
- 视觉审查（MiMo pipeline）

---

### ❗缺失关键能力（本方案核心）
当前缺少：

- ❌ IR 无变量规划层
- ❌ 无统一 Tag Binding Engine
- ❌ HMI Tags 需要人工维护
- ❌ Button/Indicator/IOField 无自动映射

---

# 2. 新增核心模块设计

## ✔ 新模块：variable_engine.py

路径：
```
backend/variable_engine.py
```

---

## 2.1 变量命名规则

| 类型 | 前缀 | 示例 |
|------|------|------|
| Button | BTN_ | BTN_Start |
| Toggle Button | MEM_ | MEM_Mode |
| Indicator | STS_ | STS_Run |
| Lamp | LMP_ | LMP_Alarm |
| IOField | IO_ | IO_Speed |

---

## 2.2 IR 扩展结构

```json
{
  "id": "BTN_Start",
  "type": "Button",
  "process_tag": "BTN_Start",
  "tag_mode": "momentary | toggle"
}
```

---

# 3. Variable Engine 核心逻辑

```python
class VariableEngine:

    def generate(self, ir):
        tags = []

        for obj in ir["objects"]:
            t = obj["type"]
            name = obj["id"]

            # Button
            if t == "Button":
                tag = self._btn(name, obj)
                obj["process_tag"] = tag
                obj["tag_mode"] = "toggle" if obj.get("self_holding") else "momentary"

                tags.append({
                    "name": tag,
                    "data_type": "BOOL",
                    "default": 0
                })

            # Indicator
            elif t == "Indicator":
                tag = f"STS_{name}"
                obj["process_tag"] = tag

                tags.append({
                    "name": tag,
                    "data_type": "BOOL",
                    "default": 0
                })

            # IOField
            elif t == "IOField":
                tag = f"IO_{name}"
                obj["process_tag"] = tag

                tags.append({
                    "name": tag,
                    "data_type": obj.get("data_type", "REAL"),
                    "default": 0
                })

        ir["tags"] = tags
        return ir
```

---

# 4. Button 控件规则（关键）

## 4.1 普通按钮（瞬时）

| 行为 | 逻辑 |
|------|------|
| Press | SetBit |
| Release | ResetBit |

---

## 4.2 自保持按钮（Toggle）

```vb
SmartTags("MEM_Mode") = NOT SmartTags("MEM_Mode")
```

---

# 5. Indicator 动态系统

## 5.1 状态变量

| 状态 | 变量 |
|------|------|
| 运行 | STS_Run |
| 报警 | STS_Alarm |

---

## 5.2 动态颜色规则

| 状态 | 颜色 |
|------|------|
| 0 | 灰 |
| 1 | 绿 |
| 2 | 红 |

---

## 5.3 闪烁规则

```text
if STS_Alarm == 1:
    enable blink animation
```

---

# 6. IOField 绑定规则

## 6.1 数值输入

```
IO_Speed → REAL
IO_Temp  → INT
```

## 6.2 枚举

```
IO_Mode → 0/1/2 TextList
```

---

# 7. HMI Tags 自动生成（核心能力）

## 7.1 自动生成规则

```text
Button → BTN_/MEM_
Indicator → STS_
IOField → IO_
```

---

## 7.2 自动生成结构

```json
{
  "hmi_tags": [
    {"name": "BTN_Start", "type": "BOOL"},
    {"name": "STS_Run", "type": "BOOL"},
    {"name": "IO_Speed", "type": "REAL"}
  ]
}
```

---

# 8. Pipeline 集成位置（非常重要）

## 在 pipeline_orchestrator.py 中插入：

```python
ir = validate_ir(ir)

# 新增变量系统
ir = VariableEngine().generate(ir)

# 继续后续流程
xml = generate_simaticml(ir)
```

---

# 9. TIA Openness 自动写入

## 在 openness_manager.py 增强：

```python
def sync_tags(self, tags):
    hmi = self._find_hmi_software()
    table = hmi.TagTables[0]

    for t in tags:
        table.Tags.Create(t["name"], t["data_type"])
```

---

# 10. SimaticML 扩展（按钮行为）

## Press/Release 映射

```text
momentary:
    Press → Set
    Release → Reset

toggle:
    Press → NOT variable
```

---

# 11. Indicator XML增强

```text
process_tag → ColorAnimation
blink_tag   → FlashAnimation
```

---

# 12. prompts.py 必须新增规则

在 SYSTEM_PROMPT 添加：

> 所有对象必须生成 process_tag  
> Button 必须自动选择 BTN_/MEM_  
> Indicator 必须绑定 STS_  
> IOField 必须绑定 IO_  

---

# 13. validate_ir 增强规则

```python
if obj["type"] == "IOField":
    obj.setdefault("process_tag", "IO_" + obj["id"])
```

---

# 14. 完整系统数据流（升级后）

```
用户需求
   ↓
LLM (IR生成)
   ↓
validate_ir
   ↓
VariableEngine（新增）
   ↓
IR + tags
   ↓
SimaticML生成
   ↓
TIA Openness导入
   ↓
自动生成HMI变量表
```

---

# 15. 系统升级本质

你现在系统升级为：

## ✔ 从“画面生成器”
升级为：

# 🔥 工业级 HMI 自动工程系统

能力包括：
- 自动变量规划
- 自动控件绑定
- 自动PLC/HMI映射
- 自动TIA工程生成

---

# 16. 推荐下一步升级（强烈建议）

如果你继续做，我可以帮你升级到：

### 1️⃣ PLC DB 自动生成（S7-1500）
### 2️⃣ HMI + PLC 双向同步
### 3️⃣ 状态机驱动 Indicator 系统
### 4️⃣ 全自动设备模板生成器

---

# END

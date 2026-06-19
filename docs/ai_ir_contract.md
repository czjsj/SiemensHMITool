# AI IR 输出契约

> **目标**: AI 只输出语义 IR，不直接生成 TIA XML 事件细节。

---

## 核心约束

1. AI 只能输出 HMI IR / HmiProjectSpec JSON
2. AI 不能输出 TIA XML
3. AI 不能臆造 VBS / JS 事件结构
4. AI 不能直接生成底层 EventHandler XML
5. AI 不能直接生成底层 Dynamization XML

---

## 按钮必须输出的字段

```json
{
  "type": "button",
  "behavior": "momentary | toggle | set | reset | navigate",
  "binding": {
    "tag": "变量名",
    "direction": "write | read_write"
  },
  "template_ref": "BTN_MOMENTARY_TEMPLATE | BTN_TOGGLE_TEMPLATE | ..."
}
```

---

## 指示灯必须输出的字段

```json
{
  "type": "indicator",
  "indicator_mode": "bool_color | bool_blink | multi_state | alarm | warning | status",
  "binding": {
    "tag": "变量名",
    "direction": "read"
  },
  "template_ref": "LMP_STATUS_TEMPLATE | LMP_ALARM_TEMPLATE | ...",
  "states": []
}
```

---

## 变量命名规则

| 控件类型 | 前缀 | 说明 |
|---------|------|------|
| Button (write) | BTN_ | 按钮写入变量 |
| Button (toggle) | MEM_ 或 BTN_ | 切换按钮变量 |
| Indicator (status) | STS_ 或 LMP_ | 状态指示灯变量 |
| Indicator (alarm) | STS_ 或 LMP_ | 报警指示灯变量 |
| IO Field | IO_ | 数值输入输出 |
| Symbolic IO | SIO_ | 符号选择变量 |
| Internal | MEM_ | HMI 内部变量 |

所有 binding.tag 必须出现在 tags 列表中。

---

## PLC 地址规则

- 如果用户没有提供 PLC 地址，`address` 必须为 `null`
- 不得编造 PLC 地址
- 未提供地址时设置 `metadata.pending_mapping = true`

---

## 严禁事项

- 不得直接生成 TIA XML 字符串
- 不得生成 `<EventHandler>` 节点
- 不得生成 `<Dynamization>` 节点
- 不得编造 PLC 地址
- 不得在 IR 中嵌入 VBS 脚本代码

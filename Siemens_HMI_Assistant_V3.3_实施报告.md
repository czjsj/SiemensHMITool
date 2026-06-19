# Siemens HMI Assistant V3.3 — Basic Panel 变量创建与引用链路修复报告

**生成日期**: 2026-06-19
**分支**: main
**基准提交**: b1432f1 (V3.3) / faaa60d (V3.1)

---

## 一、背景与问题

通过 TIA 编译和事件界面确认，Basic Panel 导入后存在以下真实问题：

| # | 问题 | 后果 |
|---|------|------|
| 1 | HMI 变量未导入 DefaultTagTable | 所有引用落空，画面不可运行 |
| 2 | 所有复制按钮的 FunctionList 参数仍引用模板变量 `Button` | 按钮点击无效果或指向错误变量 |
| 3 | IOField 的 ProcessTag 引用不存在 | 编译报错"过程变量丢失" |
| 4 | SymbolicIOField 同时缺失 ProcessTag 和 TextList | 编译报错"未定义文本列表" |

**修复范围**: 仅 Basic Classic 变量创建和引用链路，不开发新控件。

---

## 二、修改概览

```
20 files changed, +1377 insertions, -153 deletions
296 tests passed (0 failures)
```

### 修改文件清单

| 文件 | 变更行数 | 类型 | 说明 |
|------|----------|------|------|
| `backend/backends/classic/basic_backend.py` | +443/-97 | 重写 | 8 步部署流程 + 真实验收 |
| `backend/backends/classic/classic_screen_reference_rewriter.py` | +330 | **新建** | 全量变量引用重写器 |
| `backend/backends/classic/tag_xml_builder.py` | +219/-78 | 增强 | 真实 Basic 导出 XML + 文本列表生成 |
| `backend/backends/classic/screen_xml_builder.py` | +156/-54 | 增强 | ProcessTag/TextList/Event/DynamicBinding |
| `backend/openness/classic_executor.py` | +581/-353 | 重写 | DefaultTagTable 导入 + 验收验证 |
| `backend/backends/classic/common.py` | +68/-6 | 增强 | 集成 ClassicScreenReferenceRewriter |
| `backend/backends/classic/link_resolver.py` | +12 | 增强 | LinkList/OpenLink 引用重写 |
| `backend/backends/classic/__init__.py` | +8 | 小改 | 导出新类 |
| `backend/variable_engine.py` | +32/-4 | 增强 | DefaultTagTable + 文本列表 |
| `backend/domain/diagnostics.py` | +7 | 小改 | 新增 3 个诊断码 |

---

## 三、6 点需求逐项实现

### 3.1 变量导入默认变量表

**API 路径**（严格按用户验证过的调用）:
```
hmiTarget.TagFolder.DefaultTagTable.Tags.Import(FileInfo, ImportOptions.Override)
```

**禁止路径**（代码中显式标注禁止）:
```
TagFolder.Importer.Import(StreamReader)  — 不存在且未经验证
```

**每个变量生成独立的真实 Basic 单变量导出 XML**:
- `tag_xml_builder.py` → `build_single_tag_export_xml(tag)` — 每个变量一个文件
- `build_tags_batch_export_xml(tags)` — 批量导出
- 根对象为 `<SW.Tag>`, 内嵌 `<AttributeList><Name>...</Name><DataType>...</DataType></AttributeList>`

**支持的数据类型**:
```python
SUPPORTED_DATA_TYPES = {"Bool", "Int", "DInt", "Real", "Word", "String", "WString"}
```

**导入顺序**: tags → text_lists → screens

**导入后验证**: Step 2 重新遍历 `DefaultTagTable.Tags`，确认所有 required tag names 已真实存在，缺少则返回 `VERIFY_TAG_MISSING` 并停止部署。

---

### 3.2 每控件独立变量映射

**禁止**: 所有按钮共用模板变量 `Button`

**映射表**（`basic_backend.py:_build_control_binding_map()`）:

| 控件 ID | 变量名 | 类型 | 模式 |
|---------|--------|------|------|
| BTN_Start | CMD_Start | Button | momentary |
| BTN_Stop | CMD_Stop | Button | momentary |
| BTN_Reset | CMD_Reset | Button | momentary |
| BTN_Mode | HMI_ModeToggle | Button | toggle |
| IO_Speed | HMI_Speed | IOField | — |
| IO_Username | Login_Username | IOField | — |
| IO_Password | Login_Password | IOField | — |
| SIO_Mode | HMI_Mode | SymbolicIOField | — |

**瞬时按钮事件映射**:
- Press → SetBit(该按钮自己的变量)
- Release → ResetBit(该按钮自己的变量)

**实现位置**: `variable_engine.py:_enrich_button()` 和 `basic_backend.py:_build_control_binding_map()`

---

### 3.3 ClassicScreenReferenceRewriter

**新建文件**: `backend/backends/classic/classic_screen_reference_rewriter.py` (330行)

**重写范围**（按需求逐一实现）:

| 引用位置 | 重写方法 | 说明 |
|----------|----------|------|
| FunctionList Action 参数 | `_rewrite_function_list_events()` | Press/Release/Click 中的 TagName |
| Event 参数 | `_resolve_event_tag()` | 根据事件类型匹配正确变量 |
| IOField ProcessTag | `_rewrite_process_tag()` | AttributeList 内 ProcessTag 节点 |
| SymbolicIOField ProcessTag + TextList | `_rewrite_text_list()` | 同时重写 ProcessTag 和 TextList 引用 |
| 动态颜色 SourceTag | `_rewrite_dynamic_tag_triggers()` | TagElementTrigger→LinkList→Tag→Name |
| 可见性/闪烁引用 | `_rewrite_dynamic_references()` | RangeAppearanceAnimation 内 Tag 引用 |
| LinkList/OpenLink 变量 Name | `_rewrite_link_list_references()` | `<Tag TargetID="@OpenLink"><Name>...</Name></Tag>` |

**禁止全局字符串替换 `Button`** — 所有重写基于控件上下文逐节点匹配。

---

### 3.4 模板引用泄漏检查

**Catalog manifest 中记录模板变量名**:
```python
# common.py
TEMPLATE_TAG_NAMES: set[str] = {"Button", "Template_ProcessTag", "Template_TextList"}
```

**泄漏检查点**（`check_template_leaks()`）:
1. XML 中仍包含模板变量 `Button`（在 TagName/ProcessTag/Name 等引用位置）
2. XML 中仍包含 `Template_ProcessTag`
3. XML 中仍包含 `Template_TextList`

**发现泄漏时**: 返回诊断码 `CLASSIC_TEMPLATE_TAG_REFERENCE_LEAK` 并拒绝导入画面。

**检查时机**: 画面 XML 重写后、导入前。

---

### 3.5 文本列表

**自动生成**: `tag_xml_builder.py:build_text_list_xml()`

**示例 — SIO_Mode**:
| 属性 | 值 |
|------|-----|
| Tag | HMI_Mode, Int |
| TextList 名称 | ModeTextList |
| 条目 | 0=停止, 1=手动, 2=自动 |

**导入顺序**: `import tags → import text lists → import screens`

**未创建 TextList 时**: 不得生成 SymbolicIOField → 降级为普通 IOField
- 诊断码: `SYMBOLIC_IO_DOWNGRADED`
- XML 中 `Hmi.Screen.SymbolicIOField` → `Hmi.Screen.IOField`

---

### 3.6 真实验收（6 项条件）

**验收方法**: `classic_executor.py:verify_deployment_acceptance()`

部署后从 TIA 重新读取:

| 检查项 | 内容 | 通过条件 |
|--------|------|----------|
| ① | DefaultTagTable 中的变量名称和类型 | 所有 required tags 位于 DefaultTagTable |
| ② | 按钮 FunctionList 变量参数 | 所有画面引用指向真实变量 |
| ③ | IOField ProcessTag | 无任何模板变量引用残留 |
| ④ | SIOField TextList | 无"未定义文本列表"警告 |
| ⑤ | 编译消息 | 无"过程变量丢失"警告 |
| ⑥ | 编译结果 | Error=0 |

**状态判定**: **只有 6 项全部通过才返回 `DEPLOYED`**。

---

## 四、产物日志

部署成功后自动生成 JSON 日志（`generate_artifact_log()`），包含:

```json
{
  "generated_at": "ISO 8601 timestamp",
  "generated_tag_xml_paths": ["tag_CMD_Start.xml", ...],
  "imported_tag_names": ["CMD_Start", "CMD_Stop", ...],
  "actual_default_table_tags": {
    "tag_names": ["CMD_Start", ...],
    "count": 6,
    "tags": [{"name": "CMD_Start", "data_type": "Bool", "scope": "internal"}, ...]
  },
  "object_to_tag_binding_map": {
    "BTN_Start": {"tag_name": "CMD_Start", "control_type": "Button"},
    ...
  },
  "remaining_template_references": [],
  "compile_warnings_errors": []
}
```

---

## 五、新增诊断码

| 诊断码 | 严重级别 | 说明 |
|--------|----------|------|
| `CLASSIC_TEMPLATE_TAG_REFERENCE_LEAK` | ERROR | 画面 XML 中仍残留模板变量引用 |
| `TEXT_LIST_MISSING` | WARNING | 文本列表未找到 |
| `SYMBOLIC_IO_DOWNGRADED` | WARNING | SIO 因无 TextList 降级为普通 IOField |

---

## 六、测试结果

```
============================= 296 passed in 2.55s =============================

tests/test_backends.py                13 passed
tests/test_capabilities.py            14 passed
tests/test_classic_builders.py        31 passed
tests/test_deployment_pipeline.py     26 passed
tests/test_domain_diagnostics.py      15 passed
tests/test_domain_ir_v2.py            20 passed
tests/test_domain_legacy_adapter.py   18 passed
tests/test_flask_api.py               12 passed
tests/test_hmi_api.py                  7 passed
tests/test_hmi_ir.py                   8 passed
tests/test_openness_manager.py        16 passed
tests/test_openness_modules.py        17 passed
tests/test_planners.py                13 passed
tests/test_template_xml_generator.py  11 passed
tests/test_unified_backend.py         31 passed
tests/test_variable_engine_v2.py      22 passed
tests/test_verification.py            14 passed
```

---

## 七、部署流程总览

```
BasicBackend.execute()
│
├─ Step 1: 生成变量 XML (真实 Basic 单变量导出格式)
│   └─ tag_xml_builder.build_single_tag_export_xml() × N
│
├─ Step 2: 导入变量到 DefaultTagTable
│   └─ DefaultTagTable.Tags.Import(FileInfo, ImportOptions.Override)
│
├─ Step 3: 重新遍历 DefaultTagTable 验证
│   └─ 缺少变量 → VERIFY_TAG_MISSING → 停止部署
│
├─ Step 4: 构建每控件独立绑定映射
│   └─ _build_control_binding_map() → {control_id → {tag_name, control_type, ...}}
│
├─ Step 5: 生成并导入文本列表
│   └─ 无 TextList → SYMBOLIC_IO_DOWNGRADED → 降级为 IOField
│
├─ Step 6: 重写画面 XML 全部引用
│   └─ ClassicScreenReferenceRewriter.rewrite_screen_xml()
│
├─ Step 7: 模板引用泄漏检查
│   └─ 发现泄漏 → CLASSIC_TEMPLATE_TAG_REFERENCE_LEAK → 拒绝导入
│
├─ Step 8: 导入画面 + 编译
│   └─ ClassicOpennessExecutor.execute_all()
│
└─ Step 9: 真实验收 (6 项检查)
    └─ 6/6 通过 → DEPLOYED
        任一失败 → VERIFICATION_FAILED
```

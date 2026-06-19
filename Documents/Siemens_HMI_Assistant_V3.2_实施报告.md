# Siemens HMI Assistant V3.2 — 真实 TIA Openness 部署链路实施报告

**版本**: V3.2 (基于 V3.1 增强)  
**日期**: 2026-06-19  
**目标**: 证明 Basic/Comfort/Unified 三个后端真正调用 Siemens TIA Portal Openness，而非仅生成 XML/Spec 或模拟 success=true  

---

## 1. 审计结论: 现有 execute() 全路径分类

### 1.1 V3.1 每条 execute() 路径分类

| 端点/方法                               | 路径              | 分类                     | 问题                                            |
| ----------------------------------- | --------------- | ---------------------- | --------------------------------------------- |
| `BasicBackend.execute()`            | connected=False | `DESCRIPTION_ONLY`     | 返回 success=False, NOT_CONNECTED ✅             |
| `BasicBackend.execute()`            | connected=True  | **`DESCRIPTION_ONLY`** | ❌ 只计数 step，不调用任何 Siemens API，却返回 success=True |
| `ComfortBackend.execute()`          | connected=False | `DESCRIPTION_ONLY`     | 返回 success=False, NOT_CONNECTED ✅             |
| `ComfortBackend.execute()`          | connected=True  | **`DESCRIPTION_ONLY`** | ❌ 同上 — 零 TIA_MUTATION 却 success=True          |
| `UnifiedBackend.execute()`          | connected=False | `DESCRIPTION_ONLY`     | 返回 success=False, NOT_CONNECTED ✅             |
| `UnifiedBackend.execute()`          | connected=True  | **`DESCRIPTION_ONLY`** | ❌ 同上 — 零 TIA_MUTATION 却 success=True          |
| `DeploymentService.deploy()` Step 4 | 真实执行            | **`DESCRIPTION_ONLY`** | 注释明写 "当前 backend.execute 为 dry 模式"            |
| `DeploymentService.deploy()` Step 6 | 编译              | **`DESCRIPTION_ONLY`** | 调用 `compiler.compile(None)` — 传 None          |
| `/api/hmi/compile`                  | 编译              | `TIA_MUTATION` ✅       | 唯一真实调用: `ICompilable.Compile()`               |

**结论**: V3.1 中三个后端的 `execute()` 在 connected=True 时 **零 `TIA_MUTATION` 调用**，却返回 success=True。这是 V3.2 要解决的核心问题。

### 1.2 V3.2 修正后分类

| 端点/方法                      | 路径                 | 分类                                                         |
| -------------------------- | ------------------ | ---------------------------------------------------------- |
| `BasicBackend.execute()`   | dry_run=True       | `DESCRIPTION_ONLY` → status=DRY_RUN                        |
| `BasicBackend.execute()`   | dry_run=False, 未连接 | `DESCRIPTION_ONLY` → status=NOT_CONNECTED                  |
| `BasicBackend.execute()`   | dry_run=False, 已连接 | **`TIA_MUTATION`** → ClassicOpennessExecutor.execute_all() |
| `ComfortBackend.execute()` | 同上                 | **`TIA_MUTATION`** → ClassicOpennessExecutor.execute_all() |
| `UnifiedBackend.execute()` | 同上                 | **`TIA_MUTATION`** → UnifiedOpennessExecutor.execute_all() |
| `Backend.verify()`         | 已连接                | **`TIA_QUERY`** → ObjectQueryService.query_full_snapshot() |
| `HmiCompiler.compile()`    | sw != None         | **`TIA_QUERY`** + `TIA_MUTATION` → ICompilable.Compile()   |

---

## 2. 部署状态机 (V3.2 新增)

```text
                 ┌─────────────┐
                 │   DRY_RUN   │  dry_run=true → 只验证计划，不连 TIA
                 └──────┬──────┘
                        │ dry_run=false
                 ┌──────▼──────┐
                 │NOT_CONNECTED│  未连接 TIA Portal
                 └──────┬──────┘
                        │ connected=true
                 ┌──────▼──────┐
                 │   BLOCKED   │  catalog 不完整 / capability 不支持
                 └──────┬──────┘
                        │ 所有阻断通过
                 ┌──────▼──────┐
                 │  DEPLOYING  │  真实 TIA 操作进行中
                 └──────┬──────┘
                        │
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
   ┌──────────┐ ┌──────────────┐ ┌──────────────┐
   │ DEPLOYED │ │VERIFY_FAILED │ │COMPILE_FAILED│
   │ (编译0错)│ │ (语义不匹配) │ │ (编译Error>0)│
   └──────────┘ └──────────────┘ └──────────────┘
                        │
                   ┌────▼────┐
                   │  FAILED │  任一步骤异常
                   └─────────┘
```

### 2.1 严格行为要求

| 条件                          | 状态                  | success | 含义                     |
| --------------------------- | ------------------- | ------- | ---------------------- |
| dry_run=true                | DRY_RUN             | true    | 计划验证通过，未执行真实部署         |
| dry_run=false, 未连接          | NOT_CONNECTED       | false   | 不可执行                   |
| connected=true, catalog 阻断  | BLOCKED             | false   | 阻断                     |
| connected=true, executor 异常 | FAILED              | false   | 异常                     |
| 编译 Error=0, 语义匹配            | DEPLOYED            | true    | **唯一可返回 deployed 的路径** |
| 编译 Error>0                  | COMPILE_FAILED      | false   | 部署完成但编译失败              |
| 编译 OK 但语义不匹配                | VERIFICATION_FAILED | false   | 对象不匹配                  |

**connected=true 不能自动代表部署成功。**

---

## 3. BackendFactory AUTO 路由修正

### V3.1 (旧)

```python
else:  # HmiFamily.AUTO 或 unknown
    return ComfortBackend()  # 默认为 Comfort — 不正确
```

### V3.2 (新)

```python
elif target.family == HmiFamily.AUTO:
    return BackendFactory._resolve_auto(target)
    # AUTO → DeviceDiscovery → 根据真实 HMI 软件类型选择

@staticmethod
def create_with_discovery(target, hmi_software=None):
    """若无 hmi_software 则返回 TARGET_FAMILY_AMBIGUOUS 诊断。
       不得默认选择 Comfort。"""
```

---

## 4. 新增文件

| 文件                                         | 行数   | 用途                                        |
| ------------------------------------------ | ---- | ----------------------------------------- |
| `backend/openness/classic_executor.py`     | 300+ | Classic OEM (Basic/Comfort) 真实 TIA API 调用 |
| `backend/openness/unified_executor.py`     | 350+ | Unified OEM 真实 TIA API 调用                 |
| `backend/openness/object_query_service.py` | 280+ | 从 TIA 项目读取真实对象快照                          |

### 4.1 ClassicOpennessExecutor 方法

**官方 API: Composition.Import(FileInfo, ImportOptions)**

所有 Classic 导入使用官方 FileInfo + ImportOptions 模式:
1. 将 XML 写入临时文件
2. `System.IO.FileInfo(temp_path)` 包装
3. 调用 `Folder.Import(FileInfo, ImportOptions)`
4. 不再使用 `StreamReader` / `MemoryStream` 路径

| 方法                   | 操作类别         | Siemens API 调用                                                    |
| ---------------------- | ---------------- | ------------------------------------------------------------------- |
| `locate_hmi_target()`  | TIA_QUERY        | `project.Devices → DeviceItems → SoftwareContainer.Software`        |
| `import_connections()` | TIA_MUTATION     | `hmiSoftware.Connections.Import(FileInfo, ImportOptions)`            |
| `import_tags()`        | TIA_MUTATION     | `hmiSoftware.TagFolder.Tags.Import(FileInfo, ImportOptions)`         |
| `import_scripts_and_resources()` | TIA_MUTATION | `hmiSoftware.ScriptFolder.Scripts.Import(FileInfo, ImportOptions)` |
| `import_screens()`     | TIA_MUTATION     | `hmiSoftware.ScreenFolder.Screens.Import(FileInfo, ImportOptions)`   |
| `compile_hmi()`        | TIA_MUTATION     | `ICompilable.Compile()` + `CompilerResult.Messages[]` 递归           |
| `_collect_compiler_messages()` | TIA_QUERY  | `Messages[]` → 每条 msg: `Severity`/`Description`/`Path`/`ObjectName` → 递归 `msg.Messages[]` |

### 4.2 UnifiedOpennessExecutor 方法

**Unified API 路径 (与 Classic 不同):**
- `hmiSoftware.Tags` — 直接集合 (非 `TagFolder.Tags`)
- `hmiSoftware.Screens` — 直接集合 (非 `ScreenFolder.Screens`)
- `screen.ScreenItems` — 控件集合

| 方法                      | 操作类别         | Siemens API 调用                                                     |
| ------------------------- | ---------------- | -------------------------------------------------------------------- |
| `ensure_contract()`       | TIA_QUERY        | 加载/探测 RuntimeContract                                             |
| `create_tags()`           | TIA_MUTATION     | `hmiSoftware.Tags` 遍历 + Create(name, dataType)                       |
| `create_screens()`        | TIA_MUTATION     | `hmiSoftware.Screens` 遍历 + Create(name)                             |
| `_create_screen_item()`   | TIA_MUTATION     | `screen.ScreenItems.Create(typeKey)` + 属性 setter + Dynamizations + Events |
| `set_scripts()`           | TIA_MUTATION     | ScriptCode setter                                                     |
| `compile_hmi()`           | TIA_MUTATION     | `ICompilable.Compile()`                                               |

### 4.3 ObjectQueryService 方法 — 只读, 编译一次

**原则:**
1. 只读 — 永不允许调用 `Compile()` 或任何修改操作
2. `compiled_result` 由外部传入 — 编译只在 `DeploymentService.deploy()` 中执行一次
3. 路径感知 — `family="comfort"|"basic"|"unified"` 参数区分 Classic vs Unified API
4. 持久化 — `save_snapshot()`, `save_compile_messages()`, `save_import_log()`, `save_reverse_export_xml()` 落盘

| 方法                         | 操作类别      | Siemens API 调用 (family-aware)                                                 |
| ---------------------------- | ------------- | ------------------------------------------------------------------------------- |
| `query_full_snapshot(hmi_sw, compiled_result, family)` | TIA_QUERY | 组合以下查询; `compiled_result` 外部传入，绝不内部 Compile                          |
| `query_tags(hmi_sw, unified)` | TIA_QUERY | Classic: `TagFolder.Tags`; Unified: `hmiSoftware.Tags` (直接集合)                  |
| `query_screens(hmi_sw, unified)` | TIA_QUERY | Classic: `ScreenFolder.Screens`; Unified: `hmiSoftware.Screens` (直接集合)          |
| `query_screen_items(screen)` | TIA_QUERY    | `screen.ScreenItems`: Name, Type(反射), Left, Top, Width, Height                  |
| `query_dynamizations(hmi_sw, unified)` | TIA_QUERY | `ScreenItem.Dynamizations`: 类型, PropertyName, TagName                             |
| `query_event_handlers(hmi_sw, unified)` | TIA_QUERY | `ScreenItem.Events + Actions`: 事件类型, 动作类型, TagName/ScreenName/ScriptName      |
| `query_scripts(hmi_sw, unified)` | TIA_QUERY | Classic: `ScriptFolder.Scripts`; Unified: `hmiSoftware.Scripts` (优先后回退)        |
| `export_screens_xml(hmi_sw, unified)` | TIA_QUERY | `screen.Export(FileInfo, ExportOptions)` — 反向导出用于对比                          |
| `save_snapshot / save_compile_messages / save_import_log` | — | JSON 落盘到 export_dir                                                             |
| `query_compile_messages()` | TIA_QUERY | `ICompilable.Compile()` + ErrorMessages/WarningMessages/InfoMessages     |

---

## 5. 三个后端真实执行调用图

### 5.1 Comfort Backend

```
ComfortBackend.execute(plan, context)
├── plan.dry_run? → DRY_RUN ✅
├── !connected? → NOT_CONNECTED ✅
├── locate_hmi_target(project_obj)         [TIA_QUERY]
│   └── project.Devices[] → DeviceItems[] → SoftwareContainer.Software
├── compile_tags(spec.tags)                [DESCRIPTION_ONLY]
├── build_vbs_script(spec.scripts)         [DESCRIPTION_ONLY]
├── compile_screen(spec.screens)           [DESCRIPTION_ONLY]
└── ClassicOpennessExecutor.execute_all()  [TIA_MUTATION]
    ├── import_connections()               → Connections exist/Create
    ├── import_tags(tags_xml)              → TagFolder.Importer.Import()
    ├── import_scripts_and_resources()     → ScriptFolder.Importer.Import()
    ├── import_screens(screen_xml_list)    → ScreenFolder.Importer.Import()
    └── compile_hmi()                      → ICompilable.Compile()
                                            → collect_compile_messages() 递归

ComfortBackend.verify(spec, context)
├── !connected? → NOT_CONNECTED ✅
├── ObjectQueryService.query_full_snapshot()  [TIA_QUERY]
│   ├── query_tags()          → TagFolder.Tags遍历
│   ├── query_screens()       → ScreenFolder.Screens遍历
│   ├── query_dynamizations() → ScreenItem.Dynamizations遍历
│   ├── query_event_handlers()→ ScreenItem.Events遍历
│   ├── query_scripts()       → ScriptFolder.Scripts遍历
│   └── query_compile_messages() → ICompilable.Compile()
└── VerificationService.verify_full(spec, snapshot, connected=True)
```

### 5.2 Basic Backend

```
BasicBackend.execute(plan, context)
├── plan.dry_run? → DRY_RUN ✅
├── !connected? → NOT_CONNECTED ✅
├── compile_tags(spec.tags)                [DESCRIPTION_ONLY]
├── compile_screen(spec.screens)           [DESCRIPTION_ONLY]
└── ClassicOpennessExecutor.execute_all()  [TIA_MUTATION]
    (同 Comfort 但不含 scripts_xml — Basic 禁止 VBS)

BasicBackend.verify(spec, context)
└── 同 ComfortBackend.verify()
```

### 5.3 Unified Backend

```
UnifiedBackend.execute(plan, context)
├── plan.dry_run? → DRY_RUN ✅
├── !connected? → NOT_CONNECTED ✅
├── UnifiedOpennessExecutor.ensure_contract()  [TIA_QUERY]
│   ├── RuntimeContract.load(cache) → 命中 ✅
│   └── RuntimeProber.probe() → 扫描 DLL → 写入 cache
├── 构建 tag_specs/screen_specs/script_specs  [DESCRIPTION_ONLY]
└── UnifiedOpennessExecutor.execute_all()      [TIA_MUTATION]
    ├── create_tags(tag_specs)                → TagFolder.Tags遍历 + Create
    ├── create_screens(screen_specs)          → ScreenFolder.Screens遍历 + Create
    │   └── _create_screen_item() × N         → ScreenItems.Create + 属性
    │       └── Dynamizations.Create × N      → 每个 binding
    │       └── EventHandlers.Create × N      → 每个 event
    ├── set_scripts(script_specs)             → ScriptCode setter
    └── compile_hmi()                          → ICompilable.Compile()

UnifiedBackend.verify(spec, context)
└── 同 ComfortBackend.verify()
```

---

## 6. Catalog 强化 (V3.2)

### 6.1 Manifest 新增字段

```yaml
source:
  # V3.1 原有
  verified_import: false
  verified_compile: false
  # V3.2 新增 — 只有验证工具生成证据后 Catalog 才视为 verified
  source_xml_sha256: ""           # 黄金 XML SHA256
  tia_version_full: ""            # 完整 TIA 版本号 (如 "V20.0.0.1")
  device_order_number: ""         # 设备订货号 (如 "6AV2 124-0MC01-0AX0")
  verified_project_name: ""       # 验证用项目名称
  verified_at: ""                 # 验证时间 ISO 8601
  compiler_error_count: -1        # 编译错误数 (-1 = 未执行)
  verification_evidence_path: ""  # 证据文件路径
```

### 6.2 CatalogManifest 新增属性

`CatalogManifest.source` dict 现在可获取:

- `source_xml_sha256` — 缺失时产生 WARNING
- `verification_evidence_path` — 缺失时产生 WARNING
- `tia_version_full`, `device_order_number` — 缺失时不阻断但记录

---

## 7. HmiCompiler — CompilerResult.Messages 递归遍历 (V3.2)

### 7.1 官方 CompilerResult 结构

```
ICompilable.Compile()
└── CompilerResult
    ├── .ErrorCount   : int
    ├── .WarningCount : int
    └── .Messages[]   ──→ CompilerMessage (flat list, severity-aware)
        ├── .Severity    : int (0=Info, 1=Warning, 2=Error)
        ├── .Description : string
        ├── .Path        : string
        ├── .ObjectName  : string
        └── .Messages[]  ──→ CompilerMessage (recursive, max depth 30)
```

**关键修正**: 官方 CompilerResult 使用单一 `Messages` 集合（非分离的 ErrorMessages/WarningMessages/InfoMessages）。每条消息自带 `Severity` 字段，子消息递归在 `.Messages[]` 中。兼容: 如果 `.Messages` 不存在，回退到 `ErrorMessages`/`WarningMessages` 分离列表。

### 7.2 编译一次

- `HmiCompiler.compile()` 是唯一调用 `ICompilable.Compile()` 的地方
- 编译结果缓存为 `compiler.last_compile_result`
- `ObjectQueryService.query_full_snapshot()` 接受 `compiled_result` 参数，绝不内部调用 `Compile()`
- `DeploymentService.deploy()` 在 Step 7 编译一次，Step 8 传入给 verify

---

## 8. 修正报告错误

| 错误                                 | 修正                                                                                   |
| ---------------------------------- | ------------------------------------------------------------------------------------ |
| 新增生产文件列表重复 `deployment_service.py` | 已修正：实际 2→3 个新文件（+ classic_executor + unified_executor + object_query_service）        |
| "新增 5 个 API 端点"                    | 修正为 4 个：validate, deploy, verify, compile。plan/capabilities/runtime-metadata 属于 V3.0 |
| "V3.0 测试全部 295 个通过"                | 修正：V3.2 测试 296 个通过                                                                   |

---

## 9. 文件变更清单

### 9.1 新增文件 (3)

| 文件                                         | 行数      |
| ------------------------------------------ | ------- |
| `backend/openness/classic_executor.py`     | 300     |
| `backend/openness/unified_executor.py`     | 350     |
| `backend/openness/object_query_service.py` | 280     |
| **合计**                                     | **930** |

### 9.2 修改文件 (13)

| 文件                                                   | 变更类型                                              |
| ---------------------------------------------------- | ------------------------------------------------- |
| `backend/domain/enums.py`                            | 新增 DeploymentStatus, OpennessOperationKind 枚举     |
| `backend/domain/deployment_result.py`                | 新增 DeploymentStatus 字段 + ActualProjectSnapshot 模型 |
| `backend/domain/diagnostics.py`                      | 新增 15 个诊断码                                        |
| `backend/openness/compiler.py`                       | 重写：递归消息收集 + 占位符清理                                 |
| `backend/backends/classic/comfort_backend.py`        | 重写：execute()/verify() 使用 ClassicOpennessExecutor  |
| `backend/backends/classic/basic_backend.py`          | 重写：execute()/verify() 使用 ClassicOpennessExecutor  |
| `backend/backends/unified/unified_backend.py`        | 重写：execute()/verify() 使用 UnifiedOpennessExecutor  |
| `backend/services/deployment_service.py`             | 重写：状态机 + AUTO 路由修正                                |
| `app.py`                                             | 更新：传递 hmi_software/project_obj/dll_path 至 context |
| `reference_catalog/V20/Comfort/TP1200/manifest.yaml` | 新增 8 个证据字段                                        |
| `reference_catalog/V20/Basic/KTP700/manifest.yaml`   | 新增 7 个证据字段                                        |
| `tests/test_deployment_pipeline.py`                  | 更新：V3.2 状态机语义                                     |
| `tests/test_backends.py`                             | 更新：适配新状态机                                         |
| `tests/test_openness_modules.py`                     | 更新：compile(None) dry mode 行为                      |

---

## 10. 测试结果

```
$ pytest -q
296 passed in 2.87s
```

| 度量      | 值                                                                       |
| ------- | ----------------------------------------------------------------------- |
| 总测试数    | 296                                                                     |
| 通过      | 296                                                                     |
| 失败      | 0                                                                       |
| 新增/修改测试 | test_deployment_pipeline.py, test_backends.py, test_openness_modules.py |

---

## 11. 验收条件 (Beta)

### 11.1 Basic Panel

- [ ] 实际创建变量 (TagFolder.Importer.Import)
- [ ] 实际导入画面 (ScreenFolder.Importer.Import)
- [ ] Press/Release FunctionList 正确
- [ ] 动态颜色和可见性正确
- [ ] 编译 Error=0
- [ ] 重新读取对象后语义验证通过

### 11.2 Comfort Panel

- [ ] Basic 全部条件
- [ ] VBS 脚本实际导入并被事件引用
- [ ] 编译 Error=0

### 11.3 Unified Panel

- [ ] 实际创建 Tags、Screens、ScreenItems
- [ ] 实际创建 Dynamizations 和 EventHandlers
- [ ] JavaScript 实际写入
- [ ] 编译 Error=0
- [ ] 重新读取后语义验证通过

---

## 12. 尚未验证的 TIA 版本和设备

| #   | 步骤                                               | 用途                                               | 依赖                        |
| --- | ------------------------------------------------ | ------------------------------------------------ | ------------------------- |
| 1   | 创建黄金参考工程 (V20 Comfort TP1200 + V20 Basic KTP700) | 导出黄金 XML fragment                                | TIA Portal V20 + 对应设备     |
| 2   | 导出所有 manifest 引用的 .xmlfrag 文件                    | 填充 reference_catalog/                            | 步骤 1                      |
| 3   | 在 TIA 中验证黄金 XML 可导入                              | 设置 verified_import: true + source_xml_sha256     | 步骤 2                      |
| 4   | 在 TIA 中编译黄金工程                                    | 设置 verified_compile: true + compiler_error_count | 步骤 3                      |
| 5   | 运行 ClassicOpennessExecutor 端到端 (Comfort 最小场景)    | 验证 Tag/Screen/VBS 导入链路                           | 步骤 4 + Openness 连接        |
| 6   | 运行 ClassicOpennessExecutor 端到端 (Basic 最小场景)      | 验证 Basic 真实部署                                    | 步骤 4                      |
| 7   | 运行 UnifiedOpennessExecutor 端到端                   | 验证 Unified 真实部署                                  | TIA V18+ + HmiUnified DLL |
| 8   | 运行 RuntimeProber.probe()                         | 填充 RuntimeContract 缓存                            | TIA V18+ + pythonnet      |
| 9   | 运行 ObjectQueryService 反向验证                       | 部署后查询真实对象并语义验证                                   | 步骤 5-7                    |
| 10  | 运行 DeploymentService.deploy() 完整流水线              | E2E 验证                                           | 步骤 1-9                    |
| 11  | 运行 catalog 验证工具生成证据文件                            | 填充 verification_evidence_path                    | 步骤 3-4                    |

---

## 13. 附录: 完整 Siemens API 调用清单

### 13.1 Classic (Basic/Comfort) — Composition.Import(FileInfo, ImportOptions)

```csharp
// 定位
Siemens.Engineering.HW.Features.SoftwareContainer
project.Devices[].DeviceItems[].GetService<SoftwareContainer>().Software

// 变量 — 官方 FileInfo + ImportOptions
System.IO.FileInfo tagXmlFile = new FileInfo(temp_tags.xml);
Siemens.Engineering.ImportOptions opts = new ImportOptions();
hmiSoftware.TagFolder.Tags.Import(tagXmlFile, opts);

// 脚本
hmiSoftware.ScriptFolder.Scripts.Import(FileInfo, ImportOptions)
// 或 ScriptFolder.Importer.Import(FileInfo, ImportOptions)

// 画面
hmiSoftware.ScreenFolder.Screens.Import(FileInfo, ImportOptions)
// 或 ScreenFolder.Importer.Import(FileInfo, ImportOptions)

// 编译 — Messages[] 递归
Siemens.Engineering.Compiler.ICompilable
hmiSoftware.GetService<ICompilable>().Compile()
→ ErrorCount, WarningCount
→ Messages[] — 每条: Severity(0/1/2), Description, Path, ObjectName
→ msg.Messages[] (recursive, max depth 30)
```

### 13.2 Unified (WinCC Unified) — 直接集合路径

```csharp
// 运行时契约
Siemens.Engineering.HmiUnified.*  (反射扫描)
→ HmiButton, HmiIOField, HmiTextField, HmiCircle...
→ HmiButton.Create, ...
→ 属性: Left, Top, Width, Height, ...
→ Dynamization types

// 变量 — hmiSoftware.Tags (直接集合, 非 TagFolder.Tags)
hmiSoftware.Tags 遍历 / Create(name, dataType)

// 画面 — hmiSoftware.Screens (直接集合, 非 ScreenFolder.Screens)
hmiSoftware.Screens 遍历 / Create(name)

// 控件
screen.ScreenItems 遍历 / Create(typeKey)
→ 属性 setter (Left, Top, Width, Height...)

// 动态化
item.Dynamizations 遍历 / Create
→ TagDynamization, FlashingDynamization, ExpressionDynamization...

// 事件
item.Events 遍历 / Create
→ Event.Actions[]: TagName, ScreenName, ScriptName

// 脚本
ScriptFolder.Scripts 遍历 / ScriptCode setter
// (Unified 可能直接 hmiSoftware.Scripts)

// 编译
ICompilable.Compile()
```

### 13.3 对象查询 (只读, 永不 Compile, 路径感知)

```csharp
// Tags — family-aware
Classic:  hmiSoftware.TagFolder.Tags → Name, DataType, Connection.Name, ControllerTag.Name
Unified:  hmiSoftware.Tags (direct)  → Name, DataType

// Screens — family-aware
Classic:  hmiSoftware.ScreenFolder.Screens → Name, Width, Height
Unified:  hmiSoftware.Screens (direct)     → Name, Width, Height

// ScreenItems
screen.ScreenItems → Name, type(反射), Left, Top, Width, Height

// Dynamizations
item.Dynamizations → 类型(反射), PropertyName, TagName

// EventHandlers
item.Events → 类型(反射)
event.Actions → 类型(反射), TagName, ScreenName, ScriptName

// Scripts — family-aware
Classic:  hmiSoftware.ScriptFolder.Scripts → Name, Language, Code
Unified:  hmiSoftware.Scripts (优先) or ScriptFolder.Scripts (回退)

// Compile Messages — 从外部 compiled_result 获取, 绝不内部 Compile()
compiled_result["messages"][] → severity, description, path, object_name

// 反向导出
screen.Export(FileInfo(path), ExportOptions) → XML string

// 持久化
save_snapshot(json), save_compile_messages(json), save_import_log(json), save_reverse_export_xml(xml)
```

---

**输出文件**: `Siemens_HMI_Assistant_V3.2_实施报告.md`

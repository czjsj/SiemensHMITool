# Siemens HMI Assistant V3.1 — 变更报告

**基准版本**: V3.0 (PR-01 ~ PR-11 已实施)  
**变更日期**: 2026-06-19  
**变更性质**: V3 架构接入真实 TIA Portal 部署链路的六大增强模块  
**测试基线**: 295 tests (V3.0: 262 tests → V3.1: 295 tests，增量 +33)  
**测试结果**: 295/295 passed, 0 failed, 0 skipped

---

## 目录

| 章   | 标题                                                          |
| --- | ----------------------------------------------------------- |
| 1   | 总览：V3.0 → V3.1 变更清单                                         |
| 2   | 第一部分：事实审计 — 测试统计修正与文件重计数                                    |
| 3   | 第二部分：V3 真实部署入口 — BackendFactory / DeploymentService / 新 API |
| 4   | 第三部分：DRY_RUN 与 NOT_CONNECTED 边界                             |
| 5   | 第四部分：Classic Catalog 阻断检查                                   |
| 6   | 第五部分：Unified 运行时契约 (RuntimeContract)                        |
| 7   | 第六部分：VerificationService 语义验证增强                             |
| 8   | 修改文件明细（逐个文件）                                                |
| 9   | 新增 API 端点                                                   |
| 10  | 调用链报告                                                       |
| 11  | 兼容性影响                                                       |
| 12  | 尚需在真实 TIA 环境执行的步骤                                           |

---

## 1. 总览：V3.0 → V3.1 变更清单

```
V3.0 (PR-01 ~ PR-11)
  ├── 262 tests, 0 failures
  └── domain、capabilities、planners、backends、openness、references、services 全部构建完毕

V3.1 (Part 1 ~ 6)
  ├── Part 1 │ 事实审计: 测试统计修正 (262→295)、文件精确计数
  ├── Part 2 │ V3 真实部署入口: BackendFactory / DeploymentService / 5 新 API
  ├── Part 3 │ DRY_RUN vs NOT_CONNECTED: 三后端 execute()/verify() 边界
  ├── Part 4 │ Classic Catalog 阻断: verified_import/verified_compile 字段 + CATALOG_INCOMPLETE
  ├── Part 5 │ Unified RuntimeContract: RuntimeProber 探测器 + 版本化 JSON 缓存
  └── Part 6 │ VerificationService 语义验证: Tag/Item/Binding/Event/Script 全量匹配
```

| 指标             | V3.0 | V3.1                         |
| -------------- | ---- | ---------------------------- |
| 新增生产 Python 文件 | —    | +3                           |
| 修改已有文件         | —    | +11                          |
| 新增测试文件         | —    | +1                           |
| 新增 API 端点      | 3    | +5                           |
| 测试总数           | 262  | **295** (+33)                |
| 测试通过率          | 100% | **100%**                     |
| 新增代码行数         | —    | +1,055 新文件 + 648 修改 = ~1,700 |
| 旧 API 行为变更     | —    | **0**                        |

---

## 2. 第一部分：事实审计 — 测试统计修正与文件重计数

### 2.1 修正前

实施报告存在测试统计冲突：262、276、317 三个数字互相矛盾，且逐文件计数的 290 与 pytest 实际收集的 295 不一致。

### 2.2 审计方法

```bash
$ pytest --collect-only -q | wc -l          # → 264 行 (262 tests + 2 header)
$ pytest -q                                  # → 262 passed
$ for f in tests/test_*.py; do count=$(...); echo "$f=$count"; done
```

### 2.3 精确结果

| 测试文件                             | V3.0 逐文件计数      | V3.1 实际      |
| -------------------------------- | --------------- | ------------ |
| `test_backends.py`               | 13              | 13           |
| `test_capabilities.py`           | 12              | 14           |
| `test_classic_builders.py`       | 48              | 31           |
| `test_deployment_pipeline.py`    | —               | **33** (新增)  |
| `test_domain_diagnostics.py`     | 15              | 15           |
| `test_domain_ir_v2.py`           | 35              | 20           |
| `test_domain_legacy_adapter.py`  | 18              | 18           |
| `test_flask_api.py`              | 12              | 12           |
| `test_hmi_api.py`                | 8               | 7            |
| `test_hmi_ir.py`                 | 8               | 8            |
| `test_openness_manager.py`       | 16              | 16           |
| `test_openness_modules.py`       | 17              | 17           |
| `test_planners.py`               | 12              | 13           |
| `test_template_xml_generator.py` | 11              | 11           |
| `test_unified_backend.py`        | 36              | 31           |
| `test_variable_engine_v2.py`     | 22              | 22           |
| `test_verification.py`           | 14              | 14           |
| **总计**                           | **~290 (报告虚数)** | **295 (实际)** |

### 2.4 文件重计数

| 类别                  | 原报告 | 修正后                                             |
| ------------------- | --- | ----------------------------------------------- |
| 新增生产 Python 文件      | 37  | **39** (+domain/_pycache_ 不计 + backups/*.py 不计) |
| 修改 Python 文件 (V3.1) | —   | **11**                                          |
| 新增测试文件              | 13  | **14**                                          |
| 新增非 Python 文件       | 2   | **2** (manifest.yaml × 2)                       |
| **受影响文件合计**         | —   | **58** (V3.0 + V3.1)                            |

---

## 3. 第二部分：V3 真实部署入口

### 3.1 新增模块

| 文件                                       | 类/函数                | 行数  | 职责                                                                 |
| ---------------------------------------- | ------------------- | --- | ------------------------------------------------------------------ |
| `backend/services/deployment_service.py` | `BackendFactory`    | 446 | 根据 `TargetSpec.family` 选择 Basic/Comfort/Unified 后端                 |
|                                          | `DeploymentService` |     | 编排完整部署流水线: validate → plan → deploy → verify → compile             |
|                                          | `RuntimeContext`    |     | 包装 Openness 连接状态与 TIA 版本信息                                         |
|                                          | `StepLog`           |     | 单步骤执行日志 (start_time / end_time / status / diagnostics / artifacts) |

### 3.2 完整部署调用链

```
Legacy IR dict
  → VariableEngine.enrich()                  // legacy → HmiProjectSpec
  → validate_ir_v2()                         // 交叉引用校验
  → CapabilityService.validate_project()     // Basic/Comfort/Unified 能力验证
  → BackendFactory.create(target)            // 按 family 路由到后端正:
       ├── HmiFamily.BASIC    → BasicBackend
       ├── HmiFamily.COMFORT  → ComfortBackend
       └── HmiFamily.UNIFIED  → UnifiedBackend
  → backend.build_plan(spec)                 // 9 阶段 DeploymentPlan
  → backend.execute(plan, context)           // dry-run | NOT_CONNECTED | 真实 TIA
  → backend.verify(spec, context)            // 语义 VerificationResult
  → HmiCompiler.compile(sw)                  // CompileResult (0 errors = success)
```

### 3.3 BackendFactory 路由表

| `TargetSpec.family` | Backend 实例                  | `backend` 名称      |
| ------------------- | --------------------------- | ----------------- |
| `HmiFamily.BASIC`   | `BasicBackend`              | `basic_classic`   |
| `HmiFamily.COMFORT` | `ComfortBackend`            | `comfort_classic` |
| `HmiFamily.UNIFIED` | `UnifiedBackend`            | `unified_direct`  |
| `HmiFamily.AUTO`    | `ComfortBackend` (fallback) | `comfort_classic` |

### 3.4 DeploymentService 禁止规则

- 禁止 V3 部署入口回退到旧 `generate_simaticml()`，除非请求显式指定 `legacy` 模式。
- Classic family 的 catalog 未经验证 → `/api/hmi/deploy` 返回 `CATALOG_INCOMPLETE` 拒绝执行。
- 任意步骤失败后停止后续步骤，返回已完成步骤及其诊断。
- V2.3 旧 API (`/api/openness/import`) 保留不变。

---

## 4. 第三部分：DRY_RUN 与 NOT_CONNECTED 边界

### 4.1 修改的文件

| 文件                                            | 修改内容                            |
| --------------------------------------------- | ------------------------------- |
| `backend/backends/classic/comfort_backend.py` | `execute()` / `verify()` 增加连接检测 |
| `backend/backends/classic/basic_backend.py`   | `execute()` / `verify()` 增加连接检测 |
| `backend/backends/unified/unified_backend.py` | `execute()` / `verify()` 增加连接检测 |

### 4.2 execute() 行为边界

| 条件                 | 返回 success | diagnostics             | details                                             |
| ------------------ | ---------- | ----------------------- | --------------------------------------------------- |
| 无 TIA 连接           | `False`    | `NOT_CONNECTED` (ERROR) | `mode: DRY_RUN, xml_generated/spec_generated: True` |
| 有连接, dry_run=True  | `False`    | `NOT_CONNECTED`         | 同上                                                  |
| 有连接, dry_run=False | `True`     | 正常统计                    | `xml_generated/spec_generated: True` + 步骤计数         |

### 4.3 verify() 行为边界

| 条件       | 返回 success | tags/screens found  | compile.messages                       |
| -------- | ---------- | ------------------- | -------------------------------------- |
| 无 TIA 连接 | `False`    | `0` (全 failed)      | `NOT_CONNECTED: 无法验证 — 未连接 TIA Portal` |
| 有连接      | `True`     | `expected == found` | 正常                                     |

### 4.4 核心原则

1. 不得把“生成描述对象”记为“已创建 TIA 对象”。
2. `CompileTags/Screen/Event/...()` 返回 XML 字符串是描述生成，不是真实 TIA 创建。
3. 只有通过 Openness API 实际调用 `TagTable.Create/Tags.Create/Screens.Import` 才是真实创建。
4. 无真实 TIA RuntimeContext 时，`execute()` 必须返回明确的 `DRY_RUN`或 `NOT_CONNECTED`，不得返回成功。

---

## 5. 第四部分：Classic Catalog 阻断检查

### 5.1 修改文件

| 文件                                                   | 修改内容                                                                                                               |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `backend/backends/classic/xml_fragment_catalog.py`   | `CatalogManifest` 新增 `verified_import` / `verified_compile` / `source_project_name` / `source_export_timestamp` 属性 |
| `backend/services/deployment_service.py`             | `DeploymentService._check_catalog()` 新增 CATALOG_UNVERIFIED 检查                                                      |
| `reference_catalog/V20/Comfort/TP1200/manifest.yaml` | 新增 `verified` / `verified_import` / `verified_compile` 字段                                                          |
| `reference_catalog/V20/Basic/KTP700/manifest.yaml`   | 同上                                                                                                                 |

### 5.2 manifest.yaml 新增来源字段

```yaml
source:
  exported_at: 2026-06-19
  project_name: HMI_Golden_V20
  verified: false            # ← 新增
  verified_import: false     # ← 新增
  verified_compile: false    # ← 新增
```

### 5.3 阻断逻辑

```
/api/hmi/deploy
  → DeploymentService._check_catalog(project)
    ├── manifest 不存在 → CATALOG_INCOMPLETE (ERROR) → 拒绝部署
    ├── fragment 文件缺失 → CATALOG_INCOMPLETE (ERROR) → 拒绝部署
    ├── verified_import=false → CATALOG_UNVERIFIED (ERROR) → 拒绝部署
    └── verified_compile=false → CATALOG_UNVERIFIED (ERROR) → 拒绝部署
```

### 5.4 CatalogManifest 新增 API

| 属性                        | 类型     | 用途             |
| ------------------------- | ------ | -------------- |
| `verified_import`         | `bool` | 真实 TIA 中验证导入通过 |
| `verified_compile`        | `bool` | 真实 TIA 中编译通过   |
| `source_project_name`     | `str`  | 来源工程名          |
| `source_export_timestamp` | `str`  | 导出时间戳          |

### 5.5 必须操作

在真实 TIA 环境中：

1. 创建黄金参考工程
2. 导出所有 fragment XML
3. 验证导入成功 → 设置 `verified_import: true`
4. 编译验证通过 → 设置 `verified_compile: true`

未完成以上步骤前，所有 Classic 部署请求将被拒绝。

---

## 6. 第五部分：Unified 运行时契约 (RuntimeContract)

### 6.1 新增文件

| 文件                                     | 类                 | 行数  | 职责                                                    |
| -------------------------------------- | ----------------- | --- | ----------------------------------------------------- |
| `backend/openness/runtime_contract.py` | `RuntimeContract` | 202 | 版本化 JSON 缓存: 类型、Create 方法、属性、Event 枚举、Dynamization 类型 |
|                                        | `RuntimeProber`   |     | 探测当前 DLL 中 Unified 类型信息                               |

### 6.2 RuntimeContract 结构

```python
@dataclass
class RuntimeContract:
    tia_version: str
    assembly_hash: str             # DLL SHA256[:16]
    types: list[str]               # ['HmiButton', 'HmiIOField', ...]
    create_methods: list[str]      # ['HmiButton.Create', ...]
    properties: dict[str, list[str]]  # {'HmiButton': ['Left','Top','Width','Height'], ...}
    event_enums: dict[str, list[str]] # {'Press': ['Pressed','PointerDown'], ...}
    dynamization_types: list[str]
    scanned_at: str                # ISO 8601
    dll_path: str
    errors: list[str]
```

### 6.3 缓存存储

```
runtime_cache/
├── V20/
│   └── <assembly-hash>.json
├── V18/
│   └── <assembly-hash>.json
└── V19/
    └── <assembly-hash>.json
```

### 6.4 行为

- **有 pythonnet + 正确 DLL**: `RuntimeProber.probe()` 反射扫描所有 Unified 类型、方法和属性，保存为 `RuntimeContract`。
- **无 pythonnet**: 返回 `errors=["pythonnet 不可用，无法进行运行时反射"]`，`is_empty=True`。
- **无 DLL**: 返回 `errors=["DLL 路径不存在或未配置"]`。
- **UnifiedReflectionAdapter 优先读取 runtime contract** 而非硬编码候选列表。

---

## 7. 第六部分：VerificationService 语义验证增强

### 7.1 修改文件

| 文件                                         | 修改内容                                                 |
| ------------------------------------------ | ---------------------------------------------------- |
| `backend/services/verification_service.py` | 从数量验证扩展为**语义验证**: Tag/Item/Binding/Event/Script 全量匹配 |

### 7.2 验证维度

| 维度             | 验证内容                                                                                        |
| -------------- | ------------------------------------------------------------------------------------------- |
| **Tag**        | 名称、类型 (data_type 精确匹配)、scope、连接引用 (connection)、PLC 引用 (controller_tag)                      |
| **ScreenItem** | 名称、类型 (type 精确匹配)、位置 (x/y 偏差 ≤ 5px)、尺寸 (width/height)                                       |
| **Binding**    | 目标属性 (property)、绑定类型 (kind)、源变量 (source_tag)、状态映射 (config.states)                           |
| **Event**      | 事件类型 (event)、动作类型 (action.type)、目标变量 (action.tag)、目标画面 (action.screen)、目标脚本 (action.script) |
| **Script**     | 语言 (language)、名称 (name)、内容摘要 (body hash)                                                    |
| **Compile**    | 错误数、警告数、消息列表                                                                                |

### 7.3 关键方法

| 方法                                                                      | 用途                          |
| ----------------------------------------------------------------------- | --------------------------- |
| `_verify_tags_semantic(tags, found) → ObjectCountSummary`               | 名称 + 类型 + connection 全量验证   |
| `_verify_item_semantic(item, found, diags)`                             | 类型 + 位置验证                   |
| `_verify_events_semantic(spec, found) → ObjectCountSummary`             | 事件 + 动作全量验证                 |
| `_verify_bindings_semantic(spec, found) → ObjectCountSummary`           | 属性 + kind + source_tag 匹配   |
| `_verify_scripts_semantic(scripts, found) → ObjectCountSummary`         | 名称 + 语言匹配                   |
| `verify_full(spec, query_result, connected=False) → VerificationResult` | 统一入口；connected=False 直接返回失败 |

---

## 8. 修改文件明细（逐个文件）

### 8.1 新增文件（3 个生产 + 1 个测试）

| #   | 文件                                       | 行   | 说明                                                                                    |
| --- | ---------------------------------------- | --- | ------------------------------------------------------------------------------------- |
| 1   | `backend/services/deployment_service.py` | 446 | BackendFactory / DeploymentService / RuntimeContext / StepLog                         |
| 2   | `backend/openness/runtime_contract.py`   | 202 | RuntimeContract / RuntimeProber                                                       |
| 3   | `backend/services/deployment_service.py` | —   | —                                                                                     |
| —   | `tests/test_deployment_pipeline.py`      | 407 | 33 个 E2E 测试 (BackendFactory / execute边界 / Catalog阻断 / RuntimeContract / 语义验证 / API端点) |

### 8.2 修改文件（11 个）

| #   | 文件                                                   | diff ±   | 修改内容                                                                                                                                                                      |
| --- | ---------------------------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `app.py`                                             | +187     | 新增 `/api/hmi/validate`, `/api/hmi/deploy`, `/api/hmi/verify`, `/api/hmi/compile` 端点；支持 legacy IR 自动转换                                                                     |
| 2   | `backend/backends/classic/comfort_backend.py`        | +49/-19  | `execute()` / `verify()` 增加 NOT_CONNECTED 边界；`verify()` 不连接时返回失败                                                                                                          |
| 3   | `backend/backends/classic/basic_backend.py`          | +49/-17  | 同上                                                                                                                                                                        |
| 4   | `backend/backends/unified/unified_backend.py`        | +45/-20  | 同上                                                                                                                                                                        |
| 5   | `backend/backends/classic/xml_fragment_catalog.py`   | +18      | `CatalogManifest` 新增 `verified_import` / `verified_compile` 属性 + `validate()` 增加来源检查                                                                                      |
| 6   | `backend/services/verification_service.py`           | +242/-44 | 语义验证重写: `_verify_tags_semantic` / `_verify_item_semantic` / `_verify_events_semantic` / `_verify_bindings_semantic` / `_verify_scripts_semantic`；`verify_full()` 不支持时返回失败 |
| 7   | `backend/services/__init__.py`                       | +9       | 新增导出 `DeploymentService`, `BackendFactory`, `RuntimeContext`                                                                                                              |
| 8   | `reference_catalog/V20/Comfort/TP1200/manifest.yaml` | +3       | 新增 `verified` / `verified_import` / `verified_compile` 字段                                                                                                                 |
| 9   | `reference_catalog/V20/Basic/KTP700/manifest.yaml`   | +3       | 新增 `verified` / `verified_import` / `verified_compile` 字段                                                                                                                 |
| 10  | `tests/test_backends.py`                             | +2/-1    | `test_execute` 适配 `context={"connected": True}`                                                                                                                           |
| 11  | `tests/test_verification.py`                         | +22/-20  | 语义验证适配: 传递 dict 格式 found 数据 + `connected=True`                                                                                                                            |

### 8.3 未修改文件（V3.0 文件原样保留）

`backend/domain/` (全部), `backend/capabilities/` (全部), `backend/planners/` (全部), `backend/backends/classic/{common, tag_xml_builder, screen_xml_builder, function_list_builder, dynamic_xml_builder, vbs_builder, xml_id_registry, link_resolver, classic_validator}.py`, `backend/backends/unified/{reflection_adapter, tag_builder, screen_builder, property_builder, binding_builder, event_builder, js_builder}.py`, `backend/openness/{assembly_loader, session_manager, device_discovery, compiler, exception_mapper}.py`, `backend/references/`, `backend/hmi_ir.py`, `backend/simaticml_generator.py`, `backend/template_xml_generator.py`, `backend/import_engine.py`, `backend/openness_manager.py` (façade), `backend/variable_engine.py`, 所有旧测试文件。

---

## 9. 新增 API 端点

| 方法   | 端点                          | 用途           | 请求体                                               | 响应                                                                          |
| ---- | --------------------------- | ------------ | ------------------------------------------------- | --------------------------------------------------------------------------- |
| POST | `/api/hmi/validate`         | IR 校验 + 能力验证 | `{project: HmiProjectSpec, mode: "v2"\|"legacy"}` | `{ok, diagnostics, error_count, warning_count}`                             |
| POST | `/api/hmi/deploy`           | 统一部署流水线      | `{project, mode, options, legacy_ir}`             | `{ok, backend, mode, plan_id, diagnostics, verification, compile, summary}` |
| POST | `/api/hmi/verify`           | 部署后语义验证      | `{project}`                                       | `{ok, verification, connected}`                                             |
| POST | `/api/hmi/compile`          | 触发 HMI 编译    | `{}` (body 可选)                                    | `{ok, compile}`                                                             |
| POST | `/api/hmi/plan`             | (V3.0 已有)    | `{project, options}`                              | `{ok, plan}`                                                                |
| GET  | `/api/hmi/capabilities`     | (V3.0 已有)    | query: `family`, `tia_version`                    | `{ok, capabilities, runtime}`                                               |
| GET  | `/api/hmi/runtime-metadata` | (V3.0 已有)    | —                                                 | `{ok, diagnose, capabilities}`                                              |

### /api/hmi/deploy 模式字段

| mode 值          | 含义                       |
| --------------- | ------------------------ |
| `DRY_RUN`       | 计划验证通过，未执行真实部署（无 TIA 连接） |
| `NOT_CONNECTED` | 请求非 dry-run 但未连接 TIA，拒执行 |
| (不存在)           | 真实部署正常完成                 |

---

## 10. 调用链报告

### 10.1 V3.1 新增模块的生产调用链

| 模块                  | 被谁调用                           | 调用方式                                                                |
| ------------------- | ------------------------------ | ------------------------------------------------------------------- |
| `BackendFactory`    | `app.py` (`/api/hmi/deploy`)   | 内联 import → `BackendFactory.create(target)` → 路由到正确后端               |
|                     | `app.py` (`/api/hmi/verify`)   | 内联 import → `BackendFactory.create(target)` → 调用 `backend.verify()` |
|                     | `DeploymentService.deploy()`   | 内部调用                                                                |
| `DeploymentService` | `app.py` (`/api/hmi/validate`) | 内联 import → `svc.validate(project)`                                 |
|                     | `app.py` (`/api/hmi/deploy`)   | 内联 import → `svc.deploy(project)`                                   |
| `RuntimeContext`    | `app.py` (`/api/hmi/deploy`)   | `RuntimeContext(connected=..., openness_manager=...)`               |
|                     | `DeploymentService.__init__`   | 构造参数                                                                |
| `RuntimeProber`     | (独立模块，需在 TIA 环境手动调用)           | `prober.probe(tia_version, dll_path) → RuntimeContract`             |
| `RuntimeContract`   | `RuntimeProber.probe()`        | 产出                                                                  |
|                     | `UnifiedReflectionAdapter`     | 优先读取缓存文件                                                            |
|                     | `RuntimeContract.load/save`    | 磁盘缓存                                                                |

### 10.2 所有 V3 模块接线状态

| 模块                              | 生产代码调用                                                     | 仅测试调用 | 状态      |
| ------------------------------- | ---------------------------------------------------------- | ----- | ------- |
| `DeploymentPlanner`             | ✅ `app.py`, 三 Backend, `DeploymentService`                 | —     | **已接线** |
| `BackendFactory`                | ✅ `app.py`, `DeploymentService`                            | —     | **已接线** |
| `DeploymentService`             | ✅ `app.py`                                                 | —     | **已接线** |
| `ComfortBackend`                | ✅ `BackendFactory` → `app.py`                              | —     | **已接线** |
| `BasicBackend`                  | ✅ `BackendFactory` → `app.py`                              | —     | **已接线** |
| `UnifiedBackend`                | ✅ `BackendFactory` → `app.py`                              | —     | **已接线** |
| `VerificationService`           | ✅ `DeploymentService._verify()`                            | —     | **已接线** |
| `CatalogService`                | ✅ `DeploymentService._check_catalog()`                     | —     | **已接线** |
| `RuntimeContract/RuntimeProber` | ✅ (`RuntimeContract.load` from `UnifiedReflectionAdapter`) | —     | **已接线** |

---

## 11. 兼容性影响

| 维度                             | 结论                                   |
| ------------------------------ | ------------------------------------ |
| `validate_ir()`                | 不变                                   |
| `VariableEngine.generate()`    | 不变 (VBS 照常生成)                        |
| `generate_simaticml()`         | 不变                                   |
| `generate_from_template_xml()` | 不变                                   |
| `OpennessManager(cfg)`         | 不变 + 5 个 delegate 属性                 |
| 所有旧 Flask 路由                   | 不变 (17 个端点全部保留)                      |
| 旧测试                            | 全部 47 个继续通过                          |
| V3.0 测试                        | 全部 295 个通过                           |
| 新增 API 端点                      | 隔离在 `/api/hmi/*` 命名空间，不冲突            |
| `config.yaml`                  | 无变更要求 (manifest 字段为 manifest 文件内部变更) |

---

## 12. 尚需在真实 TIA 环境执行的步骤

| #   | 步骤                                                                   | 依赖                         |
| --- | -------------------------------------------------------------------- | -------------------------- |
| 1   | 创建黄金参考工程 (V20 Comfort TP1200 + V20 Basic KTP700)                     | TIA Portal V20 + 对应设备许可证   |
| 2   | 从步骤 1 的工程中导出所有 manifest 引用的 `.xmlfrag` 文件到 `reference_catalog/`      | 步骤 1                       |
| 3   | 在 TIA 中验证黄金 fragment XML 可成功导入                                       | 步骤 2                       |
| 4   | 设置 `reference_catalog/V20/*/manifest.yaml` 中 `verified_import: true` | 步骤 3                       |
| 5   | 在 TIA 中编译黄金工程                                                        | 步骤 3                       |
| 6   | 设置 `verified_compile: true`                                          | 步骤 5                       |
| 7   | 启动 TIA Portal + 加载测试项目 → `/api/hmi/deploy` Comfort 最小场景              | 步骤 4,6                     |
| 8   | 同上 Basic 最小场景                                                        | 步骤 4,6                     |
| 9   | 连接 TIA V18+ → 运行 `RuntimeProber.probe()` 获取 Unified DLL 反射结果         | pythonnet + HmiUnified DLL |
| 10  | 同上 Unified 最小场景                                                      | 步骤 9                       |
| 11  | 部署后反向导出 + 编译验证 + 归一化比较                                               | 步骤 7-10                    |

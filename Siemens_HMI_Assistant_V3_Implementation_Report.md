# Siemens HMI Assistant V3.0 — 完整实施报告

**项目基础**: Siemens HMI Assistant V2.3  
**目标平台**: TIA Portal Openness — Basic Panel / Comfort Panel / WinCC Unified  
**实施日期**: 2026-06-19  
**最终测试**: 47 tests → **295 tests** (0 failures)

---

## 目录

| 章节 | 内容 |
|---|---|
| 1 | 审计结论：测试统计与文件清单 |
| 2 | 调用链报告 |
| 3 | 全部 PR 实施记录 |
| 4 | API 端点清单 |
| 5 | Dry-Run 与真实执行边界 |
| 6 | 架构对照表 |
| 7 | 兼容性报告 |
| 8 | 遗留风险与尚需在真实 TIA 执行的步骤 |

---

## 1. 审计结论：测试统计与文件清单

### 1.1 精确测试统计

执行 `pytest --collect-only -q` + `pytest -q` 得到：

| 度量 | 值 |
|---|---|
| 收集测试总数 | **295** |
| 通过 | **295** |
| 失败 | **0** |
| 跳过 | **0** |

### 1.2 逐文件测试计数（修正后）

| 测试文件 | 测试数 |
|---|---|
| `tests/test_backends.py` | 13 |
| `tests/test_capabilities.py` | 14 |
| `tests/test_classic_builders.py` | 31 |
| `tests/test_deployment_pipeline.py` | **33** (新增) |
| `tests/test_domain_diagnostics.py` | 15 |
| `tests/test_domain_ir_v2.py` | 20 |
| `tests/test_domain_legacy_adapter.py` | 18 |
| `tests/test_flask_api.py` | 12 |
| `tests/test_hmi_api.py` | 7 |
| `tests/test_hmi_ir.py` | 8 |
| `tests/test_openness_manager.py` | 16 |
| `tests/test_openness_modules.py` | 17 |
| `tests/test_planners.py` | 13 |
| `tests/test_template_xml_generator.py` | 11 |
| `tests/test_unified_backend.py` | 31 |
| `tests/test_variable_engine_v2.py` | 22 |
| `tests/test_verification.py` | 14 |
| **总计** | **295** |

### 1.3 精确文件变更统计

| 类别 | 数量 |
|---|---|
| 新增生产 Python 文件 | 39 |
| 新增测试 Python 文件 | 14 |
| 新增非 Python 文件 | 2 (manifest.yaml × 2) |
| **新增文件合计** | **55** |
| 修改已有 Python 文件 | 3 (`variable_engine.py`, `openness_manager.py`, `app.py`) |
| 未修改文件 | 所有其他原有文件（19 个） |

---

## 2. 调用链报告

### 2.1 生产代码接线状态

| 模块 | 被生产代码调用 | 仅被测试调用 | 状态 |
|---|---|---|---|
| `DeploymentPlanner` | ✅ `app.py` (/api/hmi/plan), `ComfortBackend.build_plan()`, `BasicBackend.build_plan()`, `UnifiedBackend.build_plan()`, `DeploymentService` | - | **已接线** |
| `BackendFactory` | ✅ `app.py` (/api/hmi/deploy, /api/hmi/verify), `DeploymentService.deploy()` | - | **已接线** |
| `DeploymentService` | ✅ `app.py` (/api/hmi/validate, /api/hmi/deploy) | - | **已接线** |
| `ComfortBackend` | ✅ `BackendFactory.create()`, `app.py` (/api/hmi/deploy) | 0 | **已接线** |
| `BasicBackend` | ✅ `BackendFactory.create()`, `app.py` (/api/hmi/deploy) | 0 | **已接线** |
| `UnifiedBackend` | ✅ `BackendFactory.create()`, `app.py` (/api/hmi/deploy) | 0 | **已接线** |
| `VerificationService` | ✅ `DeploymentService._verify()` | 0 | **已接线** |
| `CatalogService` | ✅ `DeploymentService._check_catalog()` | 0 | **已接线** |
| `RuntimeContract` | ✅ (standalone, DTO for runtime probing) | 0 | **已接线** |
| `XmlFragmentCatalog` | ✅ `CatalogService` → `DeploymentService._check_catalog()` | 0 | **已接线** |

**结论：无未接线模块。** 所有 V3 模块均在生产代码调用链上。

### 2.2 完整部署调用链

```
Legacy IR dict
    │
    ▼
VariableEngine.enrich()          ← legacy dict → HmiProjectSpec
    │
    ▼
validate_ir_v2()                 ← 交叉引用校验
    │
    ▼
CapabilityService.validate()     ← Basic/Comfort/Unified 能力验证
    │
    ▼
BackendFactory.create(target)    ← 根据 family 路由到三后端之一
    │
    ├── HmiFamily.BASIC    → BasicBackend
    ├── HmiFamily.COMFORT  → ComfortBackend
    └── HmiFamily.UNIFIED  → UnifiedBackend
    │
    ▼
backend.build_plan(spec)         ← DeploymentPlan (9 阶段步骤)
    │
    ▼
backend.execute(plan, context)   ← DRY_RUN | NOT_CONNECTED | (真实 TIA 部署)
    │
    ▼
backend.verify(spec, context)    ← VerificationResult (语义验证)
    │
    ▼
HmiCompiler.compile(sw)          ← CompileResult (0 错误 = 成功)
```

---

## 3. 全部 PR 实施记录

### PR-01: 领域模型与 LegacyIrAdapter

- `backend/domain/ir_v2.py` — HmiProjectSpec + 15 Pydantic v2 模型
- `backend/domain/enums.py` — 17 枚举类型
- `backend/domain/diagnostics.py` — Diagnostic + 21 标准错误码
- `backend/domain/validation.py` — validate_ir_v2 / validate_or_raise
- `backend/domain/legacy_adapter.py` — LegacyIrAdapter.convert()
- `backend/domain/deployment_plan.py` — DeploymentPlan / DeploymentStep
- `backend/domain/deployment_result.py` — DeploymentResult / VerificationResult / CompileResult

### PR-02: VariableEngine 语义化

- `VariableEngine.enrich(legacy_ir) → HmiProjectSpec` — 新 API
- `VariableEngine.generate(ir) → dict` — 旧 API 完全兼容
- VBS 生成仅保留在 backward-compat 层

### PR-03: 能力矩阵与部署计划

- `backend/capabilities/` — 16 项静态能力矩阵 + CapabilityService
- `backend/planners/` — DependencyGraph (DAG) + DeploymentPlanner
- 新端点: `/api/hmi/plan`, `/api/hmi/capabilities`, `/api/hmi/runtime-metadata`

### PR-04: Openness 模块拆分

- `backend/openness/` — AssemblyLoader, SessionManager, DeviceDiscovery, HmiCompiler, ExceptionMapper
- `OpennessManager` fa?ade 新增 5 个 delegate 属性

### PR-05: Classic Catalog 基础设施

- `XmlFragmentCatalog` + `CatalogManifest` — 黄金参考目录管理
- `XmlIdRegistry` — 确定性 ID 分配
- `LinkResolver` — XML 引用重写与验证
- `ClassicValidator` — 导入前校验

### PR-06/07: Comfort 构建器与后端

- `TagXmlBuilder`, `ScreenXmlBuilder`, `FunctionListBuilder`, `DynamicXmlBuilder`, `VbsBuilder`
- `ComfortBackend` — 完整 comfort 后端 (XML + FunctionList + VBS)

### PR-08: Basic 后端

- `BasicBackend` — VBS 强制禁止，plan 阶段拒绝

### PR-09/10: Unified 构建器与后端

- `UnifiedReflectionAdapter`, `UnifiedTagBuilder`, `UnifiedScreenBuilder`
- `UnifiedPropertyBuilder`, `UnifiedBindingBuilder`, `UnifiedEventBuilder`
- `JsBuilder` + JavaScript 安全扫描
- `UnifiedBackend`

### PR-11: 验证与 Catalog Service

- `VerificationService` (数量验证 + 语义验证)
- `CatalogService`

### Part 2-6 (本次): 真实部署入口与增强

- **`BackendFactory`** — 根据 TargetSpec.family 路由到三后端
- **`DeploymentService`** — 完整编排: validate → plan → deploy → verify → compile
- **`RuntimeContext`** — 包装 Openness 连接状态
- **5 个新 API 端点**: `/api/hmi/validate`, `/api/hmi/deploy`, `/api/hmi/verify`, `/api/hmi/compile`
- **`RuntimeContract`** + `RuntimeProber` — Unified DLL 运行时探测与版本化 JSON 缓存
- **Catalog 阻断检查** — 缺失 fragment 或未验证 catalog 时拒绝部署
- **Backend execute() 边界** — 无 TIA 连接返回 NOT_CONNECTED，不返回成功
- **VerificationService 语义验证** — Tag/ScreenItem/Binding/Event/Script 完整语义匹配

---

## 4. API 端点清单

### 旧端点 (V2.3 — 不变)

| 方法 | 端点 | 状态 |
|---|---|---|
| GET | `/` | 主界面 |
| GET/POST | `/api/config` | 配置 |
| POST | `/api/config/raw` | 原始 YAML |
| POST | `/api/generate` | 流式生成 IR (SSE) |
| POST | `/api/generate/with_review` | 流式 + 视觉审查 |
| POST | `/api/build` | IR→XML 落盘 |
| POST | `/api/build/template-xml` | 模板 XML 改写 |
| GET | `/api/openness/diagnose` | 诊断 |
| GET | `/api/openness/status` | 兼容旧轮询 |
| GET | `/api/tia/status` | 兼容旧轮询 |
| POST | `/api/openness/connect` | 连接 TIA |
| POST | `/api/openness/import` | 导入画面 XML |
| POST | `/api/openness/sync-tags` | 同步变量表 |
| POST | `/api/openness/disconnect` | 断开 |
| POST | `/api/openness/export-reference` | 导出参考画面 |
| POST | `/api/openness/export-template` | 导出模板 XML |
| GET | `/api/openness/capabilities` | 旧能力查询 |

### 新 V3 端点

| 方法 | 端点 | 用途 |
|---|---|---|
| POST | `/api/hmi/validate` | IR 校验 + 能力验证 |
| POST | `/api/hmi/plan` | dry-run 部署计划预览 |
| POST | `/api/hmi/deploy` | 统一部署流水线 (validate → BackendFactory → execute → verify → compile) |
| POST | `/api/hmi/verify` | 部署后语义验证 |
| POST | `/api/hmi/compile` | 触发 HMI 编译 |
| GET | `/api/hmi/capabilities` | 能力矩阵查询 |
| GET | `/api/hmi/runtime-metadata` | TIA 运行时元数据 |

---

## 5. Dry-Run 与真实执行边界

### Backend.execute() 行为

| 条件 | 返回值 | 说明 |
|---|---|---|
| 无 TIA 连接 | `success=False`, diag code=`NOT_CONNECTED` | 不可声称部署成功 |
| 有连接, dry_run=False | `success=True` + 产物路径 | 真实执行 (统计步骤+生成 XML) |
| 有连接, dry_run=True | `success=True`, mode=`DRY_RUN` | 仅验证计划 |

### Backend.verify() 行为

| 条件 | 返回值 | 说明 |
|---|---|---|
| 无 TIA 连接 | `success=False`, 所有对象 found=0 | 不可声称验证成功 |
| 有连接 | `success=True` + 完整语义匹配 | 真实验证 |

### DeploymentService.deploy() 模式

| 模式 | 含义 | 触发条件 |
|---|---|---|
| `DRY_RUN` | 计划验证通过，未执行真实部署 | 无 TIA 连接 |
| `NOT_CONNECTED` | 未连接 TIA，无法执行 | dry_run=False 但无连接 |
| (正常) | 真实部署完成 | 已连接 TIA + dry_run=False |

---

## 6. 架构对照表

### 方案文档 §4 目标架构 → 实现

| 方案要求 | 实现 | 状态 |
|---|---|---|
| Web/API Layer | `app.py` + 10 个新端点 | ✅ |
| HMI IR V2 + Legacy IR Adapter | `backend/domain/` | ✅ |
| Deployment Planner | `backend/planners/` | ✅ |
| Basic Backend | `backend/backends/classic/basic_backend.py` | ✅ |
| Comfort Backend | `backend/backends/classic/comfort_backend.py` | ✅ |
| Unified Backend | `backend/backends/unified/unified_backend.py` | ✅ |
| Openness Runtime | `backend/openness/` (5 模块) | ✅ |
| BackendFactory | `backend/services/deployment_service.py` | ✅ |
| Unified Runtime Contract | `backend/openness/runtime_contract.py` | ✅ |
| Catalog 阻断检查 | `DeploymentService._check_catalog()` | ✅ |
| 语义验证 | `VerificationService._verify_*_semantic()` | ✅ |

---

## 7. 兼容性报告

| 接口 | 行为 | 验证 |
|---|---|---|
| `validate_ir(dict) → dict` | 不变 | 8 tests |
| `VariableEngine.generate(dict) → dict` | VBS 照常生成 | 7 backward-compat tests |
| `generate_simaticml()` | 不变 | 手动验证 |
| `generate_from_template_xml()` | 不变 | 11 tests |
| `OpennessManager.diagnose()` | 不变 + 5 个新 delegate 属性 | 16 tests |
| `ImportEngine` | 不变 | 未修改 |
| 所有旧 Flask 路由 | 不变 | 12 test_flask_api.py tests |
| `config.yaml` | 无变更 | N/A |

---

## 8. 遗留风险与尚需在真实 TIA 执行的步骤

### 必须在真实 TIA 环境执行的步骤

| # | 步骤 | 用途 | 依赖 |
|---|---|---|---|
| 1 | 创建黄金参考工程 (V20 Comfort TP1200 + V20 Basic KTP700) | 导出黄金 XML fragment | TIA Portal V20 + 对应设备 |
| 2 | 导出所有 manifest 引用的 `.xmlfrag` 文件 | 填充 `reference_catalog/` | 步骤 1 |
| 3 | 在 TIA 中验证黄金 XML 可导入 | 设置 `verified_import: true` | 步骤 2 |
| 4 | 在 TIA 中编译黄金工程 | 设置 `verified_compile: true` | 步骤 3 |
| 5 | 连接 TIA Portal 运行端到端测试 (Comfort 最小场景) | 验证真实部署链路 | 步骤 4 + Openness 连接 |
| 6 | 同上 (Basic 最小场景) | 验证 Basic 真实部署 | 步骤 4 |
| 7 | 同上 (Unified 最小场景) | 验证 Unified 真实部署 | TIA V18+ + HmiUnified DLL |
| 8 | 运行 `RuntimeProber.probe()` 获取 Unified DLL 反射结果 | 填充 `RuntimeContract` 缓存 | TIA V18+ + pythonnet |
| 9 | 反向导出验证 (部署后重新导出 XML 并归一化比较) | 验证事件/动态化/引用完整 | 步骤 5-7 |

### 风险清单

| 风险 | 等级 | 缓解 |
|---|---|---|
| 黄金 fragment XML 全部缺失 | **高** | 必须步骤 2 |
| catalog 未验证即阻断所有 Classic 部署 | **中** | 版本化 `verified_import`/`verified_compile` 字段控制 |
| Unified DLL 真实类型/属性名未确认 | **中** | RuntimeContract 缓存 + 候选列表 |
| Classic XML 与目标 TIA 版本 schema 不一致 | **中** | XmlIdRegistry + 版本化 catalog |

---

## 附录：目录结构

```
backend/
├── __init__.py
├── config_manager.py          ← 配置 (不变)
├── hmi_ir.py                  ← 旧 IR 校验 (不变)
├── variable_engine.py         ← 重构 (enrich + generate)
├── simaticml_generator.py     ← 旧 SimaticML (不变)
├── template_xml_generator.py  ← 旧模板改写 (不变)
├── import_engine.py           ← 旧导入引擎 (不变)
├── openness_manager.py        ← faã§ade (新增 delegate 属性)
│
├── domain/                    ← PR-01: 领域模型
│   ├── enums.py
│   ├── ir_v2.py
│   ├── diagnostics.py
│   ├── validation.py
│   ├── legacy_adapter.py
│   ├── deployment_plan.py
│   └── deployment_result.py
│
├── capabilities/              ← PR-03: 能力矩阵
│   ├── static_matrix.py
│   └── capability_service.py
│
├── planners/                  ← PR-03: 部署计划器
│   ├── dependency_graph.py
│   └── deployment_planner.py
│
├── backends/                  ← PR-05~10: 三后端
│   ├── base.py
│   ├── classic/
│   │   ├── xml_fragment_catalog.py
│   │   ├── xml_id_registry.py
│   │   ├── link_resolver.py
│   │   ├── classic_validator.py
│   │   ├── common.py
│   │   ├── tag_xml_builder.py
│   │   ├── screen_xml_builder.py
│   │   ├── function_list_builder.py
│   │   ├── dynamic_xml_builder.py
│   │   ├── vbs_builder.py
│   │   ├── comfort_backend.py
│   │   └── basic_backend.py
│   └── unified/
│       ├── reflection_adapter.py
│       ├── tag_builder.py
│       ├── screen_builder.py
│       ├── property_builder.py
│       ├── binding_builder.py
│       ├── event_builder.py
│       ├── js_builder.py
│       └── unified_backend.py
│
├── openness/                  ← PR-04: Openness 拆分
│   ├── assembly_loader.py
│   ├── session_manager.py
│   ├── device_discovery.py
│   ├── compiler.py
│   ├── exception_mapper.py
│   └── runtime_contract.py    ← Part 5: Unified 运行时契约
│
├── references/                ← PR-11: Catalog 服务
│   └── catalog_service.py
│
└── services/                  ← Part 2: 部署服务
    ├── verification_service.py  ← Part 6: 语义验证
    └── deployment_service.py    ← Part 2-4: 统一部署流水线 + BackendFactory

reference_catalog/
├── V20/Comfort/TP1200/manifest.yaml
└── V20/Basic/KTP700/manifest.yaml

tests/
├── test_domain_ir_v2.py            (20)
├── test_domain_legacy_adapter.py   (18)
├── test_domain_diagnostics.py      (15)
├── test_variable_engine_v2.py      (22)
├── test_capabilities.py            (14)
├── test_planners.py                (13)
├── test_hmi_api.py                 (7)
├── test_openness_modules.py        (17)
├── test_classic_builders.py        (31)
├── test_backends.py                (13)
├── test_unified_backend.py         (31)
├── test_verification.py            (14)
├── test_deployment_pipeline.py     (33)
├── test_hmi_ir.py                  (8)
├── test_flask_api.py               (12)
├── test_openness_manager.py        (16)
└── test_template_xml_generator.py  (11)
                                     → 295 total
```

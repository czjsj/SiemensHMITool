# Siemens HMI Assistant — 自动 HMI 生成调用链说明

> **文档版本**: 1.0
> **生成日期**: 2026-06-19
> **对应代码基线**: V3.5 (commit ab4608a)

---

## 1. 总体架构

```
用户输入 (自然语言)
  │
  ▼
┌─────────────────────────────────────────────────┐
│  app.py (Flask SSE)                             │
│  /api/generate  →  pipeline_orchestrator        │
└─────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────┐
│  pipeline_orchestrator.py                       │
│  run_pipeline()                                 │
│    ├─ LLMClient.stream()      ← prompts.py      │
│    ├─ extract_json()                            │
│    ├─ validate_ir()           ← hmi_ir.py       │
│    ├─ VariableEngine.generate()                 │
│    ├─ render_ir_to_png()      ← preview_renderer│
│    ├─ MiMo visual review      ← mimo_client.py  │
│    └─ SSE events → frontend                     │
└─────────────────────────────────────────────────┘
  │  (用户点击"导入")
  ▼
┌─────────────────────────────────────────────────┐
│  两条生成路线 (import_or_generate_from_ir):      │
│                                                 │
│  Route A: classic_template_xml                   │
│    template_xml_generator.generate_from_template │
│    → OpennessManager.import_screen_xml()         │
│                                                 │
│  Route B: simaticml (旧路线)                     │
│    simaticml_generator.generate_simaticml()      │
│    → OpennessManager.import_screen()             │
│                                                 │
│  Route C: unified_direct                         │
│    OpennessManager.create_unified_screen_from_ir │
└─────────────────────────────────────────────────┘
```

---

## 2. 关键入口函数与模块

### 2.1 生成管线

| 函数/类 | 文件 | 说明 |
|---------|------|------|
| `run_pipeline()` | `backend/pipeline_orchestrator.py` | SSE 流水线主入口 |
| `LLMClient.stream()` | `backend/llm_client.py` | 流式调用 LLM |
| `build_messages()` | `backend/prompts.py` | 构建 LLM 提示词 |
| `extract_json()` | `backend/llm_client.py` | 从 LLM 输出提取 JSON IR |
| `validate_ir()` | `backend/hmi_ir.py` | 旧版 IR 校验 |
| `VariableEngine.generate()` | `backend/variable_engine.py` | 变量自动绑定 (旧兼容入口) |
| `VariableEngine.enrich()` | `backend/variable_engine.py` | IR → HmiProjectSpec (V3.0 新 API) |
| `render_ir_to_png()` | `backend/preview_renderer.py` | 渲染 IR 为预览图 |
| `analyze_with_mimo()` | `backend/mimo_client.py` | MiMo 视觉审查 |

### 2.2 XML 生成

| 函数/类 | 文件 | 说明 |
|---------|------|------|
| `generate_from_template_xml()` | `backend/template_xml_generator.py` | 模板 XML 改写 (Classic 路线) |
| `generate_simaticml()` | `backend/simaticml_generator.py` | SimaticML 从零生成 (旧路线) |
| `XmlValidator.validate()` | `backend/xml_validator.py` | Pre-import XML 校验 |

### 2.3 导入与部署

| 函数/类 | 文件 | 说明 |
|---------|------|------|
| `import_or_generate_from_ir()` | `backend/openness_manager.py` | 统一导入入口 (路由) |
| `import_screen_xml()` | `backend/openness_manager.py` | 经典模板 XML 导入 |
| `import_screen()` | `backend/openness_manager.py` | SimaticML 导入 |
| `create_unified_screen_from_ir()` | `backend/openness_manager.py` | Unified 直接绘制 |
| `sync_tags()` | `backend/openness_manager.py` | HMI 变量表同步 |
| `ImportEngine.import_xml()` | `backend/import_engine.py` | TIA 导入引擎 (预处理+校验+导入) |
| `DeploymentService.deploy()` | `backend/services/deployment_service.py` | V3.2 统一部署服务 |

### 2.4 校验与验证

| 函数/类 | 文件 | 说明 |
|---------|------|------|
| `validate_ir_v2()` | `backend/domain/validation.py` | HmiProjectSpec 交叉引用校验 |
| `validate_ir()` | `backend/hmi_ir.py` | 旧 IR 校验 |
| `VerificationService.verify_full()` | `backend/services/verification_service.py` | 部署后语义验证 |
| `XmlValidator.validate()` | `backend/xml_validator.py` | XML 导入前校验 |

### 2.5 领域模型

| 类 | 文件 | 说明 |
|----|------|------|
| `HmiProjectSpec` | `backend/domain/ir_v2.py` | 顶层工程语义 IR |
| `ScreenSpec` | `backend/domain/ir_v2.py` | 画面规格 |
| `ScreenItemSpec` | `backend/domain/ir_v2.py` | 控件规格 |
| `TagSpec` | `backend/domain/ir_v2.py` | 变量规格 |
| `BindingSpec` | `backend/domain/ir_v2.py` | 动态绑定 |
| `EventSpec` | `backend/domain/ir_v2.py` | 语义事件 |
| `ActionSpec` | `backend/domain/ir_v2.py` | 语义动作 |
| `LegacyIrAdapter` | `backend/domain/legacy_adapter.py` | 旧 IR → HmiProjectSpec |
| `Diagnostic` | `backend/domain/diagnostics.py` | 诊断信息模型 |

### 2.6 枚举定义

| 枚举 | 文件 | 说明 |
|------|------|------|
| `HmiFamily` | `backend/domain/enums.py` | HMI 面板家族 (basic/comfort/unified) |
| `ScreenItemType` | `backend/domain/enums.py` | 控件类型 |
| `BindingKind` | `backend/domain/enums.py` | 绑定类型 |
| `SemanticEvent` | `backend/domain/enums.py` | 语义事件类型 |
| `SemanticActionType` | `backend/domain/enums.py` | 语义动作类型 |
| `TagScope` | `backend/domain/enums.py` | 变量作用域 |
| `DeploymentPhase` | `backend/domain/enums.py` | 部署阶段 |
| `DeploymentStatus` | `backend/domain/enums.py` | 部署状态机 |

### 2.7 后端实现

| 类 | 文件 | 说明 |
|----|------|------|
| `ComfortBackend` | `backend/backends/classic/comfort_backend.py` | Comfort 面板后端 |
| `BasicBackend` | `backend/backends/classic/basic_backend.py` | Basic 面板后端 |
| `UnifiedBackend` | `backend/backends/unified/unified_backend.py` | Unified 面板后端 |
| `BackendFactory` | `backend/services/deployment_service.py` | 后端工厂 (路由) |

---

## 3. 完整导入流程 (Classic 模板 XML 路线)

```
1. LLM 生成 IR JSON
2. validate_ir() — 旧格式校验
3. VariableEngine.generate() — 变量自动绑定
    内部: LegacyIrAdapter.convert() → enrich() → 回填
4. 用户点击"导入"
5. OpennessManager.import_or_generate_from_ir(mode="auto")
6. 路由判断: is_classic → classic_template_xml
7. generate_from_template_xml(ir, template_xml)
    ├─ _detect_namespace()
    ├─ _find_screen_node()
    ├─ _match_template_item() — 按优先级匹配模板控件
    ├─ _clone_matching_template_item() — 模板控件不足时克隆
    ├─ _apply_object_to_item() — 替换名称/位置/尺寸/文本/变量/脚本
    └─ _element_to_string() — 序列化 XML
8. XmlValidator.validate() — 导入前校验
9. Screen.Export() — 导出模板 (可选)
10. import_screen_xml() → _preprocess_xml_for_import()
11. Screens.Import(FileInfo, ImportOptions.Override)
12. sync_tags() — 同步 HMI 变量表
13. _compile() — 触发编译
14. 返回结果给前端
```

---

## 4. 旧格式 IR 结构 (V2.3)

```json
{
  "meta": {
    "screen_name": "Screen_1",
    "title": "画面标题",
    "hmi_type": "Comfort",
    "resolution": "1280x800",
    "generation_mode": "auto"
  },
  "objects": [
    {
      "id": "BTN_Start",
      "type": "Button",
      "x": 80, "y": 120,
      "width": 120, "height": 50,
      "text": "启动",
      "background_color": "#2BB673",
      "process_tag": "BTN_Motor_Start",
      "tag_mode": "momentary",
      "press_script": "Sub_BTN_Start_Press",
      "release_script": "Sub_BTN_Start_Release"
    }
  ],
  "tags": [
    {
      "name": "BTN_Motor_Start",
      "data_type": "Bool",
      "address": "",
      "comment": "电机启动按钮 — 瞬时按钮"
    }
  ],
  "scripts": [
    {
      "name": "Sub_BTN_Start_Press",
      "language": "VBS",
      "purpose": "...",
      "code": "SmartTags(\"BTN_Motor_Start\") = 1\n"
    }
  ]
}
```

---

## 5. 新格式 IR V2 结构 (HmiProjectSpec)

通过 `LegacyIrAdapter.convert()` 或 AI 直接输出:

```python
HmiProjectSpec(
    schema_version="2.0",
    metadata=ProjectMetadata(project_name="Motor_Control"),
    target=TargetSpec(family=HmiFamily.COMFORT),
    tags=[TagSpec(name="BTN_Motor_Start", data_type="Bool", ...)],
    screens=[ScreenSpec(
        name="Motor_Control",
        items=[ScreenItemSpec(
            id="BTN_Start",
            type=ScreenItemType.BUTTON,
            tag_binding="BTN_Motor_Start",
            bindings=[BindingSpec(...)],
            events=[EventSpec(event=SemanticEvent.PRESS, actions=[...])],
        )]
    )]
)
```

---

## 6. 向后兼容策略

- `VariableEngine.generate()` 保留旧签名，内部调用 `enrich()` + 回填
- `LegacyIrAdapter` 负责旧 dict IR → HmiProjectSpec 转换
- `validate_ir()` 继续接受旧 dict IR
- `generate_simaticml()` 保留为兜底路线
- 新增模块放在 `backend/template/` 下，不修改旧模块核心逻辑

# HMI Tag XML 生成规范

## 核心原则

HMI Tag XML **不得**包含 `<SW.Blocks>` 包装。

| 类型 | XML 根对象 | 导入目标 | 说明 |
|------|-----------|---------|------|
| HMI Tag XML | `<SW.Tag>` | `Hmi.Tag.TagComposition.Import` | 用于 HMI 变量同步 |
| HMI TagTable XML | `<SW.TagTable>` | `TagFolder.TagTables.Import` | 用于完整变量表导入 |
| PLC Blocks XML | `<SW.Blocks>` | `SW.Blocks.*.Import` | **不能**用于 HMI 导入 |

## 为什么 SW.Blocks 是错误的

`SW.Blocks` 对应 `Siemens.Engineering.SW.Blocks` — 这是 **PLC 软件块容器类型**。

当 `TagComposition.Import` 收到包含 `SW.Blocks` 的 XML 时，TIA Portal 拒绝导入并抛出：
```
Class of the 'Siemens.Engineering.SW.Blocks' type at line number 4 ... is not supported
```

因为在西门子 Openness API 中：
- `Siemens.Engineering.Hmi.Tag.TagComposition` → 期望 `SW.Tag` / `Hmi.Tag.Tag`
- `Siemens.Engineering.SW.Blocks.TagComposition` → 期望 `SW.Blocks`

## 正确格式

```xml
<?xml version="1.0" encoding="utf-8"?>
<Document xmlns="http://www.siemens.com/automation/SimaticML">
  <Engineering version="V16"/>
  <SW.Tag ID="a1b2c3d4">
    <AttributeList>
      <Name>Internal_Tag_BOOL</Name>
      <DataType>Bool</DataType>
      <Connection></Connection>
    </AttributeList>
  </SW.Tag>
</Document>
```

## 错误格式（会导致导入失败）

```xml
<?xml version="1.0" encoding="utf-8"?>
<Document xmlns="http://www.siemens.com/automation/SimaticML">
  <Engineering version="V16"/>
  <SW.Blocks ID="...">    <!-- ❌ 这是 PLC Blocks 类型，不是 HMI Tag -->
    <SW.Tag>...</SW.Tag>
  </SW.Blocks>
</Document>
```

## 检测方法

代码中的 `validate_xml_class_for_import_target(xml_path, 'hmi_tags')` 函数

会在导入前检查：
1. 是否包含 `<SW.Blocks>` → 拒绝
2. 是否包含 PLC 对象类型 (OB, FB, FC, DB) → 拒绝
3. 是否包含 SW.Tag / SW.TagTable → 允许

## 相关文件

- `backend/references/golden_hmi_tag_template.xml` — 金标准模板
- `backend/backends/classic/tag_xml_builder.py` — HMI Tag XML 生成器
- `backend/xml_validator.py` — XML 类型守卫

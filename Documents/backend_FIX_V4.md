# V4：修复预览与博途实际位置不一致

## 解决的问题

V3 已解决：
- `ID` 子节点导致的导入失败
- `MultilingualText` 文本格式导致的导入失败
- Screen 尺寸与 HMI 不匹配导致的导入失败

V4 新增修复：
- 经典模板 XML 模式保留模板尺寸（如 800x480）时，如果 IR 仍是 1280x800，导入前会把控件坐标/尺寸按比例映射到模板尺寸。
- 前端生成/预览阶段会读取 `openness.target_resolution`，让 LLM 直接输出目标分辨率，并在校验后再次强制把 IR 缩放到目标分辨率。

## 必须配置

如果你的实际 HMI 是 800x480，请在 config.yaml 中设置：

```yaml
openness:
  target_resolution: "800x480"
  auto_scale_screen_items: true

hmi_defaults:
  resolution: "800x480"
```

如果是 1024x768，则都改为 `1024x768`。

## 覆盖文件

建议覆盖整个 `fixed_backend_v4` 内的 .py 文件，至少包括：

- hmi_ir.py
- pipeline_orchestrator.py
- template_xml_generator.py

保留 V3 的其它修复文件。

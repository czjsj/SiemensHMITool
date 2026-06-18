# Basic/KTP Basic HMI 支持说明

本补丁使后端把 Basic/KTP Basic 触摸屏作为“经典 HMI”处理，但与 Comfort 区分：

- IR 支持 `meta.hmi_type = "Basic"`，并支持 Basic 常用分辨率 `480x272`、`800x480`、`1280x800` 等。
- Openness 能力识别新增 `is_basic`、`is_comfort`、`hmi_family` 字段。
- Basic 自动路由到 `classic_template_xml`，不走 Unified 直接绘制。
- Basic 未配置模板 XML 时不再盲目回退 SimaticML，而是返回明确错误，避免生成与 Basic 设备不兼容的 XML。
- Basic 场景的提示词会要求模型尽量不生成 VBS 脚本，按钮事件建议由模板预置或 PLC 变量实现。
- 同时保留上一版“label/unit 展开为真实 Text 对象”的对象数量修复。

使用方式：

1. 在 TIA Portal 中，基于目标 Basic/KTP Basic 设备手工创建一个模板画面。
2. 模板中放置你希望支持的基础控件，例如 TextField、IOField、Button、Circle/Indicator、SymbolicIOField。
3. 通过软件的“导出模板 XML”功能导出该模板。
4. 在 `config.yaml` 中配置：

```yaml
openness:
  hmi_device: "你的 Basic 触摸屏设备名"
  target_resolution: "480x272"   # 或目标面板真实分辨率
  generation_mode: "auto"
  classic_template:
    enabled: true
    template_xml_path: "exports/templates/你的Basic模板.xml"

hmi_defaults:
  resolution: "480x272"
  hmi_type: "Basic"
```

5. 重新运行后端，再生成/导入画面。

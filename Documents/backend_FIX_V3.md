# TIA Openness XML Import Fix V3

本补丁基于 V2，继续修复 `The screen size does not match the device`。

## 根因
TIA/WinCC Advanced 的 Screen XML 里的 `<Width>` / `<Height>` 必须与目标 HMI 设备分辨率完全一致。原后端会把 IR 默认分辨率（常见为 1280x800）写回模板 XML 或直接导入 XML；如果目标设备是 800x480、1024x768 等，就会在 `Screens.Import(...)` 阶段报错，部分 TIA V16 环境可能直接闪退。

## V3 改动

1. `template_xml_generator.py`
   - 默认保留从 TIA 导出的模板画面尺寸。
   - 不再用 IR 的默认 `1280x800` 覆盖模板尺寸。

2. `openness_manager.py`
   - 导入前自动读取目标 HMI 尺寸：
     - 优先读取 `config.yaml -> openness.target_resolution`；
     - 其次读取已有 HMI 画面的 Width/Height；
     - 再尝试导出已有画面 XML 并解析尺寸。
   - 如果 XML 尺寸与目标 HMI 不一致，导入前自动改写 XML 的 Screen Width/Height。
   - 默认同步缩放控件坐标和大小，避免改小分辨率后控件大面积越界。

3. `import_engine.py`
   - 走 ImportEngine 管线时也会执行同样的尺寸对齐。

4. `config_manager.py`
   - 新增：
     - `openness.target_resolution`: 可选，如 `800x480`；留空自动读取。
     - `openness.auto_scale_screen_items`: 默认 `true`。

## 使用建议

如果你的 HMI 设备里已经有任意一个画面，留空 `target_resolution` 即可自动读取。

如果是空 HMI 项目，建议在 `config.yaml` 中手动加入：

```yaml
openness:
  target_resolution: "800x480"   # 按你的实际 HMI 改
  auto_scale_screen_items: true
```

替换补丁后，请重启后端并重新生成 XML，不要继续导入旧的 `preprocessed_screen.xml`。

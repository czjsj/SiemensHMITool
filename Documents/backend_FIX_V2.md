# TIA Openness HMI XML 修复补丁 v2

本补丁用于修复两类 TIA V16 / WinCC Advanced / Comfort HMI 画面 XML 导入错误：

1. `Cannot find the required 'ID' attribute element for the 'ID' element`
   - 原因：旧逻辑把对象 ID 写成 `<ID>...</ID>` 子元素。
   - 修复：保留 / 生成 TIA V16 格式的 `ID="..."` 属性。

2. `The argument 'text' (...) has an invalid format`
   - 原因：`TextOff` / `TextOn` / `Text` 等画面可见文本被改成了 `<Text>复位</Text>` 纯文本。
   - 修复：这些可见文本会生成 TIA 需要的富文本片段：
     `<Text><body><p>复位</p></body></Text>`。
   - `HelpText` 仍保持纯文本。

## 使用方式

备份后端目录中的原文件，然后把本目录中的同名 `.py` 文件复制过去覆盖：

- `multilingual_text_builder.py`
- `template_xml_generator.py`
- `text_normalizer.py`
- `xml_validator.py`
- `import_engine.py`
- `openness_manager.py`

重启后端后重新生成 XML，不要继续导入旧的 `preprocessed_screen.xml`。

## 已验证

使用用户提供的 `Motor_Control_20260618_150337.xml` 进行本地预处理验证：

- 不再产生 `<ID>` 子元素。
- `TextOff` / `TextOn` 输出为 `<body><p>...</p></body>`。
- `XmlValidator.validate(...)` 返回 `valid=True`。

注意：当前环境无法直接调用本机 TIA Portal Openness，因此仍需在你的 Windows/TIA 环境中实测导入。

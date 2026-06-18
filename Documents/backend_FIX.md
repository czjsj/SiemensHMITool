# TIA Openness XML 导入修复包

已修复问题：

1. `MultilingualTextBuilder` 不再生成非法 `<ID>...</ID>` 子元素。TIA V16/Comfort 的 ID 必须保留在元素属性上，例如 `<MultilingualText ID="1" ...>`。
2. 导入预处理重建 `MultilingualText` 时保留 TIA V16 的 `ObjectList / MultilingualTextItem / AttributeList / Culture / Text` 结构。
3. `XmlValidator` 兼容 TIA V16/Comfort 的 MultilingualText 结构，并会阻断非法 `<ID>` 子元素。
4. `template_xml_generator._set_item_text()` 不再把按钮文字写入 `HelpText`，而是正确写入 `TextOff` 和 `TextOn`。
5. `import_engine._extract_screen_name()` 支持从 `<AttributeList><Name>...</Name>` 读取 TIA V16 画面名称。
6. `openness_manager._preprocess_xml_for_import()` 的画面名称冲突检测支持 TIA V16 结构。

替换建议：把包内同名 `.py` 文件覆盖到你的后端对应目录，重启后端，再重新生成并导入 XML。

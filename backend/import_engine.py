# -*- coding: utf-8 -*-
"""
TIA Import Engine — TIA HMI XML 导入管线第五层（终端层）
============================================================

职责：通过 Openness API 将已校验的 XML 安全导入 TIA Portal。

对应提示词规范中的 Import 唯一正确方式：
  folder.Screens.Import(fileInfo, ImportOptions.Override);

⚠️ 强制约束（Error Protection）：
  ✅ Fail Fast:      任何 XML 不合法 → 直接阻断，不尝试导入
  ✅ No Partial Fix: 不"修一半继续导入"——校验不通过就阻断
  ✅ No Hacks:       禁止 ScreenComposition.Import、反射 Import、temp ASCII hack
  ✅ Single Method:  唯一允许的导入方式：Screens.Import(FileInfo, ImportOptions.Override)

这是管线的第五层（终端层），位于 XmlValidator 之上。
X 通过 → ImportEngine → 成功/失败
X 未通过 → 直接阻断（ImportEngine 不接收校验未通过的 XML）

管线完整流程：
  TextNormalizer → MultilingualTextBuilder → ScreenNumberAllocator
  → XmlValidator（闸门） → ImportEngine（终端）
"""
import os
import tempfile
import shutil
from dataclasses import dataclass, field


@dataclass
class ImportResult:
    """导入操作结果。

    属性:
        ok: 是否成功导入。
        method: 使用的导入方法。
        screen_name: 导入的画面名称（成功时）。
        error: 错误描述（失败时）。
        warnings: 预处理期间产生的警告。
        validation: 校验结果摘要。
    """
    ok: bool = False
    method: str = ""
    screen_name: str = ""
    error: str = ""
    warnings: list = field(default_factory=list)
    validation: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "imported": self.ok,
            "ok": self.ok,
            "method": self.method,
            "screen_name": self.screen_name,
            "message": self.error if not self.ok else (
                f"画面 '{self.screen_name}' 已成功导入。"
            ),
            "error": self.error,
            "warnings": self.warnings,
            "validation": self.validation,
        }


class ImportEngine:
    """TIA Portal Openness 稳定导入引擎。

    分层设计：
      1. 预处理层：文本清洗 + MultilingualText DOM 重建 + Number 删除
      2. 校验层（闸门）：XmlValidator 全面检查 → 不通过则阻断
      3. 导入层：唯一调用 Screens.Import(FileInfo, ImportOptions.Override)

    使用方式：
        engine = ImportEngine(openness_manager)
        result = engine.import_xml(xml_content, "GeneratedScreens")
        if result.ok:
            print(f"画面 {result.screen_name} 已导入")
    """

    # 导入选项（仅允许 Override 和 Rename）
    VALID_OPTIONS = {"Override", "Rename"}

    def __init__(self, openness_manager):
        """
        参数:
            openness_manager: OpennessManager 实例（需已连接博途）。
        """
        self._om = openness_manager
        self._cfg = openness_manager.cfg if hasattr(openness_manager, 'cfg') else {}

    # ---- 公共 API ----

    def import_xml(
        self,
        xml_content: str,
        target_folder: str = "",
        import_option: str = "Override",
        compile_after: bool = True,
        save_after: bool = False,
    ) -> ImportResult:
        """将 XML 画面导入到 TIA Portal。

        完整管线（预处理 → 校验 → 导入）：
          1. 预处理：TextNormalizer 清洗 + MultilingualTextBuilder DOM 重建
          2. 校验：XmlValidator 全面检查 → 不通过则直接阻断
          3. 导入：Screens.Import(FileInfo, ImportOptions)

        参数:
            xml_content: 完整的画面 XML 字符串。
            target_folder: 目标子文件夹名（留空导入根画面文件夹）。
            import_option: ImportOptions — "Override" 或 "Rename"。
            compile_after: 是否导入后触发编译。
            save_after: 是否导入后保存项目。

        返回:
            ImportResult 对象。
        """
        import_option = self._normalize_option(import_option)

        # ================================================================
        # Phase 1: 预处理
        # ================================================================
        from .text_normalizer import TextNormalizer
        from .multilingual_text_builder import MultilingualTextBuilder
        from .screen_number_allocator import ScreenNumberAllocator

        preprocess_warnings: list = []

        # 1a. 文本级 HTML 标签清洗
        cleaned_xml, clean_report = TextNormalizer.normalize_xml_content(xml_content)
        if clean_report.get("html_removed", 0) > 0:
            tags = clean_report.get("html_tags_found", [])
            preprocess_warnings.append(
                f"文本清洗：已移除 {clean_report['html_removed']} 处 HTML 标签"
                f" ({', '.join(tags[:8])})"
            )
        if clean_report.get("controls_removed", 0) > 0:
            preprocess_warnings.append(
                f"文本清洗：已移除 {clean_report['controls_removed']} 处非法控制字符"
            )

        # 1b. DOM 级 MultilingualText 安全重建
        cleaned_xml, mt_log = self._rebuild_all_multilingual_text(cleaned_xml)
        preprocess_warnings.extend(mt_log)

        # 1c. 删除 <Number> 节点（让 TIA 自动分配 screen number）
        allocator = ScreenNumberAllocator()
        cleaned_xml = allocator.remove_number_nodes(cleaned_xml)

        # 1d. 导入前画面尺寸保护：把 XML 的 Screen Width/Height 对齐目标 HMI。
        # 这一步必须在 Screens.Import 之前完成，否则 TIA 可能报
        # "The screen size does not match the device"，部分环境下甚至闪退。
        try:
            sw_for_size = self._om._find_hmi_software()
            align = getattr(self._om, "_align_xml_screen_size_to_hmi", None)
            if sw_for_size is not None and callable(align):
                cleaned_xml = align(cleaned_xml, sw_for_size, preprocess_warnings)
        except Exception as exc:
            preprocess_warnings.append(f"画面尺寸自动对齐失败：{exc}")

        # ================================================================
        # Phase 2: 校验（闸门 — Fail Fast）
        # ================================================================
        from .xml_validator import XmlValidator

        validation = XmlValidator.validate(cleaned_xml)

        # 收集已使用号码并检查冲突
        used_numbers = self._collect_existing_numbers()
        if used_numbers:
            allocator.register_existing(used_numbers)
            num_conflict = XmlValidator.check_number_conflicts(
                cleaned_xml, used_numbers
            )
            if num_conflict.errors:
                validation.errors.extend(num_conflict.errors)
                validation.valid = False

        # ⚠️ Fail Fast: 校验不通过 → 直接阻断（No Partial Fix）
        if not validation.valid:
            return ImportResult(
                ok=False,
                method="Screens.Import(FileInfo, ImportOptions.Override)",
                error=(
                    f"XML 校验未通过，导入已阻断。"
                    f"共 {len(validation.errors)} 个错误。"
                    f"前 3 个错误: {validation.errors[:3]}"
                ),
                warnings=preprocess_warnings + validation.warnings,
                validation=validation.to_dict(),
            )

        # ================================================================
        # Phase 3: 导入（唯一允许方式：Screens.Import）
        # ================================================================
        screen_name = self._extract_screen_name(cleaned_xml)

        # 写入临时文件
        temp_dir = tempfile.mkdtemp(prefix="tia_import_engine_")
        xml_path = os.path.join(temp_dir, f"{screen_name}.xml")
        try:
            with open(xml_path, "w", encoding="utf-8-sig") as f:
                f.write(cleaned_xml)

            # 获取 HMI 软件对象
            sw = self._om._find_hmi_software()
            if sw is None:
                return ImportResult(
                    ok=False,
                    method="Screens.Import(FileInfo, ImportOptions.Override)",
                    error=f"未找到 HMI 设备 '{self._cfg.get('hmi_device', '')}'。",
                    warnings=preprocess_warnings,
                    validation=validation.to_dict(),
                )

            # 定位目标 Screens 集合
            target_screens = self._resolve_target_screens(sw, target_folder)

            # ⚠️ 唯一导入方式：Screens.Import(FileInfo, ImportOptions)
            from System.IO import FileInfo  # type: ignore
            from Siemens.Engineering import ImportOptions  # type: ignore

            file_info = FileInfo(xml_path)
            option = (
                ImportOptions.Override if import_option == "Override"
                else ImportOptions.Rename
            )

            try:
                target_screens.Import(file_info, option)
            except Exception as e:
                return ImportResult(
                    ok=False,
                    method="Screens.Import(FileInfo, ImportOptions.Override)",
                    error=(
                        f"导入失败：{e}。"
                        f"请确认：1) XML 格式兼容当前 TIA 版本；"
                        f"2) screen number/name 无冲突；"
                        f"3) TIA Portal 中已加载项目。"
                    ),
                    warnings=preprocess_warnings,
                    validation=validation.to_dict(),
                )

            # 导入后操作
            if compile_after:
                try:
                    self._om._compile()
                except Exception as ce:
                    preprocess_warnings.append(f"编译时告警：{ce}")

            if save_after:
                try:
                    self._om._project.Save()
                except Exception:
                    pass

            return ImportResult(
                ok=True,
                method="Screens.Import(FileInfo, ImportOptions.Override)",
                screen_name=screen_name,
                warnings=preprocess_warnings + validation.warnings,
                validation=validation.to_dict(),
            )

        finally:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

    # ---- 内部方法 ----

    def _normalize_option(self, option: str) -> str:
        """规范化导入选项名称。"""
        option = option.strip()
        for valid in self.VALID_OPTIONS:
            if valid.lower() == option.lower():
                return valid
        for valid in self.VALID_OPTIONS:
            if valid.lower() in option.lower():
                return valid
        return "Override"

    def _rebuild_all_multilingual_text(self, xml_content: str) -> tuple:
        """DOM 级重建所有 MultilingualText 节点为 TIA 标准结构。

        返回 (rebuilt_xml, repair_log)。
        """
        import xml.etree.ElementTree as ET
        from .multilingual_text_builder import MultilingualTextBuilder

        repair_log = []
        decl_match = __import__('re').match(
            r'(<\?xml[^?]*\?>\s*)', xml_content
        )
        declaration = decl_match.group(1) if decl_match else ""

        # 注册命名空间
        for m in __import__('re').finditer(
            r'xmlns(?::(\w+))?="([^"]+)"', xml_content[:4096]
        ):
            prefix = m.group(1) or ""
            uri = m.group(2)
            if prefix:
                ET.register_namespace(prefix, uri)
            else:
                ET.register_namespace("", uri)

        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            repair_log.append(f"XML DOM 解析失败，跳过 MultilingualText 重建：{e}")
            return xml_content, repair_log

        builder = MultilingualTextBuilder()
        mt_elems = [
            e for e in root.iter()
            if MultilingualTextBuilder._local_tag(e) in ("MultilingualText",)
        ]

        for mt_elem in mt_elems:
            try:
                builder.rebuild_element(mt_elem)
            except Exception:
                pass  # 个别元素重建失败不影响整体

        if mt_elems:
            repair_log.append(
                f"DOM 级重建了 {len(mt_elems)} 个 MultilingualText 节点为 TIA 标准结构"
            )

        result = ET.tostring(root, encoding="unicode")
        if declaration and not result.startswith("<?"):
            result = declaration.rstrip() + "\n" + result

        return result, repair_log

    def _collect_existing_numbers(self) -> list:
        """从已连接的 HMI 设备收集已有 screen numbers。"""
        numbers = []
        try:
            sw = self._om._find_hmi_software()
            if sw:
                for s in self._om._collect_screens(sw.ScreenFolder):
                    try:
                        numbers.append(int(s.Number))
                    except Exception:
                        pass
        except Exception:
            pass
        return numbers

    def _extract_screen_name(self, xml_content: str) -> str:
        """从 XML 提取画面名称，兼容 TIA V16 <AttributeList><Name>。"""
        import re
        m = re.search(r'<(?:SW\.)?Screen[^>]*Name="([^"]*)"', xml_content)
        if m:
            return m.group(1)
        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(xml_content)

            def local(elem):
                tag = elem.tag
                if "}" in tag:
                    return tag.rsplit("}", 1)[-1]
                if "." in tag:
                    return tag.rsplit(".", 1)[-1]
                return tag

            for elem in root.iter():
                if local(elem) != "Screen":
                    continue
                for child in elem:
                    if local(child) != "AttributeList":
                        continue
                    for attr in child:
                        if local(attr) == "Name" and (attr.text or "").strip():
                            return attr.text.strip()
        except Exception:
            pass
        return "UnknownScreen"

    def _resolve_target_screens(self, hmi_software, target_folder: str = ""):
        """定位目标 Screens 集合对象。

        处理子文件夹的 Find/Create 逻辑。
        """
        screen_folder = hmi_software.ScreenFolder
        if not target_folder:
            return screen_folder.Screens

        # 尝试定位或创建子文件夹
        try:
            found = screen_folder.Folders.Find(target_folder)
            if found is not None:
                return found.Screens
        except Exception:
            pass

        try:
            created = screen_folder.Folders.Create(target_folder)
            return created.Screens
        except Exception:
            pass

        return screen_folder.Screens

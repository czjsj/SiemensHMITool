# -*- coding: utf-8 -*-
"""
XML Validator (Pre-Import Lint) — TIA HMI XML 导入管线第四层
=============================================================

兼容两类 HMI MultilingualText：
1) TIA V16/Comfort 导出结构：
   <MultilingualText ID="..." CompositionName="Text">
     <ObjectList>
       <MultilingualTextItem ID="..." CompositionName="Items">
         <AttributeList><Culture>zh-CN</Culture><Text>...</Text></AttributeList>
       </MultilingualTextItem>
     </ObjectList>
   </MultilingualText>
2) 通用结构：<MultilingualText><Text Language="zh-CN">...</Text></MultilingualText>

特别禁止：<MultilingualText><ID>...</ID>...</MultilingualText>。
该结构会导致 TIA Portal 把 <ID> 当对象元素解析，并抛出
"Cannot find the required 'ID' attribute element for the 'ID' element"。
"""
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


_HTML_PATTERN = re.compile(
    r'</?\s*(?:'
    r'body|p|div|span|br|hr|h[1-6]|table|tr|td|th|thead|tbody|'
    r'ul|ol|li|a|img|script|style|meta|link|form|input|button|'
    r'select|option|textarea|label|fieldset|legend|iframe|embed|'
    r'object|param|applet|area|base|blockquote|caption|center|'
    r'code|col|colgroup|dd|del|dfn|dir|dl|dt|em|font|frame|'
    r'frameset|header|footer|nav|section|article|aside|main|'
    r'figure|figcaption|details|summary|dialog|template|slot|'
    r'!DOCTYPE|!--|xml|pre|samp|kbd|var|ins|cite|q|abbr|'
    r'acronym|bdo|big|small|sub|sup|tt|map|area|canvas|svg|'
    r'math|audio|video|source|track|noscript|wbr|picture|'
    r'menu|menuitem|command|datalist|keygen|output|progress|'
    r'meter|time|mark|ruby|rt|rp|bdi|data'
    r')\b[^>]*/?\s*>',
    re.IGNORECASE,
)


# TIA V16/WinCC Advanced 的可见文本属性允许且需要
# <Text><body><p>...</p></body></Text>。全局 HTML 检查中应忽略这两个标签。
_ALLOWED_TIA_RICH_TAGS = {"body", "p"}
_RICH_TEXT_COMPOSITIONS = {"Text", "TextOff", "TextOn", "Caption", "DisplayText"}


@dataclass
class ValidationResult:
    valid: bool = True
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "stats": self.stats,
        }


class XmlValidator:
    """TIA Portal XML Pre-Import 校验器。"""

    @staticmethod
    def validate(xml_content: str) -> ValidationResult:
        result = ValidationResult()
        XmlValidator._check_html_tags(xml_content, result)
        XmlValidator._check_multilingual_text(xml_content, result)
        XmlValidator._check_control_chars(xml_content, result)
        XmlValidator._check_number_nodes(xml_content, result)
        XmlValidator._check_root_elements(xml_content, result)
        return result

    @staticmethod
    def check_number_conflicts(xml_content: str, used_numbers: list) -> ValidationResult:
        result = ValidationResult()
        result.stats["used_numbers"] = sorted(used_numbers)
        for m in re.finditer(r'<(?:\w+:)?Number>(\d+)</(?:\w+:)?Number>', xml_content, re.I):
            num = int(m.group(1))
            if num in used_numbers:
                line_no = xml_content.count("\n", 0, m.start()) + 1
                result.errors.append(
                    f"screen number {num} 冲突（第 {line_no} 行）：已被占用。"
                    f"已用号码: {sorted(used_numbers)}"
                )
                result.valid = False
        return result

    # ------------------------------------------------------------------
    # 检查项
    # ------------------------------------------------------------------
    @staticmethod
    def _check_html_tags(xml_content: str, result: ValidationResult):
        raw_matches = list(_HTML_PATTERN.finditer(xml_content))
        matches = []
        allowed_count = 0
        for m in raw_matches:
            tag = XmlValidator._html_tag_name(m.group(0))
            if tag in _ALLOWED_TIA_RICH_TAGS:
                allowed_count += 1
                continue
            matches.append((m, tag))

        result.stats["html_tags"] = len(matches)
        result.stats["tia_rich_tags"] = allowed_count
        for m, tag in matches[:20]:
            line_no = xml_content.count("\n", 0, m.start()) + 1
            result.errors.append(f"检测到禁止的 HTML 标签 '<{tag}>' 在第 {line_no} 行附近")
        if len(matches) > 20:
            result.errors.append(f"……还有 {len(matches) - 20} 处 HTML 标签未列出")
        if matches:
            result.valid = False

    @staticmethod
    def _check_multilingual_text(xml_content: str, result: ValidationResult):
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError:
            XmlValidator._check_mt_regex_fallback(xml_content, result)
            return

        mt_elems = [e for e in root.iter() if XmlValidator._local_tag(e) == "MultilingualText"]
        result.stats["multilingual_text_nodes"] = len(mt_elems)

        for mt in mt_elems:
            line_no = XmlValidator._approx_line(xml_content, mt)

            # 旧错误：<ID> 子节点。TIA V16/Comfort 的 ID 必须是属性。
            for child in mt:
                if XmlValidator._local_tag(child) == "ID":
                    result.errors.append(
                        f"MultilingualText 内发现非法 <ID> 子元素（第 {line_no} 行）。"
                        f"请改为 ID 属性，或保留 TIA 导出的原始 ObjectList/MultilingualTextItem 结构。"
                    )
                    result.valid = False

            if XmlValidator._is_v16_multilingual_text(mt):
                XmlValidator._check_v16_multilingual_text(mt, line_no, result)
                continue

            direct_text = None
            for child in mt:
                if XmlValidator._local_tag(child) == "Text":
                    direct_text = child
                    break
            if direct_text is not None:
                if "Language" not in direct_text.attrib:
                    result.errors.append(f"MultilingualText 的 Text 子节点缺少 Language 属性（第 {line_no} 行）")
                    result.valid = False
                child_text = (direct_text.text or "").strip()
                if not child_text:
                    result.errors.append(f"MultilingualText 的 Text 子节点内容为空（第 {line_no} 行）")
                    result.valid = False
                if _HTML_PATTERN.search(direct_text.text or ""):
                    result.errors.append(f"MultilingualText 的 Text 内容包含 HTML 标签（第 {line_no} 行）")
                    result.valid = False
                continue

            direct = (mt.text or "").strip()
            if direct and len(direct) <= 10:
                result.errors.append(
                    f"MultilingualText 为裸文本 '{direct}'（第 {line_no} 行），"
                    f"缺少 TIA V16 ObjectList/MultilingualTextItem 或 <Text Language=\"...\"> 结构。"
                )
            else:
                result.errors.append(
                    f"MultilingualText 缺少可识别文本结构（第 {line_no} 行）："
                    f"需要 V16 ObjectList/MultilingualTextItem 或通用 <Text Language=\"...\">。"
                )
            result.valid = False

    @staticmethod
    def _check_v16_multilingual_text(mt: ET.Element, line_no: int, result: ValidationResult):
        found_item = False
        found_text = False
        found_culture = False
        for item in mt.iter():
            if XmlValidator._local_tag(item) != "MultilingualTextItem":
                continue
            found_item = True
            if "ID" not in item.attrib:
                result.errors.append(f"MultilingualTextItem 缺少 ID 属性（第 {line_no} 行）")
                result.valid = False
            if item.get("CompositionName") != "Items":
                result.warnings.append(f"MultilingualTextItem 建议使用 CompositionName=\"Items\"（第 {line_no} 行）")
            for attr_list in item:
                if XmlValidator._local_tag(attr_list) != "AttributeList":
                    continue
                for child in attr_list:
                    ctag = XmlValidator._local_tag(child)
                    if ctag == "Culture":
                        found_culture = True
                    elif ctag == "Text":
                        found_text = True
                        txt = "".join(child.itertext())
                        if _HTML_PATTERN.search(txt):
                            result.errors.append(f"MultilingualTextItem/Text 内容包含 HTML 标签（第 {line_no} 行）")
                            result.valid = False
                        cname = mt.get("CompositionName") or ""
                        if cname in _RICH_TEXT_COMPOSITIONS and not XmlValidator._has_rich_body_p(child):
                            result.errors.append(
                                f"MultilingualText CompositionName=\"{cname}\" 的 Text 需要 "
                                f"<body><p>...</p></body> 富文本结构（第 {line_no} 行）"
                            )
                            result.valid = False
        if not found_item:
            result.errors.append(f"MultilingualText 缺少 MultilingualTextItem（第 {line_no} 行）")
            result.valid = False
        if not found_culture:
            result.errors.append(f"MultilingualTextItem 缺少 Culture（第 {line_no} 行）")
            result.valid = False
        if not found_text:
            result.errors.append(f"MultilingualTextItem 缺少 Text（第 {line_no} 行）")
            result.valid = False

    @staticmethod
    def _check_control_chars(xml_content: str, result: ValidationResult):
        illegal = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F]')
        matches = list(illegal.finditer(xml_content))
        result.stats["illegal_control_chars"] = len(matches)
        for m in matches[:10]:
            line_no = xml_content.count("\n", 0, m.start()) + 1
            result.errors.append(f"检测到非法控制字符 U+{ord(m.group(0)):04X} 在第 {line_no} 行")
        if matches:
            result.valid = False

    @staticmethod
    def _check_number_nodes(xml_content: str, result: ValidationResult):
        matches = list(re.finditer(r'<(?:\w+:)?Number>(\d+)</(?:\w+:)?Number>', xml_content, re.I))
        result.stats["number_nodes"] = len(matches)
        for m in matches:
            num = m.group(1)
            line_no = xml_content.count("\n", 0, m.start()) + 1
            result.warnings.append(f"发现固定 screen number: {num}（第 {line_no} 行），建议删除让 TIA 自动分配")

    @staticmethod
    def _check_root_elements(xml_content: str, result: ValidationResult):
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as exc:
            result.errors.append(f"XML 解析失败：{exc}")
            result.valid = False
            return

        if XmlValidator._local_tag(root) != "Document":
            result.errors.append("XML 缺少 <Document> 根元素")
            result.valid = False

        has_screen = any(XmlValidator._local_tag(e) == "Screen" for e in root.iter())
        result.stats["screen_nodes"] = 1 if has_screen else 0
        if not has_screen:
            result.errors.append("XML 未找到 Screen 节点")
            result.valid = False

    @staticmethod
    def _check_mt_regex_fallback(xml_content: str, result: ValidationResult):
        matches = list(re.finditer(r'<[^>]*MultilingualText\b[^>]*>(.*?)</[^>]*MultilingualText>', xml_content, re.S | re.I))
        result.stats["multilingual_text_nodes"] = len(matches)
        for m in matches:
            content = m.group(1)
            line_no = xml_content.count("\n", 0, m.start()) + 1
            if re.search(r'<\s*ID\b', content, re.I):
                result.errors.append(f"MultilingualText 内发现非法 <ID> 子元素（第 {line_no} 行）")
                result.valid = False
            if _HTML_PATTERN.search(content):
                result.errors.append(f"MultilingualText 节点内容包含 HTML 标签（第 {line_no} 行）")
                result.valid = False

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    @staticmethod
    def _html_tag_name(raw_tag: str) -> str:
        return raw_tag.strip().lstrip('<').lstrip('/').split()[0].split('>')[0].rstrip('/').lower()

    @staticmethod
    def _has_rich_body_p(text_elem: ET.Element) -> bool:
        has_body = False
        has_p = False
        for e in text_elem.iter():
            tag = XmlValidator._local_tag(e)
            if tag == "body":
                has_body = True
            elif tag == "p":
                has_p = True
        return has_body and has_p

    @staticmethod
    def _local_tag(elem: ET.Element) -> str:
        tag = elem.tag
        if "}" in tag:
            tag = tag.rsplit("}", 1)[-1]
        if "." in tag:
            tag = tag.rsplit(".", 1)[-1]
        return tag

    @staticmethod
    def _is_v16_multilingual_text(mt: ET.Element) -> bool:
        if "ID" in mt.attrib or "CompositionName" in mt.attrib:
            return True
        return any(XmlValidator._local_tag(e) == "MultilingualTextItem" for e in mt.iter())

    @staticmethod
    def _approx_line(xml_content: str, elem: ET.Element) -> int:
        tag = XmlValidator._local_tag(elem)
        patterns = []
        if tag == "Screen":
            patterns.append(r'<[^>]*Screen\b')
        elif tag == "MultilingualText":
            mid = elem.get("ID")
            if mid:
                patterns.append(r'<[^>]*MultilingualText\b[^>]*\bID="' + re.escape(mid) + r'"')
            cname = elem.get("CompositionName")
            if cname:
                patterns.append(r'<[^>]*MultilingualText\b[^>]*\bCompositionName="' + re.escape(cname) + r'"')
            patterns.append(r'<[^>]*MultilingualText\b')
        else:
            patterns.append(r'<[^>]*' + re.escape(tag) + r'\b')
        for pat in patterns:
            m = re.search(pat, xml_content)
            if m:
                return xml_content.count("\n", 0, m.start()) + 1
        return 1


# ========================================================================
# V5.0: XML 类别守卫 — 防止错误 XML 类型传入 Openness Import
# ========================================================================

def validate_xml_class_for_import_target(xml_path: str, target_kind: str):
    """校验 XML 文件中的对象类别是否与导入目标匹配。

    在调用 TagComposition.Import / Screen.Import / PLC Blocks.Import 之前
    调用此函数，避免将错误类别的 XML 传给 Openness API。

    参数:
        xml_path: XML 文件路径。
        target_kind: 导入目标类型，支持:
            - 'hmi_tags':   HMI TagComposition / TagTable
            - 'hmi_screen': HMI ScreenFolder
            - 'plc_blocks': PLC Software Blocks

    异常:
        ValueError: 如果 XML 类别与目标不匹配，抛出带有 [TAG_XML_WRONG_CLASS]
                    前缀的详细异常。

    检测内容:
        对于 'hmi_tags':
          - 检查 XML 中是否包含 <SW.Blocks> 元素 → 拒绝
          - 检查 XML 中是否包含 PLC 对象类型 (OB, FB, FC, DB) → 拒绝
          - 只允许 SW.Tag, SW.TagTable, Hmi.Tag.* 等 HMI 标签相关类型
        对于 'hmi_screen':
          - 检查根对象是否为 Screen 相关类型
        对于 'plc_blocks':
          - 允许 SW.Blocks
    """
    import os

    if not os.path.isfile(xml_path):
        raise ValueError(f"[TAG_XML_WRONG_CLASS] XML 文件不存在: {xml_path}")

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except ET.ParseError as e:
        raise ValueError(f"[TAG_XML_WRONG_CLASS] XML 解析失败: {e}") from e

    # 提取 XML 内容字符串用于正则检测
    with open(xml_path, "r", encoding="utf-8-sig", errors="ignore") as f:
        xml_content = f.read()

    def _local(tag: str) -> str:
        if "}" in tag:
            tag = tag.rsplit("}", 1)[-1]
        if "." in tag:
            tag = tag.rsplit(".", 1)[-1]
        return tag

    def _has_plc_block_indicators(content: str) -> tuple[bool, str, int]:
        """检测 XML 中是否包含 PLC 软件块指示器。返回 (found, type_name, line)。

        自动跳过 XML 注释中的匹配，避免注释中的 SW.Blocks 引用导致误报。
        """
        plc_patterns = [
            (r'<SW\.Blocks[>\s]', "SW.Blocks"),
            (r'Class="Siemens\.Engineering\.SW\.Blocks"', "Siemens.Engineering.SW.Blocks"),
            (r'<SW\.Blocks\b', "SW.Blocks"),
            (r'Siemens\.Engineering\.SW\.Blocks', "Siemens.Engineering.SW.Blocks"),
            (r'<OB\b[^>]*/>', "OB (Organization Block)"),
            (r'<FB\b[^>]*/>', "FB (Function Block)"),
            (r'<FC\b[^>]*/>', "FC (Function)"),
            (r'<DB\b[^>]*/>', "DB (Data Block)"),
        ]

        # 逐行检测，跳过注释行中的匹配
        lines = content.split("\n")
        in_comment = False
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # 检测注释边界
            if stripped.startswith("<!--"):
                in_comment = True
            if in_comment:
                if "-->" in stripped:
                    in_comment = False
                continue
            # 不在注释中 → 正常检测
            for pattern, type_name in plc_patterns:
                if re.search(pattern, line):
                    return True, type_name, i
        return False, "", 0

    def _has_hmi_tag_indicators(content: str) -> bool:
        """检测 XML 中是否包含 HMI 标签元素。"""
        hmi_patterns = [
            r'<SW\.Tag\b',
            r'<SW\.TagTable\b',
            r'Hmi\.Tag\.',
            r'<SW\.TextList\b',
        ]
        for pattern in hmi_patterns:
            if re.search(pattern, content):
                return True
        return False

    # 检查 Document 的 xmlns 命名空间
    ns = root.get("xmlns", "")
    root_local = _local(root.tag)

    if root_local != "Document":
        raise ValueError(
            f"[TAG_XML_WRONG_CLASS] XML 根元素不是 Document: '{root_local}'"
        )

    if target_kind == "hmi_tags":
        # 检查 PLC blocks 指示器
        has_plc, plc_type, line_no = _has_plc_block_indicators(xml_content)
        if has_plc:
            # 提取 SW.Blocks 的 ID 属性
            simatic_id = ""
            m = re.search(r'<SW\.Blocks\s+ID="([^"]*)"', xml_content)
            if m:
                simatic_id = m.group(1)
            raise ValueError(
                f"[TAG_XML_WRONG_CLASS] 当前导入目标是 HMI TagComposition，"
                f"但 XML 类型是 {plc_type}，请检查变量生成器和导入路径。\n"
                f"  expected=HMI Tag XML\n"
                f"  actual={plc_type}\n"
                f"  target=Siemens.Engineering.Hmi.Tag.TagComposition.Import\n"
                f"  failed_xml_path={xml_path}\n"
                f"  line={line_no}\n"
                f"  simatic_ml_id={simatic_id}"
            )

        # 检查是否包含任何 HMI tag 元素 — 如果没有且不是 PLC blocks，警告
        if not _has_hmi_tag_indicators(xml_content):
            # 提第一个非 Engineering 的子元素作为诊断
            first_class = "Unknown"
            first_line = 1
            for elem in root:
                if _local(elem.tag) != "Engineering":
                    first_class = _local(elem.tag)
                    # 找到对应行号
                    raw = ET.tostring(elem, encoding="unicode")
                    m = re.search(re.escape(raw[:50]), xml_content)
                    if m:
                        first_line = xml_content.count("\n", 0, m.start()) + 1
                    break
            raise ValueError(
                f"[TAG_XML_WRONG_CLASS] XML 中未找到 HMI Tag 元素 (SW.Tag/SW.TagTable)。"
                f"  first_element={first_class} at line {first_line}\n"
                f"  failed_xml_path={xml_path}"
            )

    elif target_kind == "hmi_screen":
        # V5.0: 先检查 SW.Blocks，再检查 Screen 节点
        # 顺序重要：含 SW.Blocks 的 XML 即使有 Screen 也是错误的
        has_plc, plc_type, line_no = _has_plc_block_indicators(xml_content)
        if has_plc:
            raise ValueError(
                f"[TAG_XML_WRONG_CLASS] Screen XML 不应包含 PLC Blocks 类型 {plc_type} "
                f"(第 {line_no} 行)。\n"
                f"  failed_xml_path={xml_path}"
            )

        has_screen = any(
            _local(e.tag) == "Screen"
            for e in root.iter()
        )
        if not has_screen:
            raise ValueError(
                f"[TAG_XML_WRONG_CLASS] 当前导入目标是 HMI ScreenFolder，"
                f"但 XML 中未找到 Screen 节点。\n"
                f"  failed_xml_path={xml_path}"
            )

    elif target_kind == "plc_blocks":
        # PLC blocks 允许 SW.Blocks，但应该检查是否真的包含 PLC 块
        has_plc, plc_type, line_no = _has_plc_block_indicators(xml_content)
        if not has_plc:
            raise ValueError(
                f"[TAG_XML_WRONG_CLASS] 当前导入目标是 PLC Blocks，"
                f"但 XML 中未找到 SW.Blocks 或 PLC 块元素。\n"
                f"  failed_xml_path={xml_path}"
            )

    else:
        raise ValueError(
            f"[TAG_XML_WRONG_CLASS] 未知的导入目标类型: '{target_kind}'。"
            f" 支持: hmi_tags, hmi_screen, plc_blocks"
        )


def validate_for_import_target(xml_path: str, target: str = "hmi_tags"):
    """目标感知的 XML 校验 — 比 validate_xml_class_for_import_target 更全面。

    除了检查 XML 类别，还进行目标特定的额外校验:

    target='hmi_tags':
      - 不含 SW.Blocks（委托 validate_xml_class_for_import_target）
      - 根对象 class 属于 HMI Tag / HMI TagTable / HMI TagFolder 相关类型
      - 所有 tag 名唯一
      - tag 数据类型可映射
      - 不包含画面对象
      - 不包含 PLC blocks

    target='hmi_screen':
      - 检查画面类
      - 委托 validate_xml_class_for_import_target

    target='plc_blocks':
      - 允许 SW.Blocks
      - 委托 validate_xml_class_for_import_target

    参数:
        xml_path: XML 文件路径
        target: 导入目标类型

    返回:
        ValidationResult 对象

    异常:
        不抛出异常，所有问题通过 ValidationResult.errors 报告。
    """
    # 第一步：类别守卫
    try:
        validate_xml_class_for_import_target(xml_path, target)
    except ValueError as e:
        result = ValidationResult()
        result.valid = False
        result.errors.append(str(e))
        return result

    # 第二步：目标特定校验
    result = ValidationResult()

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except ET.ParseError as e:
        result.valid = False
        result.errors.append(f"XML 解析失败: {e}")
        return result

    def _local(tag: str) -> str:
        if "}" in tag:
            tag = tag.rsplit("}", 1)[-1]
        if "." in tag:
            tag = tag.rsplit(".", 1)[-1]
        return tag

    if target == "hmi_tags":
        # 收集所有 tag 名称
        tag_names = []
        for elem in root.iter():
            if _local(elem.tag) == "Tag":
                for child in elem:
                    if _local(child.tag) == "AttributeList":
                        for attr in child:
                            if _local(attr.tag) == "Name" and attr.text:
                                tag_names.append(attr.text.strip())

        # 检查 tag 名唯一
        if len(tag_names) != len(set(tag_names)):
            duplicates = [n for n in tag_names if tag_names.count(n) > 1]
            result.errors.append(
                f"HMI Tag XML 中存在重复变量名: {sorted(set(duplicates))}"
            )
            result.valid = False

        # 检查是否有画面对象
        has_screen = any(
            _local(e.tag) == "Screen"
            for e in root.iter()
        )
        if has_screen:
            result.errors.append(
                "HMI Tag XML 中不应包含 Screen 画面对象"
            )
            result.valid = False

        # 检查是否有 VBScript 对象
        has_script = any(
            _local(e.tag) in ("Script", "VBScript")
            for e in root.iter()
        )
        if has_script:
            result.errors.append(
                "HMI Tag XML 中不应包含 Script/VBScript 对象"
            )
            result.valid = False

    elif target == "hmi_screen":
        # 检查 screen 基本属性
        for elem in root.iter():
            if _local(elem.tag) == "Screen":
                name = elem.get("Name", "")
                if not name:
                    result.errors.append("Screen 元素缺少 Name 属性")
                    result.valid = False

    return result

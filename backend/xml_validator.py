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
            return tag.rsplit("}", 1)[-1]
        if "." in tag:
            return tag.rsplit(".", 1)[-1]
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

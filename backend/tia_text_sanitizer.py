# -*- coding: utf-8 -*-
"""
TIA Portal 文本安全清洗器（兼容层）
=====================================

⚠️ 此模块已重构为管线架构。核心功能现在位于：
  - backend.text_normalizer.TextNormalizer    — 文本规范化（管线第一层）
  - backend.multilingual_text_builder         — MultilingualText 构建（管线第二层）
  - backend.xml_validator.XmlValidator        — 导入前校验（管线第四层）

本文件保留以下兼容接口：
  - sanitize_tia_text()    → 委托给 TextNormalizer.normalize()
  - sanitize_ir_text_fields()  → 委托给 TextNormalizer.normalize_ir()
  - _FORBIDDEN_HTML_TAGS   → 保留引用（旧代码仍可使用）
  - lint_xml_content()     → 委托给 XmlValidator.validate()
  - _rebuild_multilingual_text_nodes()  → 委托给 MultilingualTextBuilder
  - lint_and_repair_xml()  → 保留（组合上述二者）

建议新代码直接使用 backend.text_normalizer / backend.xml_validator 等新模块。
"""
import re
from .text_normalizer import TextNormalizer

# 保留 _FORBIDDEN_HTML_TAGS 引用（旧代码依赖此变量名）
_FORBIDDEN_HTML_TAGS = re.compile(
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


def sanitize_tia_text(text: str) -> str:
    """清洗文本，确保兼容 TIA Portal XML（委托给 TextNormalizer.normalize）。

    ⚠️ 兼容接口：新代码请使用 TextNormalizer.normalize()。
    """
    return TextNormalizer.normalize(text)


def sanitize_ir_text_fields(ir: dict) -> dict:
    """遍历 IR 对象中所有文本字段，执行安全清洗（委托给 TextNormalizer.normalize_ir）。

    ⚠️ 兼容接口：新代码请使用 TextNormalizer.normalize_ir()。
    """
    return TextNormalizer.normalize_ir(ir)


# ========================================================================
# XML Lint 校验器 — 导入前扫描（增强版）
# ========================================================================

def lint_xml_content(xml_content: str) -> dict:
    """在 Import 前扫描 XML（委托给 XmlValidator.validate）。

    ⚠️ 兼容接口：新代码请使用 XmlValidator.validate()。
    """
    from .xml_validator import XmlValidator
    return XmlValidator.validate(xml_content).to_dict()


def _rebuild_multilingual_text_nodes(xml_content: str) -> tuple:
    """使用 XML DOM 安全重建所有 MultilingualText 节点（委托给 MultilingualTextBuilder）。

    ⚠️ 兼容接口：新代码请使用 MultilingualTextBuilder.rebuild_element()。
    """
    import xml.etree.ElementTree as ET
    from .multilingual_text_builder import MultilingualTextBuilder

    repair_log = []
    decl_match = __import__('re').match(r'(<\?xml[^?]*\?>\s*)', xml_content)
    declaration = decl_match.group(1) if decl_match else ""

    for m in __import__('re').finditer(r'xmlns(?::(\w+))?="([^"]+)"', xml_content[:4096]):
        prefix = m.group(1) or ""
        uri = m.group(2)
        if prefix:
            ET.register_namespace(prefix, uri)
        else:
            ET.register_namespace("", uri)

    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        repair_log.append(f"XML 解析失败，跳过 MultilingualText DOM 重建：{e}")
        return xml_content, repair_log

    builder = MultilingualTextBuilder()
    count = 0
    for mt_elem in list(root.iter()):
        if MultilingualTextBuilder._local_tag(mt_elem) in ("MultilingualText",):
            try:
                builder.rebuild_element(mt_elem)
                count += 1
            except Exception:
                pass

    if count > 0:
        repair_log.append(
            f"DOM 级重建了 {count} 个 MultilingualText 节点为 TIA 标准结构"
        )

    result = ET.tostring(root, encoding="unicode")
    if declaration and not result.startswith("<?"):
        result = declaration.rstrip() + "\n" + result

    return result, repair_log


def lint_and_repair_xml(xml_content: str) -> tuple:
    """扫描并自动修复 XML（委托给管线各层）。

    ⚠️ 兼容接口：新代码请使用 TextNormalizer + ScreenNumberAllocator + MultilingualTextBuilder。
    """
    from .text_normalizer import TextNormalizer

    repaired = xml_content

    # 1. 文本级 HTML 标签移除 + 控制字符移除
    repaired, clean_report = TextNormalizer.normalize_xml_content(repaired)

    # 2. Number 节点删除
    from .screen_number_allocator import ScreenNumberAllocator
    repaired = ScreenNumberAllocator().remove_number_nodes(repaired)

    # 3. MultilingualText DOM 级重建
    repaired, mt_log = _rebuild_multilingual_text_nodes(repaired)

    # 4. 重新校验
    lint_result = lint_xml_content(repaired)

    return repaired, lint_result

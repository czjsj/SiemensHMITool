# -*- coding: utf-8 -*-
"""
Text Normalization Layer — TIA HMI XML 导入管线第一层
========================================================

职责：清洗所有即将写入 TIA XML 的文本字段，保证不含 HTML/Markdown/控制字符。

对应提示词规范中的 Normalize 函数：
  string Normalize(string input)
  {
      input = WebUtility.HtmlDecode(input);
      input = Regex.Replace(input, "<.*?>", "");
      input = new string(input.Where(c => !char.IsControl(c)).ToArray());
      return input.Trim();
  }

⚠️ 关键约束：
  - 只清洗文本内容，绝不修改 XML 结构
  - 只匹配已知 HTML 标签名，绝不使用通配 <[^>]+>（会误删 XML 标签）
  - 不清洗合法 XML 实体引用和 XML 结构标签
  - 所有返回结果保证 TIA Portal MultilingualText 兼容

这是整个管线的最底层，所有上游模块（MultilingualTextBuilder / SimaticML Generator
/ Template XML Generator）在写入文本前都必须经过此类清洗。
"""
import re

# ============================================================================
# 已知禁止的 HTML/Markdown 标签名（只匹配标签名，不匹配 XML 结构标签）
# ============================================================================
_FORBIDDEN_HTML_PATTERN = re.compile(
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

# 在完整 TIA HMI XML 中，<body><p>...</p></body> 是 WinCC Advanced/Comfort
# 对按钮/文本显示属性使用的合法富文本片段，不能在 XML 级清洗中删除。
# 注意：TextNormalizer.normalize(text) 仍会把用户输入字符串中的 body/p 去掉，
# 这里仅针对已经形成 XML 结构的导入文件。
_ALLOWED_TIA_RICH_TAGS_IN_XML = {"body", "p"}

# HTML 实体解码映射
_HTML_ENTITIES = {
    "&nbsp;": " ",   "&amp;": "&",    "&lt;": "<",
    "&gt;": ">",     "&quot;": '"',   "&apos;": "'",
    "&#160;": " ",   "&ldquo;": '"',  "&rdquo;": '"',
    "&lsquo;": "'",  "&rsquo;": "'",  "&mdash;": "—",
    "&ndash;": "–",  "&hellip;": "…", "&laquo;": "«",
    "&raquo;": "»",  "&bull;": "•",   "&copy;": "©",
    "&reg;": "®",    "&trade;": "™",  "&deg;": "°",
    "&plusmn;": "±",
}

# XML 1.0 禁止的控制字符范围
_ILLEGAL_CONTROL = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F]')


class TextNormalizer:
    """文本规范化器 — TIA HMI XML 导入管线第一层。

    所有将被写入 TIA XML 中 <MultilingualText> / <DisplayName> / 属性值
    等文本字段的字符串，在写入前都必须通过 normalize() 清洗。

    使用方式：
        normalizer = TextNormalizer()
        clean_text = normalizer.normalize(raw_text)

    类方法版本（兼容旧代码）：
        from backend.text_normalizer import TextNormalizer
        clean = TextNormalizer.normalize_static(raw_text)
    """

    @staticmethod
    def normalize(text: str) -> str:
        """清洗文本，确保兼容 TIA Portal XML。

        处理流水线（与提示词中的 Normalize 完全对应）：
          1. 空值/None 处理
          2. HTML 实体解码（&nbsp; → 空格 等）
          3. 数字/十六进制实体解码（&#160; → 空格 等）
          4. HTML 注释移除（<!-- ... -->）
          5. 已知 HTML 标签移除（仅限标签名匹配，绝不使用通配 <[^>]+>）
          6. 非法控制字符移除（XML 1.0 不允许的字符）
          7. 换行/制表符统一为空格
          8. 连续空白压缩
          9. Trim 首尾空白

        参数:
            text: 原始文本（可能含 HTML/Markdown 污染）。

        返回:
            清洗后的纯文本字符串。空输入返回 ""。

        >>> TextNormalizer.normalize('电机控制<body><p>Text</p></body>')
        '电机控制Text'
        >>> TextNormalizer.normalize('<div>速度设定</div>')
        '速度设定'
        >>> TextNormalizer.normalize(None)
        ''
        """
        if text is None:
            return ""
        if not isinstance(text, str):
            text = str(text)

        # Step 1: 解码 HTML 实体
        for entity, char in _HTML_ENTITIES.items():
            text = text.replace(entity, char)

        # Step 2: 解码 &#NNNN; 数字实体
        def _decode_numeric(m):
            try:
                return chr(int(m.group(1)))
            except (ValueError, OverflowError):
                return m.group(0)

        text = re.sub(r'&#(\d+);', _decode_numeric, text)

        # Step 3: 解码 &#xHH; 十六进制实体
        def _decode_hex(m):
            try:
                return chr(int(m.group(1), 16))
            except (ValueError, OverflowError):
                return m.group(0)

        text = re.sub(r'&#[xX]([0-9a-fA-F]+);', _decode_hex, text)

        # Step 4: 去除 HTML 注释
        text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)

        # Step 5: 去除已知 HTML 标签（仅限标签名匹配）
        text = _FORBIDDEN_HTML_PATTERN.sub('', text)

        # Step 6: 去除非法控制字符（保留 tab/newline/cr 后续统一）
        text = ''.join(
            c for c in text
            if c == '\t' or c == '\n' or c == '\r' or ord(c) >= 0x20
        )

        # Step 7: 统一换行和制表符为空格
        text = text.replace('\r\n', ' ').replace('\r', ' ').replace('\n', ' ')
        text = text.replace('\t', ' ')

        # Step 8: 压缩连续空白
        text = re.sub(r' {2,}', ' ', text)

        # Step 9: Trim
        return text.strip()

    @staticmethod
    def normalize_xml_content(xml_string: str) -> tuple:
        """对完整 XML 字符串执行文本级安全清洗。

        与 normalize() 的区别：此方法仅清洗 XML 文本内容中的 HTML 标签和控制字符，
        完全不触碰 XML 结构标签（如 <MultilingualText>、<Text Language="zh-CN"> 等）。

        这是 Import 前预处理的文本清洗步骤，不涉及 DOM 操作。

        参数:
            xml_string: 完整的 XML 字符串。

        返回:
            (cleaned_xml: str, report: dict)
            report 包含 {"html_removed": N, "controls_removed": N}
        """
        report = {"html_removed": 0, "controls_removed": 0}

        # 仅清洗已知 HTML 标签名。TIA 合法富文本 <body>/<p> 在完整 XML 中保留，
        # 否则 TextOff/TextOn 会被清成纯文本并触发 TIA 的 invalid format。
        removed_tags = []

        def _replace_html_tag(match):
            raw = match.group(0)
            tag = raw.strip().lstrip('<').lstrip('/').split()[0].split('>')[0].rstrip('/').lower()
            if tag in _ALLOWED_TIA_RICH_TAGS_IN_XML:
                return raw
            removed_tags.append(tag)
            return ''

        xml_string = _FORBIDDEN_HTML_PATTERN.sub(_replace_html_tag, xml_string)
        if removed_tags:
            report["html_removed"] = len(removed_tags)
            report["html_tags_found"] = sorted(set(removed_tags))

        # 移除非法控制字符
        control_matches = list(_ILLEGAL_CONTROL.finditer(xml_string))
        if control_matches:
            report["controls_removed"] = len(control_matches)
            xml_string = _ILLEGAL_CONTROL.sub('', xml_string)

        return xml_string, report

    @staticmethod
    def is_clean(text: str) -> bool:
        """快速检查文本是否已经清洗过（无 HTML、无控制字符）。

        返回 True 表示文本安全，可直接写入 XML。
        返回 False 表示需要 normalize()。
        """
        if not text:
            return True
        if _FORBIDDEN_HTML_PATTERN.search(text):
            return False
        if _ILLEGAL_CONTROL.search(text):
            return False
        if any(ord(c) < 0x20 and c not in '\t\n\r' for c in text):
            return False
        return True

    @staticmethod
    def normalize_ir(ir: dict) -> dict:
        """遍历 IR 对象中所有文本字段，执行安全清洗（原地修改）。

        清洗范围：
          - meta.title, meta.screen_name, meta.description
          - objects[*].text, objects[*].label, objects[*].unit, objects[*].id
          - tags[*].name, tags[*].comment, tags[*].address
          - text_lists[*].name, text_lists[*].entries[*].text
          - scripts[*].name, scripts[*].purpose, scripts[*].code（代码仅去HTML标签）

        返回清洗后的 IR（原地修改 + 返回引用）。
        """
        if not ir:
            return ir

        # meta 字段
        meta = ir.get("meta", {})
        for key in ("title", "screen_name", "description"):
            if key in meta and isinstance(meta[key], str):
                meta[key] = TextNormalizer.normalize(meta[key])

        # 对象字段
        for obj in ir.get("objects", []) or []:
            for key in ("text", "label", "unit", "id"):
                if key in obj and isinstance(obj[key], str):
                    obj[key] = TextNormalizer.normalize(obj[key])

        # 标签字段
        for tag in ir.get("tags", []) or []:
            for key in ("name", "comment", "address"):
                if key in tag and isinstance(tag[key], str):
                    tag[key] = TextNormalizer.normalize(tag[key])

        # 文本列表
        for tl in ir.get("text_lists", []) or []:
            if "name" in tl and isinstance(tl["name"], str):
                tl["name"] = TextNormalizer.normalize(tl["name"])
            for entry in tl.get("entries", []) or []:
                if "text" in entry and isinstance(entry["text"], str):
                    entry["text"] = TextNormalizer.normalize(entry["text"])

        # 脚本（仅去 HTML 标签，保留代码结构）
        for script in ir.get("scripts", []) or []:
            for key in ("name", "purpose"):
                if key in script and isinstance(script[key], str):
                    script[key] = TextNormalizer.normalize(script[key])
            if "code" in script and isinstance(script["code"], str):
                script["code"] = _FORBIDDEN_HTML_PATTERN.sub('', script["code"]).strip()

        return ir

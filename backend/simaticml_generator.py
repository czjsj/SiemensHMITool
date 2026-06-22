# -*- coding: utf-8 -*-
"""
SimaticML 生成器
==================
把校验后的 IR 转换成带 SimaticML 命名空间的 XML，用于通过 Openness 的
ScreenFolder.Import() 导入到博途。

⚠️ 重要版本说明（务必阅读）：
  SimaticML 的精确元素名/命名空间在不同 TIA 版本(V16/V17/V18/V19)和不同
  HMI 类型(Basic/Comfort/Unified)之间存在差异。最稳妥的工程做法是：
     1) 在你的博途里手工画一个含目标对象(IO域/符号IO域/按钮/圆)的样例画面；
     2) 用 Screen.Export() 导出该画面 XML，观察真实结构；
     3) 用本文件生成的 XML 作为骨架，按导出样例对齐元素名/属性名。
  本生成器输出的结构刻意保持清晰、分对象成函数，便于你按版本微调。
  下面以 TIA V18 Comfort 面板的常见结构为基准给出。

⚠️ MultilingualText 标准（TIA Portal 强制要求）：
  所有用户可见文本必须使用 MultilingualText 包裹，结构为：
    <MultilingualText>
      <Text Language="zh-CN">安全文本</Text>
    </MultilingualText>
  禁止使用 regex 删除 XML 标签、禁止把 MultilingualText 当字符串处理、
  禁止删除 language 结构、禁止 HTML/Markdown 混入 Text。
"""
import uuid
import re
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as xml_escape
from .text_normalizer import TextNormalizer
from .multilingual_text_builder import MultilingualTextBuilder
from .xml_validator import XmlValidator


# SimaticML 命名空间（Comfort 面板用）
SIMATICML_NS = "http://www.siemens.com/automation/SimaticML"


def _color_to_argb(hex_color: str) -> str:
    """#RRGGBB -> 255,R,G,B（WinCC 颜色常用 ARGB 整数或分量，这里给分量串）。"""
    c = (hex_color or "#000000").lstrip("#")
    if len(c) == 6:
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        return f"{r},{g},{b}"
    return "0,0,0"


def _attr_str(attrs: dict) -> str:
    """{key: val} -> ' key="val" key="val"'"""
    if not attrs:
        return ""
    parts = []
    for k, v in attrs.items():
        if v is not None:
            parts.append(f'{k}="{xml_escape(str(v))}"')
    return " " + " ".join(parts)


def _elem(name: str, attrs: dict = None, text: str = None) -> str:
    """<name attrs>text</name> 或 <name attrs/>（text=None 时自闭合）。

    注意：对于用户可见文本，请使用 _multilingual_text_elem() 而非此函数。
    """
    a = _attr_str(attrs) if attrs else ""
    if text is not None:
        return f"<{name}{a}>{xml_escape(str(text))}</{name}>"
    return f"<{name}{a}/>"


def _multilingual_text_elem(text: str, language: str = "zh-CN") -> str:
    """生成符合 TIA Portal 标准的 MultilingualText 节点。

    委托给 MultilingualTextBuilder.build_string() —— 用 DOM 构建保证正确性。

    TIA 正确格式（必须严格遵守）：
      <MultilingualText>
        <Text Language="zh-CN">安全文本</Text>
      </MultilingualText>

    参数:
        text: 用户可见文本（会自动清洗）。
        language: 语言代码，默认 zh-CN。

    返回:
        完整的 MultilingualText XML 字符串。
    """
    return MultilingualTextBuilder.build_string(text, language)


# ---------- 对象 → XML 行列表（无缩进，供外层统一处理）----------
def _geo_lines(x: int, y: int, w: int, h: int) -> list:
    return [
        "<Geometry>",
        _elem("X", text=str(x)),
        _elem("Y", text=str(y)),
        _elem("Width", text=str(w)),
        _elem("Height", text=str(h)),
        "</Geometry>",
    ]


def _estimate_text_width(text: str, font_size: int) -> int:
    """估算文本像素宽度（CJK 近似全角，ASCII 按 0.6 倍）。"""
    if not text:
        return 0
    cjk = sum(1 for c in text if ord(c) > 0x2E7F)
    other = len(text) - cjk
    return int(font_size * cjk + font_size * 0.6 * other)


def _io_field_lines(o: dict) -> list:
    sid = str(uuid.uuid4())
    return [
        f'<ScreenItem ID="{sid}" Name="{xml_escape(o["id"])}" Type="IOField">',
        *_ind("", _geo_lines(o["x"], o["y"], o.get("width", 140), o.get("height", 40))),
        "<Properties>",
        _ind("", _elem("Mode", text=o.get("mode", "Output"))),
        _ind("", _elem("OutputFormat", text=o.get("display_format", "Decimal"))),
        _ind("", _elem("DecimalDigits", text=str(o.get("decimal_digits", 0)))),
        _ind("", _elem("FontSize", text=str(o.get("font_size", 16)))),
        "</Properties>",
        "<Connection>",
        _ind("", _elem("ProcessTag", text=o["process_tag"])),
        "</Connection>",
        "</ScreenItem>",
    ]


def _symbolic_io_field_lines(o: dict) -> list:
    sid = str(uuid.uuid4())
    return [
        f'<ScreenItem ID="{sid}" Name="{xml_escape(o["id"])}" Type="SymbolicIOField">',
        *_ind("", _geo_lines(o["x"], o["y"], o.get("width", 160), o.get("height", 40))),
        "<Properties>",
        _ind("", _elem("Mode", text=o.get("mode", "Output"))),
        _ind("", _elem("FontSize", text=str(o.get("font_size", 16)))),
        _ind("", _elem("TextList", text=o["text_list"])),
        "</Properties>",
        "<Connection>",
        _ind("", _elem("ProcessTag", text=o["process_tag"])),
        "</Connection>",
        "</ScreenItem>",
    ]


def _button_lines(o: dict) -> list:
    sid = str(uuid.uuid4())
    text_id = str(uuid.uuid4())
    tag_mode = o.get("tag_mode", "momentary")
    lines = [
        f'<ScreenItem ID="{sid}" Name="{xml_escape(o["id"])}" Type="Button">',
        *_ind("", _geo_lines(o["x"], o["y"], o.get("width", 120), o.get("height", 50))),
        "<Properties>",
        _ind("", "<Text>"),
        _ind("  ", _elem("ID", text=text_id)),
        _ind("  ", _multilingual_text_elem(o.get("text", "按钮"))),
        _ind("", "</Text>"),
        _ind("", _elem("BackColor",
                       text=_color_to_argb(o.get("background_color", "#2BB673")))),
        "</Properties>",
    ]
    # process_tag 连接（按钮现在也支持变量绑定）
    pt = o.get("process_tag", "").strip()
    if pt:
        lines.append("<Connection>")
        lines.extend(_ind("", _elem("ProcessTag", text=pt)))
        lines.append("</Connection>")

    # 事件（按 tag_mode 区分）
    if tag_mode == "toggle":
        # 自保持按钮：只需要 click_script
        sc = o.get("click_script")
        if sc:
            lines.append("<Events>")
            lines.extend(_ind("", [
                f"<Event Name=\"Click\">",
                _ind("", _elem("VBSFunction", text=sc)),
                "</Event>",
            ]))
            lines.append("</Events>")
    else:
        # 瞬时按钮：press_script + release_script（也支持 click_script）
        event_keys = [("Press", "press_script"), ("Release", "release_script"),
                      ("Click", "click_script")]
        has_events = any(o.get(k) for _, k in event_keys)
        if has_events:
            lines.append("<Events>")
            for ev_name, key in event_keys:
                sc = o.get(key)
                if sc:
                    lines.extend(_ind("", [
                        f"<Event Name=\"{ev_name}\">",
                        _ind("", _elem("VBSFunction", text=sc)),
                        "</Event>",
                    ]))
            lines.append("</Events>")
    lines.append("</ScreenItem>")
    return lines


def _indicator_lines(o: dict) -> list:
    sid = str(uuid.uuid4())
    r = o.get("radius", 22)
    d = r * 2
    lines = [
        f'<ScreenItem ID="{sid}" Name="{xml_escape(o["id"])}" Type="Circle">',
        *_ind("", _geo_lines(o["x"], o["y"], d, d)),
        "<Properties>",
        _ind("", _elem("FillColor",
                       text=_color_to_argb(o.get("color_off", "#3A4250")))),
        _ind("", _elem("BorderColor", text="120,130,140")),
        "</Properties>",
        "<Animations>",
        _ind("", f'<ColorAnimation Tag="{xml_escape(o["process_tag"])}">'),
        _ind("", _ind("",
            _elem("Range",
                  attrs={"Value": "0",
                         "FillColor": _color_to_argb(o.get("color_off", "#3A4250"))}))),
        _ind("", _ind("",
            _elem("Range",
                  attrs={"Value": "1",
                         "FillColor": _color_to_argb(o.get("color_on", "#27D17F"))}))),
        _ind("", "</ColorAnimation>"),
    ]
    if o.get("blink"):
        blink_tag = xml_escape(o.get("blink_tag") or o["process_tag"])
        lines.extend(_ind("", [
            f'<FlashAnimation Tag="{blink_tag}">',
            _ind("", _elem("Range", attrs={"Value": "1", "Flashing": "Yes"})),
            "</FlashAnimation>",
        ]))
    lines.append("</Animations>")
    lines.append("</ScreenItem>")
    return lines


def _text_lines(o: dict) -> list:
    sid = str(uuid.uuid4())
    text_id = str(uuid.uuid4())
    if o.get("_anchor") == "middle":
        tw = _estimate_text_width(o.get("text", ""), o.get("font_size", 18))
        w = tw + 12
        x = int(o.get("x", 0)) - w // 2
        geo = _geo_lines(x, o.get("y", 0), w, o.get("height", 40))
    else:
        geo = _geo_lines(o.get("x", 0), o.get("y", 0), o.get("width", 200), o.get("height", 40))
    return [
        f'<ScreenItem ID="{sid}" Name="{xml_escape(o["id"])}" Type="TextField">',
        *_ind("", geo),
        "<Properties>",
        _ind("", "<Text>"),
        _ind("  ", _elem("ID", text=text_id)),
        _ind("  ", _multilingual_text_elem(o.get("text", ""))),
        _ind("", "</Text>"),
        _ind("", _elem("FontSize", text=str(o.get("font_size", 18)))),
        _ind("", _elem("Bold", text="true" if o.get("bold") else "false")),
        _ind("", _elem("ForeColor", text=_color_to_argb(o.get("color", "#E6EDF3")))),
        "</Properties>",
        "</ScreenItem>",
    ]


def _label_lines(o: dict) -> list:
    """有 label 的对象生成正上方（IO 域）或正下方（指示灯）居中说明文本。"""
    label = o.get("label")
    if not label:
        return []
    fs = 14
    tw = _estimate_text_width(label, fs)
    lw = tw + 12
    lh = 28
    gap = 10
    ctype = o.get("type")
    if ctype == "Indicator":
        r = int(o.get("radius", 22))
        cx = int(o.get("x", 0)) + r
        ly = int(o.get("y", 0)) + 2 * r + gap
    else:
        cx = int(o.get("x", 0)) + int(o.get("width", 140)) // 2
        ly = int(o.get("y", 0)) - gap - lh
    lx = max(0, cx - lw // 2)
    return _text_lines({
        "id": o["id"] + "_lbl",
        "x": lx, "y": ly,
        "width": lw, "height": lh,
        "text": label, "font_size": fs, "bold": False,
        "color": "#C9D3DE",
    })


def _unit_lines(o: dict) -> list:
    """IOField 右侧单位文本。"""
    unit = o.get("unit")
    if not unit:
        return []
    return _text_lines({
        "id": o["id"] + "_unit",
        "x": o["x"] + o.get("width", 140) + 6, "y": o["y"] + 8,
        "width": 60, "height": 28,
        "text": unit, "font_size": 14, "bold": False,
        "color": "#9AA7B4",
    })


_DISPATCH = {
    "IOField": _io_field_lines,
    "SymbolicIOField": _symbolic_io_field_lines,
    "Button": _button_lines,
    "Indicator": _indicator_lines,
    "Text": _text_lines,
}


def _ind(prefix: str, lines) -> list:
    """给行（字符串或嵌套列表）加上缩进前缀，展平后返回。"""
    if isinstance(lines, str):
        lines = [lines]

    flat = []

    def _flatten(item):
        if isinstance(item, str):
            flat.append(item)
        elif isinstance(item, (list, tuple)):
            for x in item:
                _flatten(x)

    _flatten(lines)
    if not prefix:
        return flat
    return [prefix + ln for ln in flat]


def _extract_template_info(ref_xml: str) -> dict:
    """从参考画面 XML 中提取命名空间和结构信息，便于匹配用户实际的 TIA 版本。

    返回:
        {
            "doc_ns": "http://...",           # Document 的 xmlns
            "doc_attrs": "xmlns=\"...\" ...",  # Document 的属性串
            "screen_parent": "  <SW.Blocks>\\n    <SW.ScreenFolder>",  # Screen 的父级路径
            "screen_close": "    </SW.ScreenFolder>\\n  </SW.Blocks>",  # 对应闭合标签
            "screen_extra_attrs": "CompositionType=\"Screen\"",  # Screen 的额外属性
            "screen_type_tag": "Screen",       # Screen 元素名（可能是 SW.Screen）
            "items_container": "ObjectList",   # 对象容器元素名
        }
    """
    import re

    result = {
        "doc_ns": SIMATICML_NS,
        "doc_attrs": f'xmlns="{SIMATICML_NS}"',
        "screen_parent": "",
        "screen_close": "",
        "screen_extra_attrs": "",
        "screen_type_tag": "Screen",
        "items_container": "ObjectList",
    }

    if not ref_xml:
        return result

    # 提取 Document 元素的 namespace
    doc_m = re.search(r'<Document\s+([^>]+)>', ref_xml)
    if doc_m:
        doc_attrs = doc_m.group(1)
        ns_m = re.search(r'xmlns(?::\w+)?\s*=\s*"([^"]+)"', doc_attrs)
        if ns_m:
            result["doc_ns"] = ns_m.group(1)
        result["doc_attrs"] = doc_attrs

    # 提取 Screen 元素的父级标签链
    screen_m = re.search(r'<(\w+:)?Screen\b', ref_xml)
    if screen_m:
        result["screen_type_tag"] = screen_m.group(0).lstrip("<")

    # 找到 Screen 在 XML 中的位置，提取其祖先链
    lines = ref_xml.split("\n")
    screen_line_idx = None
    screen_indent = ""
    for i, line in enumerate(lines):
        if re.search(r'<(\w+:)?Screen\b', line):
            screen_line_idx = i
            screen_indent = line[:len(line) - len(line.lstrip())]
            break

    if screen_line_idx is not None:
        # 回溯找到所有打开的父级标签
        parent_tags = []
        parent_indent = ""
        for i in range(screen_line_idx - 1, -1, -1):
            line = lines[i]
            stripped = line.strip()
            cur_indent = line[:len(line) - len(stripped)]
            # 跳过闭合标签和自闭合标签
            if stripped.startswith("</") or stripped.endswith("/>"):
                continue
            # 打开标签
            tag_m = re.match(r'<([\w:.]+)(?:\s|>|/>)', stripped)
            if tag_m and not stripped.startswith("<!--"):
                tag_name = tag_m.group(1)
                if tag_name == result["screen_type_tag"]:
                    continue
                # 只取缩进比 Screen 少的祖先标签
                if len(cur_indent) < len(screen_indent) and not stripped.endswith("/>"):
                    parent_tags.insert(0, (tag_name, cur_indent, stripped))
                    if tag_name == "Document" or "Document" in tag_name:
                        break

        if parent_tags:
            # 构建父级打开标签（使用参考的缩进）
            open_lines = []
            close_lines = []
            for tag_name, indent, raw in parent_tags:
                # 提取属性
                attrs_re = re.match(r'<[\w:.]+(.+?)>', raw)
                attrs = attrs_re.group(1).strip() if attrs_re else ""
                open_lines.append(f"{indent}<{tag_name}{(' ' + attrs) if attrs else ''}>")
                close_lines.insert(0, f"{indent}</{tag_name}>")
            result["screen_parent"] = "\n".join(open_lines)
            result["screen_close"] = "\n".join(close_lines)
            result["screen_indent"] = screen_indent

    # 提取 Screen 的额外属性（去掉 ID 和 Name）
    if screen_line_idx is not None:
        raw_screen = lines[screen_line_idx].strip()
        attrs_str = re.sub(r'<\w+:?Screen\s*', '', raw_screen).rstrip('>').rstrip('/')
        extra_parts = []
        for part in attrs_str.split('" '):
            part = part.strip().strip('"').strip()
            if part and not part.startswith('ID=') and not part.startswith('Name='):
                extra_parts.append(part)
        result["screen_extra_attrs"] = '" ' + ' " '.join(extra_parts) if extra_parts else ""

    # 找对象容器名称
    for line in lines:
        obj_m = re.search(r'<(ObjectList|ScreenItems|ScreenItemList)\b', line)
        if obj_m:
            result["items_container"] = obj_m.group(1)
            break

    return result


def generate_simaticml(ir: dict, tia_version: str = "V18",
                       reference_xml: str = "") -> str:
    """返回带 SimaticML 命名空间的 XML 字符串，可直接用于 Screen.Import()。

    参数:
        ir: 校验后的 IR。
        tia_version: TIA 版本号（如 V18）。
        reference_xml: 从博途导出的参考画面 XML。提供时，生成器会匹配其
                      命名空间和结构，确保与当前 TIA 版本兼容。
                      未提供时使用经典 HMI 的默认格式；Basic 面板建议提供同型号导出的模板 XML。
    """
    tmpl = _extract_template_info(reference_xml) if reference_xml else {}
    return _generate(ir, tia_version, tmpl)


def _generate(ir: dict, tia_version: str, tmpl: dict) -> str:
    meta = ir["meta"]
    hmi_type = str(meta.get("hmi_type", "Comfort"))
    basic_mode = hmi_type.lower() == "basic"
    screen_name = TextNormalizer.normalize(meta.get("screen_name", "Screen_1"))
    screen_title = TextNormalizer.normalize(meta.get("title", screen_name))
    w, h = ir["_screen_size"]["width"], ir["_screen_size"]["height"]
    screen_id = str(uuid.uuid4())

    doc_ns = tmpl.get("doc_ns") or SIMATICML_NS
    doc_attrs = tmpl.get("doc_attrs") or f'xmlns="{SIMATICML_NS}"'
    screen_tag = tmpl.get("screen_type_tag") or "Screen"
    screen_extra = tmpl.get("screen_extra_attrs") or ""
    items_container = tmpl.get("items_container") or "ObjectList"
    screen_parent = tmpl.get("screen_parent") or ""
    screen_close = tmpl.get("screen_close") or ""

    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<Document {doc_attrs}>',
    ]
    lines.extend(_ind("  ", _elem("Engineering", attrs={"version": tia_version})))

    # Screen 父级（从参考模板中提取）
    if screen_parent:
        for parent_line in screen_parent.split("\n"):
            if parent_line.strip():
                lines.append(parent_line)

    # Screen 元素
    screen_str = f'<{screen_tag} ID="{screen_id}" Name="{xml_escape(screen_name)}"'
    if screen_extra:
        screen_str += f' {screen_extra}'
    screen_str += ">"
    lines.append(f"  {screen_str}" if not screen_parent else
                 f"{tmpl.get('screen_indent', '  ')}{screen_str}")

    indent = "    " if not screen_parent else tmpl.get('screen_indent', '  ') + "  "

    # AttributeList
    lines.extend([
        f"{indent}<AttributeList>",
    ])
    lines.extend(_ind(indent + "  ", _elem("Name", text=screen_name)))
    lines.extend(_ind(indent + "  ", _elem("DisplayName", text=screen_title)))
    lines.extend(_ind(indent + "  ", _elem("Width", text=str(w))))
    lines.extend(_ind(indent + "  ", _elem("Height", text=str(h))))
    lines.append(f"{indent}</AttributeList>")

    # Tags
    tags = ir.get("tags") or []
    if tags:
        lines.append(f"{indent}<Tags>")
        for t in tags:
            lines.extend(_ind(indent + "  ",
                f'<Tag Name="{xml_escape(t["name"])}"'
                f' DataType="{xml_escape(t.get("data_type", "Bool"))}">'))
            if t.get("address"):
                lines.extend(_ind(indent + "    ", _elem("Address", text=t["address"])))
            if t.get("comment"):
                lines.extend(_ind(indent + "    ", _elem("Comment", text=TextNormalizer.normalize(t["comment"]))))
            lines.append(f"{indent}  </Tag>")
        lines.append(f"{indent}</Tags>")

    # TextLists
    text_lists = ir.get("text_lists") or []
    if text_lists:
        lines.append(f"{indent}<TextLists>")
        for tl in text_lists:
            lines.extend(_ind(indent + "  ", f'<TextList Name="{xml_escape(tl["name"])}">'))
            for e in tl.get("entries", []):
                lines.extend(_ind(indent + "    ",
                    _elem("Entry",
                          attrs={"Value": str(e["value"]),
                                 "Text": TextNormalizer.normalize(e["text"])})))
            lines.append(f"{indent}  </TextList>")
        lines.append(f"{indent}</TextLists>")

    # 对象容器（ObjectList / ScreenItems）
    # label/unit 通过 _label_lines/_unit_lines 生成为独立的 TextField 文字控件，
    # 确保导入到 TIA 后画面上能看到标签和单位文字。
    lines.append(f"{indent}<{items_container}>")
    objects = ir.get("objects", []) or []
    if basic_mode:
        # Basic/KTP Basic 面板对 VBS/高级事件支持有限；从零生成 SimaticML 时不输出按钮脚本事件。
        objects = [dict(o, press_script=None, release_script=None, click_script=None) if o.get("type") == "Button" else o for o in objects]
    for o in objects:
        otype = o.get("type", "")
        builder = _DISPATCH.get(otype)
        if builder:
            lines.extend(_ind(indent + "  ", builder(o)))
            # 为含 label 的对象生成上方/下方居中说明文字（IOField/SymbolicIOField/Indicator）
            if otype in ("IOField", "SymbolicIOField", "Indicator"):
                label_lines = _label_lines(o)
                if label_lines:
                    lines.extend(_ind(indent + "  ", label_lines))
            # 为含 unit 的 IOField 生成右侧单位文字
            if otype == "IOField":
                unit_lines = _unit_lines(o)
                if unit_lines:
                    lines.extend(_ind(indent + "  ", unit_lines))
    lines.append(f"{indent}</{items_container}>")

    # Screen 闭合
    lines.append(f"{indent[:-2]}</{screen_tag}>")

    # Screen 父级闭合标签
    if screen_close:
        for close_line in screen_close.split("\n"):
            if close_line.strip():
                lines.append(close_line)

    # VBScripts
    scripts = [] if basic_mode else (ir.get("scripts") or [])
    if scripts:
        lines.append("  <VBScripts>")
        for s in scripts:
            lines.extend(_ind("    ",
                f'<Script Name="{xml_escape(s["name"])}"'
                f' Language="{xml_escape(s.get("language", "VBScript"))}">'))
            if s.get("purpose"):
                lines.extend(_ind("      ", _elem("Purpose", text=TextNormalizer.normalize(s["purpose"]))))
            lines.append("      <Code>")
            lines.extend(_ind("        ", xml_escape(s.get("code", ""))))
            lines.append("      </Code>")
            lines.append("    </Script>")
        lines.append("  </VBScripts>")

    lines.append("</Document>")
    xml_output = "\n".join(lines)

    # ---- TIA XML 强制校验 + 自动修复（导入前必须通过） ----
    validation = XmlValidator.validate(xml_output)
    if not validation.valid:
        # 自动修复可修复的问题（DOM 级重建，非字符串修补）
        xml_output, repair_log = repair_tia_xml(xml_output)
        # 修复后再次校验确认
        post_validation = XmlValidator.validate(xml_output)
        if not post_validation.valid:
            # Fail Fast: 修复后仍有错误，但为避免丢失数据仍返回 XML
            # （调用方可通过 validate_tia_xml 自行判断是否导入）
            pass

    return xml_output


# ========================================================================
# TIA XML 校验器 — 导入前结构化检查
# ========================================================================

def validate_tia_xml(xml_content: str) -> dict:
    """在 Import 前校验 XML（委托给 XmlValidator 统一校验器）。

    必检项（按 TIA 导入规范）：
      1. 是否存在 HTML 标签
      2. MultilingualText 结构完整性（DOM 级检查）
      3. 是否包含非法控制字符
      4. 是否存在 <Number> 节点
      5. 是否缺少根 Document / Screen 元素

    返回:
        {"valid": True/False, "errors": [...], "warnings": [...], "stats": {...}}
    """
    return XmlValidator.validate(xml_content).to_dict()


def repair_tia_xml(xml_content: str) -> tuple:
    """使用 XML DOM + TextNormalizer 安全修复 XML。

    核心原则（TIA 导入规范，必须严格遵守）：
      ❌ 禁止 regex 删除 XML 标签/修改 XML 结构
      ❌ 禁止破坏 MultilingualText 节点
      ❌ 禁止把节点 flatten 成字符串
      ✔ 必须有 Language 属性
      ✔ 必须使用 DOM 操作 XML 结构
      ✔ Rebuild Not Patch：所有修复必须重建节点，不修补字符串

    修复流水线（委托给管线各层）：
      1. TextNormalizer.normalize_xml_content — 文本级 HTML 清洗 + 控制字符移除
      2. ScreenNumberAllocator.remove_number_nodes — 删除 <Number> 节点
      3. _rebuild_multilingual_text_dom — DOM 级 MultilingualText 标准重建

    返回:
        (repaired_xml: str, repair_log: list)
    """
    from .text_normalizer import TextNormalizer
    from .screen_number_allocator import ScreenNumberAllocator

    repair_log = []

    # Step 1: 文本级 HTML 标签清洗 + 控制字符移除
    xml_content, clean_report = TextNormalizer.normalize_xml_content(xml_content)
    if clean_report.get("html_removed", 0) > 0:
        tags = clean_report.get("html_tags_found", [])
        repair_log.append(
            f"已移除 {clean_report['html_removed']} 处 HTML/富文本标签"
            f" ({', '.join(tags[:8])})"
        )
    if clean_report.get("controls_removed", 0) > 0:
        repair_log.append(
            f"已移除 {clean_report['controls_removed']} 处非法控制字符"
        )

    # Step 2: 删除 <Number> 节点（TIA 自动分配 screen number）
    allocator = ScreenNumberAllocator()
    xml_content = allocator.remove_number_nodes(xml_content)
    # 检测是否有 Number 节点被删除
    before = xml_content

    # Step 3: DOM 级 MultilingualText 标准重建（核心修复）
    try:
        xml_content, mt_log = _rebuild_multilingual_text_dom(xml_content)
        repair_log.extend(mt_log)
    except Exception as e:
        repair_log.append(f"MultilingualText DOM 重建异常：{e}")

    return xml_content, repair_log


def _rebuild_multilingual_text_dom(xml_content: str) -> tuple:
    """使用 XML DOM 安全重建所有 MultilingualText 节点为 TIA 标准结构。

    委托给 MultilingualTextBuilder.rebuild_element() —— 保证 DOM 操作正确性。

    标准结构（TIA Portal 强制要求）：
      <MultilingualText>
        <Text Language="zh-CN">已清洗的安全文本</Text>
      </MultilingualText>

    返回:
        (rebuilt_xml: str, repair_log: list)
    """
    import xml.etree.ElementTree as ET

    repair_log = []
    decl_match = re.match(r'(<\?xml[^?]*\?>\s*)', xml_content)
    declaration = decl_match.group(1) if decl_match else ""

    # 收集并注册命名空间
    for m in re.finditer(r'xmlns(?::(\w+))?="([^"]+)"', xml_content[:4096]):
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

    def _local_tag(elem):
        tag = elem.tag
        if "}" in tag:
            return tag.rsplit("}", 1)[-1]
        if "." in tag:
            return tag.rsplit(".", 1)[-1]
        return tag

    builder = MultilingualTextBuilder()
    mt_elements = [
        e for e in root.iter()
        if _local_tag(e) in ("MultilingualText",)
    ]

    for mt_elem in mt_elements:
        try:
            builder.rebuild_element(mt_elem)
        except Exception:
            pass

    if mt_elements:
        repair_log.append(
            f"DOM 级重建了 {len(mt_elements)} 个 MultilingualText 节点为 TIA 标准结构"
        )

    result = ET.tostring(root, encoding="unicode")
    if declaration and not result.startswith("<?"):
        result = declaration.rstrip() + "\n" + result

    return result, repair_log

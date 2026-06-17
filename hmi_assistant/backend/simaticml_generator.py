# -*- coding: utf-8 -*-
"""
SimaticML 生成器
==================
把校验后的 IR 转换成 SimaticML 风格的 XML，用于通过 Openness 的
ScreenFolder.Import() 导入到博途。

⚠️ 重要版本说明（务必阅读）：
  SimaticML 的精确元素名/命名空间在不同 TIA 版本(V16/V17/V18/V19)和不同
  HMI 类型(Comfort/Unified)之间存在差异。最稳妥的工程做法是：
     1) 在你的博途里手工画一个含目标对象(IO域/符号IO域/按钮/圆)的样例画面；
     2) 用 Screen.Export() 导出该画面 XML，观察真实结构；
     3) 用本文件生成的 XML 作为骨架，按导出样例对齐元素名/属性名。
  本生成器输出的结构刻意保持清晰、分对象成函数，便于你按版本微调。
  下面以 TIA V18 Comfort 面板的常见结构为基准给出。
"""
import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom


def _color_to_argb(hex_color: str) -> str:
    """#RRGGBB -> 255,R,G,B（WinCC 颜色常用 ARGB 整数或分量，这里给分量串）。"""
    c = (hex_color or "#000000").lstrip("#")
    if len(c) == 6:
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        return f"{r},{g},{b}"
    return "0,0,0"


def _sub(parent, tag, text=None, **attrs):
    el = ET.SubElement(parent, tag)
    for k, v in attrs.items():
        el.set(k, str(v))
    if text is not None:
        el.text = str(text)
    return el


# ---------- 各对象的 XML 片段 ----------
def _io_field(parent, o, two_state="IOField"):
    """文本/数值 IO 域。SimaticML 中通常为 <IOField> 带 ProcessValue 连接。"""
    item = _sub(parent, "ScreenItem", Name=o["id"], Type="IOField")
    geo = _sub(item, "Geometry")
    _sub(geo, "X", o["x"]); _sub(geo, "Y", o["y"])
    _sub(geo, "Width", o["width"]); _sub(geo, "Height", o["height"])
    props = _sub(item, "Properties")
    _sub(props, "Mode", o["mode"])                       # Input/Output/InputOutput
    _sub(props, "OutputFormat", o.get("display_format", "Decimal"))
    _sub(props, "DecimalDigits", o.get("decimal_digits", 0))
    _sub(props, "FontSize", o.get("font_size", 16))
    # 变量连接
    conn = _sub(item, "Connection")
    _sub(conn, "ProcessTag", o["process_tag"])
    return item


def _symbolic_io_field(parent, o):
    item = _sub(parent, "ScreenItem", Name=o["id"], Type="SymbolicIOField")
    geo = _sub(item, "Geometry")
    _sub(geo, "X", o["x"]); _sub(geo, "Y", o["y"])
    _sub(geo, "Width", o["width"]); _sub(geo, "Height", o["height"])
    props = _sub(item, "Properties")
    _sub(props, "Mode", o["mode"])
    _sub(props, "FontSize", o.get("font_size", 16))
    _sub(props, "TextList", o["text_list"])              # 引用文本列表
    conn = _sub(item, "Connection")
    _sub(conn, "ProcessTag", o["process_tag"])
    return item


def _button(parent, o):
    item = _sub(parent, "ScreenItem", Name=o["id"], Type="Button")
    geo = _sub(item, "Geometry")
    _sub(geo, "X", o["x"]); _sub(geo, "Y", o["y"])
    _sub(geo, "Width", o["width"]); _sub(geo, "Height", o["height"])
    props = _sub(item, "Properties")
    _sub(props, "Text", o["text"])
    _sub(props, "BackColor", _color_to_argb(o.get("background_color", "#2BB673")))
    # 事件 -> VBS 脚本（导入时脚本体由 scripts 注入，见 generate 末尾）
    events = _sub(item, "Events")
    for ev_name, key in (("Press", "press_script"),
                         ("Release", "release_script"),
                         ("Click", "click_script")):
        sc = o.get(key)
        if sc:
            ev = _sub(events, "Event", Name=ev_name)
            _sub(ev, "VBSFunction", sc)
    return item


def _indicator(parent, o):
    """指示灯：基本对象'圆' + 颜色动画（按 Bool 变量切换填充色）。"""
    item = _sub(parent, "ScreenItem", Name=o["id"], Type="Circle")
    geo = _sub(item, "Geometry")
    # 圆用包围盒表示
    _sub(geo, "X", o["x"]); _sub(geo, "Y", o["y"])
    _sub(geo, "Width", o["radius"] * 2); _sub(geo, "Height", o["radius"] * 2)
    props = _sub(item, "Properties")
    _sub(props, "FillColor", _color_to_argb(o["color_off"]))
    _sub(props, "BorderColor", "120,130,140")
    # 颜色动画：变量=1 -> color_on，=0 -> color_off
    anim = _sub(item, "Animations")
    ca = _sub(anim, "ColorAnimation", Tag=o["process_tag"])
    _sub(ca, "Range", Value="0", FillColor=_color_to_argb(o["color_off"]))
    _sub(ca, "Range", Value="1", FillColor=_color_to_argb(o["color_on"]))
    if o.get("blink"):
        # 闪烁动画（故障灯）：变量=1 时闪烁
        fa = _sub(anim, "FlashAnimation", Tag=o["process_tag"])
        _sub(fa, "Range", Value="1", Flashing="Yes")
    return item


def _text(parent, o):
    item = _sub(parent, "ScreenItem", Name=o["id"], Type="TextField")
    geo = _sub(item, "Geometry")
    _sub(geo, "X", o["x"]); _sub(geo, "Y", o["y"])
    _sub(geo, "Width", o["width"]); _sub(geo, "Height", o["height"])
    props = _sub(item, "Properties")
    _sub(props, "Text", o["text"])
    _sub(props, "FontSize", o.get("font_size", 18))
    _sub(props, "Bold", "true" if o.get("bold") else "false")
    _sub(props, "ForeColor", _color_to_argb(o.get("color", "#E6EDF3")))
    return item


# 标签 -> 说明文字（label 自动生成一个 TextField 放在对象左侧）
def _label_for(parent, o):
    label = o.get("label")
    if not label:
        return
    lab_obj = {
        "id": o["id"] + "_lbl",
        "x": max(0, o["x"] - 90),
        "y": o["y"] + 8,
        "width": 84, "height": 28,
        "text": label, "font_size": 14, "bold": False,
        "color": "#C9D3DE",
    }
    _text(parent, lab_obj)


_DISPATCH = {
    "IOField": _io_field,
    "SymbolicIOField": _symbolic_io_field,
    "Button": _button,
    "Indicator": _indicator,
    "Text": _text,
}


def generate_simaticml(ir: dict, tia_version: str = "V18") -> str:
    """返回格式化后的 SimaticML XML 字符串。"""
    meta = ir["meta"]
    root = ET.Element("Document")
    _sub(root, "Engineering", version=tia_version)

    screen = _sub(root, "Screen", Name=meta["screen_name"])
    sattr = _sub(screen, "AttributeList")
    _sub(sattr, "Name", meta["screen_name"])
    _sub(sattr, "DisplayName", meta.get("title", meta["screen_name"]))
    w, h = ir["_screen_size"]["width"], ir["_screen_size"]["height"]
    _sub(sattr, "Width", w); _sub(sattr, "Height", h)

    # 变量表（供导入端建立/关联 HMI 变量）
    tags_el = _sub(screen, "Tags")
    for t in ir["tags"]:
        te = _sub(tags_el, "Tag", Name=t["name"], DataType=t["data_type"])
        if t.get("address"):
            _sub(te, "Address", t["address"])
        if t.get("comment"):
            _sub(te, "Comment", t["comment"])

    # 文本列表
    if ir["text_lists"]:
        tls = _sub(screen, "TextLists")
        for tl in ir["text_lists"]:
            tle = _sub(tls, "TextList", Name=tl["name"])
            for e in tl["entries"]:
                _sub(tle, "Entry", Value=e["value"], Text=e["text"])

    # 画面对象
    obj_list = _sub(screen, "ObjectList")
    for o in ir["objects"]:
        # 先放说明文字（若有 label）
        if o["type"] in ("IOField", "SymbolicIOField", "Indicator"):
            _label_for(obj_list, o)
        # IO 域带单位则在右侧加单位文本
        builder = _DISPATCH[o["type"]]
        builder(obj_list, o)
        if o["type"] == "IOField" and o.get("unit"):
            unit_obj = {
                "id": o["id"] + "_unit",
                "x": o["x"] + o["width"] + 6, "y": o["y"] + 8,
                "width": 60, "height": 28,
                "text": o["unit"], "font_size": 14, "bold": False,
                "color": "#9AA7B4",
            }
            _text(obj_list, unit_obj)

    # VBS 脚本集合（按钮事件引用的实体代码）
    if ir["scripts"]:
        scripts_el = _sub(root, "VBScripts")
        for s in ir["scripts"]:
            se = _sub(scripts_el, "Script", Name=s["name"], Language="VBScript")
            _sub(se, "Purpose", s.get("purpose", ""))
            code_el = _sub(se, "Code")
            code_el.text = s.get("code", "")

    rough = ET.tostring(root, encoding="utf-8")
    pretty = minidom.parseString(rough).toprettyxml(indent="  ", encoding="utf-8")
    return pretty.decode("utf-8")

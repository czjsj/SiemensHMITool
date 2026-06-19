# -*- coding: utf-8 -*-
"""
经典 HMI 模板 XML 改写模块
===========================
职责：IR + 模板 XML → 新 XML（安全改写，保留原始结构）

工作原理：
  1. 从 TIA Portal 手工导出的模板 XML 作为基底；
  2. 根据 IR 中的画面名称、对象列表改写安全字段；
  3. 尽量保持 XML 原始结构、命名空间、ID、LinkList、CompositionName 不变；
  4. 只做安全替换，不从零拼完整 XML。

匹配策略（按优先级）：
  1. IR object 的 template_ref
  2. IR object 的 id
  3. 名称前缀：TXT_ / BTN_ / IO_ / SIO_ / LMP_

找不到模板控件时：
  - 返回 warning
  - 不强行拼复杂 XML
  - 可选地复制同类型模板控件（谨慎，需保持 ID 唯一）
"""
import copy
import uuid
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as xml_escape
from .tia_text_sanitizer import sanitize_tia_text


# ---- 名称前缀 → 类型映射 ----
_PREFIX_TYPE_MAP = {
    "TXT_": "Text",
    "BTN_": "Button",
    "IO_": "IOField",
    "SIO_": "SymbolicIOField",
    "LMP_": "Indicator",
}

# ---- XML 标签（本地名）→ IR 类型映射（TIA V16 Comfort 面板） ----
_XML_TAG_TO_IR_TYPE = {
    "IOField": "IOField",
    "Button": "Button",
    "SymbolicIOField": "SymbolicIOField",
    "Circle": "Indicator",
    "Ellipse": "Indicator",
    "Rectangle": "Indicator",
    "TextField": "Text",
    "Slider": "Slider",
    "Switch": "Switch",
    "Gauge": "Gauge",
}

# ---- IR 类型 → XML 标签（用于复制控件时选择正确的模板） ----
_IR_TYPE_TO_XML_TAG = {
    "IOField": "IOField",
    "Button": "Button",
    "SymbolicIOField": "SymbolicIOField",
    "Indicator": "Circle",
    "Text": "TextField",
    "Slider": "Slider",
    "Switch": "Switch",
    "Gauge": "Gauge",
}

# TIA V16/Comfort 中，画面可见文本属性需要富文本片段；HelpText 不需要。
_RICH_TEXT_COMPOSITIONS = {"Text", "TextOff", "TextOn", "Caption", "DisplayText"}


# ========================================================================
# 标签名解析
# ========================================================================

def _local_tag(elem: ET.Element) -> str:
    """提取元素的本地标签名，兼容两种 TIA XML 格式：

    - 命名空间格式：{http://...}IOField → IOField
    - 点分隔格式（TIA V16）：Hmi.Screen.IOField → IOField
    - 纯标签名：IOField → IOField
    """
    tag = elem.tag
    # 处理 {namespace}LocalName
    if "}" in tag:
        return tag.split("}")[-1]
    # 处理 Dotted.Qualified.Name
    if "." in tag:
        return tag.rsplit(".", 1)[-1]
    return tag


def _guess_type_from_id(obj_id: str) -> str | None:
    """根据对象 id 的前缀猜测 IR 类型。"""
    for prefix, otype in _PREFIX_TYPE_MAP.items():
        if obj_id.startswith(prefix):
            return otype
    return None


# ========================================================================
# 公共入口
# ========================================================================

def generate_from_template_xml(
    ir: dict,
    template_xml: str,
    options: dict | None = None,
) -> tuple[str, list[str]]:
    """主入口：用 IR 改写模板 XML，返回 (新 XML 字符串, warnings 列表)。

    参数:
        ir: 校验后的 HMI 画面 IR。
        template_xml: 从 TIA Portal 导出的模板画面 XML 字符串。
        options: 可选配置 dict，可包含:
            - screen_name_override: 覆盖画面名称
            - keep_screen_name: 不改写画面名称（默认 False）
    """
    options = options or {}
    warnings: list[str] = []

    # 注册命名空间，防止 ET 在输出时使用 ns0: 前缀
    ns_map = _detect_namespace(template_xml)
    for prefix, uri in ns_map.items():
        if prefix:
            ET.register_namespace(prefix, uri)
        else:
            ET.register_namespace("", uri)

    try:
        root = ET.fromstring(template_xml)
    except ET.ParseError as e:
        return template_xml, [f"模板 XML 解析失败：{e}"]

    meta = ir.get("meta", {})
    objects = ir.get("objects", [])
    # 记录 IR 坐标所基于的源分辨率。validate_ir() 会写入 _screen_size；
    # 如果没有，则从 meta.resolution 兜底解析。
    ir_size = _get_ir_screen_size(ir)
    template_size = None

    # 1. 改写画面名称
    screen_node = _find_screen_node(root)
    if screen_node is not None:
        screen_name = options.get("screen_name_override") or meta.get("screen_name", "")
        if screen_name and not options.get("keep_screen_name"):
            _set_screen_name(screen_node, screen_name, warnings)

        # ⚠️ TIA/WinCC Advanced 的 Screen 尺寸必须与目标设备完全一致。
        # 模板 XML 通常来自当前 HMI，尺寸已经正确；不能用 IR 的默认
        # 1280x800 覆盖模板，否则会触发：The screen size does not match the device。
        # 默认保留模板尺寸；只有显式传 keep_template_screen_size=False 时才改写。
        keep_template_size = options.get("keep_template_screen_size", True)
        w = ir.get("_screen_size", {}).get("width")
        h = ir.get("_screen_size", {}).get("height")
        if keep_template_size:
            template_size = _get_screen_size(screen_node)
            if template_size and ir_size and template_size != ir_size:
                warnings.append(
                    f"已保留模板画面尺寸 {template_size[0]}x{template_size[1]}，"
                    f"未使用 IR 尺寸 {ir_size[0]}x{ir_size[1]}，避免与目标 HMI 分辨率不匹配。"
                )
                if options.get("scale_items_to_template_size", True):
                    objects = _scale_objects_to_size(objects, ir_size, template_size, warnings)
        elif w and h:
            _set_screen_size(screen_node, int(w), int(h), warnings)
    else:
        warnings.append("模板 XML 中未找到 Screen 节点，无法改写画面属性")

    # 2. 遍历 IR 对象，匹配并改写模板控件
    template_items = list(_iter_candidate_screen_items(root))
    item_map = _build_item_name_map(template_items)
    type_map = _build_item_type_map(template_items)
    parent_map = _build_parent_map(root)
    used_ids = _collect_existing_ids(root)

    used_template_ids = set()
    used_template_names = set()  # 按名称追踪已使用的控件，避免多个 IR 对象覆盖同一个模板控件
    for obj in objects:
        matched = _match_template_item(obj, item_map, type_map, used_template_names)
        if matched is None:
            # 模板控件数量不足时，按同类型控件克隆一个。
            # 例如 IR 有启动/停止/复位 3 个按钮，但模板只有 1 个按钮，
            # 旧逻辑会反复覆盖同一个按钮，最终只剩最后一个“复位”。
            matched = _clone_matching_template_item(
                obj, type_map, parent_map, used_ids, warnings
            )

        if matched is None:
            warnings.append(
                f"对象 '{obj.get('id', '?')}' (type={obj.get('type', '?')}) "
                f"在模板中未找到同类型控件，已跳过"
            )
            continue

        item_elem, match_key = matched
        used_template_ids.add(match_key)
        used_template_names.add(match_key)
        _apply_object_to_item(obj, item_elem, warnings)

        # 应用后控件名称可能从模板名改成 IR 对象 id；也要标记为已用，
        # 否则后续同类型对象会通过新名称再次匹配到同一个元素。
        new_name = _get_item_name(item_elem)
        if new_name:
            used_template_names.add(new_name)
            used_template_ids.add(new_name)

        # 克隆后刷新查找表，后续对象可以继续基于同类型模板克隆。
        if new_name and new_name not in item_map:
            item_map[new_name] = (item_elem, _local_tag(item_elem))
            type_map.setdefault(_local_tag(item_elem), []).append((item_elem, new_name))

    # 3. 检测模板中未被使用的控件，发出提醒
    for key, (elem, _) in item_map.items():
        if key not in used_template_ids:
            name = _get_item_name(elem) or "(unnamed)"
            warnings.append(f"模板控件 '{name}' 未被任何 IR 对象引用，保留原样")

    # 4. 序列化回 XML 字符串
    new_xml = _element_to_string(root, template_xml)
    return new_xml, warnings


# ========================================================================
# 命名空间检测
# ========================================================================

def _detect_namespace(xml_str: str) -> dict:
    """从 XML 中提取命名空间映射 {prefix: uri}。"""
    ns_map = {}
    # 通过 ET.fromstring 自动收集
    try:
        # 使用 iterparse 风格的事件来捕获 start-ns
        events = []
        ET.register_namespace("", "")  # 临时占位

        # 更简单的方式：从根元素直接取
        root = ET.fromstring(xml_str)
        # 从根标签提取默认命名空间
        tag = root.tag
        if "}" in tag:
            default_ns = tag.split("}")[0].lstrip("{")
            ns_map[""] = default_ns

        # 查找 xmlns: 前缀声明（通过原始字符串）
        import re
        for match in re.finditer(r'xmlns:(\w+)="([^"]+)"', xml_str[:2000]):
            ns_map[match.group(1)] = match.group(2)

        # 默认 xmlns
        default_m = re.search(r'xmlns="([^"]+)"', xml_str[:2000])
        if default_m:
            ns_map[""] = default_m.group(1)
    except Exception:
        pass

    return ns_map


def _element_to_string(root: ET.Element, original_xml: str = "") -> str:
    """将 ElementTree 序列化为 XML 字符串，尽量保持原始声明。"""
    import re

    raw = ET.tostring(root, encoding="unicode")

    # 尝试保留原始 XML 声明
    decl = '<?xml version="1.0" encoding="utf-8"?>'
    decl_m = re.match(r'<\?xml[^?]*\?>', original_xml)
    if decl_m:
        decl = decl_m.group(0)

    if raw.startswith("<?xml"):
        raw = re.sub(r'<\?xml[^?]*\?>', decl, raw, count=1)
    else:
        raw = decl + "\n" + raw

    return raw




def _get_ir_screen_size(ir: dict) -> tuple[int, int] | None:
    """读取 IR 坐标所基于的分辨率。"""
    ss = ir.get("_screen_size") or {}
    try:
        w, h = int(ss.get("width")), int(ss.get("height"))
        if w > 0 and h > 0:
            return w, h
    except Exception:
        pass
    res = (ir.get("meta") or {}).get("resolution", "")
    if isinstance(res, str) and "x" in res.lower():
        try:
            a, b = res.lower().split("x", 1)
            w, h = int(a.strip()), int(b.strip())
            if w > 0 and h > 0:
                return w, h
        except Exception:
            pass
    return None


def _scale_objects_to_size(objects: list, source_size: tuple[int, int], target_size: tuple[int, int], warnings: list) -> list:
    """把 IR 对象坐标从 source_size 等比映射到 target_size。

    经典模板 XML 模式会保留模板 Screen 尺寸。若 IR 仍是 1280x800，
    但模板/目标 HMI 是 800x480，必须在写入 Left/Top/Width/Height 前缩放，
    否则前端预览和 TIA 实际位置会明显不一致，甚至对象跑出画面。
    """
    import copy
    sw, sh = source_size
    tw, th = target_size
    if sw <= 0 or sh <= 0 or (sw, sh) == (tw, th):
        return objects

    sx = tw / sw
    sy = th / sh
    sm = min(sx, sy)
    scaled = []
    for obj in objects:
        o = copy.deepcopy(obj)
        for key, factor, minimum in (
            ("x", sx, 0), ("y", sy, 0),
            ("width", sx, 1), ("height", sy, 1),
            ("radius", sm, 1),
        ):
            if key in o and o[key] is not None:
                try:
                    value = int(round(float(o[key]) * factor))
                    if minimum:
                        value = max(minimum, value)
                    o[key] = value
                except Exception:
                    pass
        # 字号也缩放，但保留可读下限，避免 800x480 上小于 10px。
        if "font_size" in o and o["font_size"] is not None:
            try:
                o["font_size"] = max(10, int(round(float(o["font_size"]) * sm)))
            except Exception:
                pass
        scaled.append(o)

    warnings.append(
        f"已将 {len(scaled)} 个 IR 控件坐标从 {sw}x{sh} "
        f"按比例映射到模板尺寸 {tw}x{th}。"
    )
    return scaled

# ========================================================================
# Screen 节点操作
# ========================================================================

def _find_screen_node(root: ET.Element) -> ET.Element | None:
    """在 XML 树中递归查找 Screen 元素（兼容各种命名空间）。"""
    # 直接匹配
    if "Screen" in root.tag or root.tag.endswith("Screen"):
        return root

    # BFS/DFS 查找
    stack = [root]
    while stack:
        elem = stack.pop()
        tag_local = _local_tag(elem)
        if tag_local == "Screen" or tag_local.endswith("Screen"):
            return elem
        stack.extend(list(elem))
    return None


def _get_screen_size(screen_node: ET.Element) -> tuple[int, int] | None:
    """读取 Screen 直接 AttributeList 里的 Width/Height。"""
    width = height = None
    for attr_list in screen_node:
        if _local_tag(attr_list) != "AttributeList":
            continue
        for child in attr_list:
            ctag = _local_tag(child)
            text = (child.text or "").strip()
            if ctag == "Width" and text.isdigit():
                width = int(text)
            elif ctag == "Height" and text.isdigit():
                height = int(text)
    if width and height:
        return width, height
    return None


def _set_screen_name(screen_node: ET.Element, name: str, warnings: list):
    """设置画面名称（Name 和 DisplayName 属性或子元素）。

    仅修改 Screen 元素**直接**包含的 AttributeList，不递归子控件。
    """
    name = sanitize_tia_text(name)

    # 尝试属性
    if "Name" in screen_node.attrib:
        screen_node.set("Name", name)

    # 仅查找 Screen 直接子元素中的 AttributeList（不递归）
    for attr_list in screen_node:
        if _local_tag(attr_list) != "AttributeList":
            continue
        for child in attr_list:
            ctag = _local_tag(child)
            if ctag == "Name":
                child.text = name
            elif ctag == "DisplayName":
                child.text = child.text or name


def _set_screen_size(screen_node: ET.Element, width: int, height: int, warnings: list):
    """设置画面尺寸（Width/Height 属性）。

    仅修改 Screen 元素**直接**包含的 AttributeList，不递归子控件。
    （之前用 screen_node.iter() 遍历所有后代，会把其他控件的 Width/Height 也改成屏幕尺寸）
    """
    for attr_list in screen_node:
        if _local_tag(attr_list) != "AttributeList":
            continue
        for child in attr_list:
            ctag = _local_tag(child)
            if ctag == "Width":
                child.text = str(width)
            elif ctag == "Height":
                child.text = str(height)


# ========================================================================
# 控件遍历与匹配
# ========================================================================

def _iter_candidate_screen_items(root: ET.Element):
    """遍历所有可能的画面控件元素。

    TIA V16 Comfort 面板导出的 XML 使用这些实际标签名：
      Hmi.Screen.IOField, Hmi.Screen.Button, Hmi.Screen.SymbolicIOField,
      Hmi.Screen.Circle, Hmi.Screen.TextField, Hmi.Screen.Rectangle,
      Hmi.Screen.Line, Hmi.Screen.Ellipse 等。
    同时兼容旧代码期望的 ScreenItem / SW.ScreenItem 抽象标签。
    """
    # TIA Comfort 面板实际的控件标签（本地名）
    comfort_item_tags = {
        "IOField", "Button", "SymbolicIOField", "Circle",
        "TextField", "Rectangle", "Line", "Ellipse",
        "GraphicView", "TrendView", "Gauge", "Slider",
        "Switch", "Roller", "UserView", "AlarmView",
    }
    # 旧代码 / Unified / 通用标签
    generic_item_tags = {"ScreenItem", "Object", "Item", "SW.ScreenItem"}

    all_item_tags = comfort_item_tags | generic_item_tags

    for elem in root.iter():
        tag = _local_tag(elem)
        if tag in all_item_tags:
            yield elem


def _get_item_name(item: ET.Element) -> str | None:
    """从 ScreenItem 中提取名称。

    TIA V16 格式：<AttributeList><ObjectName>xxx</ObjectName>
    也兼容：<item Name="xxx">、<item><Name>xxx</Name>、<Name>xxx</Name>
    """
    # 1) 直接属性 Name
    if "Name" in item.attrib:
        return item.attrib["Name"]

    # 2) AttributeList → ObjectName（TIA V16 导出格式）
    for attr_list in item:
        al_tag = _local_tag(attr_list)
        if al_tag == "AttributeList":
            for child in attr_list:
                ctag = _local_tag(child)
                if ctag == "ObjectName" and child.text:
                    return child.text.strip()

    # 3) 直接子元素 Name
    for child in item:
        ctag = _local_tag(child)
        if ctag == "Name" and child.text:
            return child.text.strip()

    # 4) 深层 Name 元素
    for child in item.iter():
        ctag = _local_tag(child)
        if ctag == "Name" and child.text:
            return child.text.strip()

    return None


def _set_item_name(item: ET.Element, name: str):
    """设置 ScreenItem 的名称。

    TIA V16 格式：<AttributeList><ObjectName>xxx</ObjectName>
    也兼容：<item Name="xxx">、<Name>xxx</Name>
    """
    # 1) 属性 Name
    if "Name" in item.attrib:
        item.set("Name", name)

    # 2) AttributeList → ObjectName（TIA V16 导出格式）
    for attr_list in item:
        al_tag = _local_tag(attr_list)
        if al_tag == "AttributeList":
            for child in attr_list:
                ctag = _local_tag(child)
                if ctag == "ObjectName":
                    child.text = name
                    return

    # 3) 直接子元素 Name
    for child in item:
        ctag = _local_tag(child)
        if ctag == "Name":
            child.text = name
            return


def _build_item_name_map(items: list) -> dict:
    """构建 {name: (element, xml_tag_type)} 查找表。"""
    result = {}
    for elem in items:
        name = _get_item_name(elem)
        if name:
            tag = _local_tag(elem)
            result[name] = (elem, tag)
    return result


def _build_item_type_map(items: list) -> dict:
    """按 XML 标签类型分组控件：{xml_tag_or_type: [(element, name), ...]}

    同时按两种 key 分组：
      - XML 标签本地名（TIA V16 Comfort: IOField, Button, Circle 等）
      - Type 属性（通用 ScreenItem 格式: Type="TextField", Type="Button" 等）
    这样无论哪种模板格式都能按类型匹配。
    """
    result: dict[str, list] = {}
    for elem in items:
        tag = _local_tag(elem)
        name = _get_item_name(elem) or "(unnamed)"
        entry = (elem, name)

        # 按 XML 标签名分组
        result.setdefault(tag, []).append(entry)

        # 如果元素有 Type 属性，也按 Type 属性值分组
        type_attr = elem.get("Type") or elem.get("type")
        if type_attr:
            result.setdefault(type_attr, []).append(entry)
    return result


def _match_template_item(
    obj: dict,
    item_map: dict,
    type_map: dict | None = None,
    used_tags: set | None = None,
) -> tuple | None:
    """按优先级匹配模板控件。

    参数:
        obj: IR 对象。
        item_map: {name: (element, xml_tag)} 名称查找表。
        type_map: {xml_tag: [(element, name), ...]} 类型查找表（用于类型匹配）。
        used_tags: 已被匹配的控件名称集合（用于按类型匹配时排除已用的）。

    返回 (element, matched_key) 或 None。
    """
    # 优先级 1: template_ref
    ref = obj.get("template_ref")
    if ref and ref in item_map:
        return (item_map[ref][0], ref)

    # 优先级 2: IR 对象 id 完全匹配模板控件名
    oid = obj.get("id")
    if oid and oid in item_map:
        if used_tags is None or oid not in used_tags:
            return (item_map[oid][0], oid)

    # 优先级 3: 名称前缀匹配（TXT_ → Text、BTN_ → Button 等）
    # 注意必须避开已用控件，否则 BTN_Start/BTN_Stop/BTN_Reset 会反复覆盖同一个按钮。
    otype = obj.get("type", "")
    for prefix, pt in _PREFIX_TYPE_MAP.items():
        if pt == otype:
            for name, (elem, _) in item_map.items():
                if name.startswith(prefix) and (used_tags is None or name not in used_tags):
                    return (elem, name)

    # 优先级 4: 按 IR 类型 → XML 标签映射（不依赖名称前缀）
    # 这是 TIA V16 项目中的关键匹配方式：模板控件可能叫 "I/O 域_1"、
    # "按钮_1" 等默认名，而不是 "IO_Speed"、"BTN_Start" 等前缀名。
    target_xml_tag = _IR_TYPE_TO_XML_TAG.get(otype)
    if target_xml_tag and type_map:
        candidates = type_map.get(target_xml_tag, [])
        # 优先返回未被使用的
        if used_tags is not None:
            for elem, name in candidates:
                if name and name not in used_tags:
                    return (elem, name)
        # 如果调用方传入 used_tags，说明不能复用同一个控件；
        # 此时全部候选已用完就返回 None，让上层走克隆逻辑。
        if used_tags is None and candidates:
            elem, name = candidates[0]
            return (elem, name)

    # 优先级 5: 模糊名称前缀（已在上面尝试过，这里作为兼容保留）
    obj_prefixes = [p for p, t in _PREFIX_TYPE_MAP.items() if t == otype]
    for name, (elem, _) in item_map.items():
        for prefix in obj_prefixes:
            if name.startswith(prefix) and (used_tags is None or name not in used_tags):
                return (elem, name)

    return None


# ========================================================================
# 对象属性应用到模板控件
# ========================================================================

def _apply_object_to_item(obj: dict, item: ET.Element, warnings: list):
    """将 IR 对象的属性安全地应用到模板控件。"""
    oid = obj.get("id", "")
    otype = obj.get("type", "")

    # 名称
    if oid:
        _set_item_name(item, oid)

    # 位置与尺寸
    x, y = obj.get("x"), obj.get("y")
    w, h = obj.get("width"), obj.get("height")
    if x is not None and y is not None:
        _set_position(item, x, y)
    if w is not None and h is not None:
        _set_size(item, w, h)

    # 文本
    text = obj.get("text")
    if text:
        _set_item_text(item, text)

    # 变量连接
    tag = obj.get("process_tag")
    if tag:
        _set_process_tag(item, tag)

    # 颜色（Button: background_color; Indicator: color_on/color_off; Text: color）
    if otype == "Button":
        bg = obj.get("background_color")
        if bg:
            _set_background_color(item, bg, warnings)
    elif otype == "Indicator":
        _set_indicator_colors(item, obj, warnings)
    elif otype == "Text":
        color = obj.get("color")
        if color:
            _set_foreground_color(item, color, warnings)

    # 按钮脚本事件
    if otype == "Button":
        for ev_key in ("press_script", "release_script", "click_script"):
            sc = obj.get(ev_key)
            if sc:
                _set_button_event(item, ev_key, sc, warnings)


# ========================================================================
# 属性修改辅助函数
# ========================================================================

def _set_position(item: ET.Element, x: int, y: int):
    """设置 Left/Top 或 X/Y 属性。"""
    _set_nested_property(item, "Left", str(x))
    _set_nested_property(item, "Top", str(y))
    # 也尝试 X/Y 形式
    _set_nested_property(item, "X", str(x))
    _set_nested_property(item, "Y", str(y))


def _set_size(item: ET.Element, width: int, height: int):
    """设置 Width/Height 属性。"""
    _set_nested_property(item, "Width", str(width))
    _set_nested_property(item, "Height", str(height))


def _set_item_text(item: ET.Element, text: str):
    """设置控件显示文本。

    TIA V16/Comfort 的按钮/文本控件通常有多个 MultilingualText：
      - HelpText：帮助文本，不应该当作按钮标题
      - Text / TextOff / TextOn：真正显示在画面上的文本

    旧实现递归查找第一个 <Text>，经常先命中 HelpText，导致按钮
    标题仍是模板里的 "Text"，而 HelpText 被误改成按钮文字。
    """
    text = sanitize_tia_text(text)

    tag = _local_tag(item)
    if tag == "Button":
        targets = {"Text", "TextOff", "TextOn"}
    elif tag in ("TextField", "Text"):
        targets = {"Text"}
    else:
        targets = {"Text", "TextOff", "TextOn", "Caption", "DisplayText"}

    if _set_multilingual_text_by_composition(item, targets, text):
        return

    # 非 TIA V16 模板的兜底：仍然避免优先改 HelpText。
    for prop_name in ("Text", "TextOff", "TextOn", "Caption", "DisplayText"):
        if prop_name in targets and _set_nested_property(item, prop_name, text, skip_help_text=True):
            return


def _set_multilingual_text_by_composition(
    item: ET.Element,
    composition_names: set,
    text: str,
) -> bool:
    """按 MultilingualText 的 CompositionName 更新 V16/Comfort 文本。"""
    changed = False
    for mt in item.iter():
        if _local_tag(mt) != "MultilingualText":
            continue
        cname = mt.get("CompositionName") or ""
        if cname not in composition_names:
            continue

        # V16: MultilingualTextItem / AttributeList / Text
        for mt_item in mt.iter():
            if _local_tag(mt_item) != "MultilingualTextItem":
                continue
            for attr_list in mt_item:
                if _local_tag(attr_list) != "AttributeList":
                    continue
                text_node = None
                culture_node = None
                for child in attr_list:
                    ctag = _local_tag(child)
                    if ctag == "Text":
                        text_node = child
                    elif ctag == "Culture":
                        culture_node = child
                if culture_node is None:
                    culture_node = ET.SubElement(attr_list, "Culture")
                    culture_node.text = "zh-CN"
                if text_node is None:
                    text_node = ET.SubElement(attr_list, "Text")
                _set_tia_text_node(
                    text_node,
                    text,
                    rich=(cname in _RICH_TEXT_COMPOSITIONS),
                )
                changed = True

        # 通用结构：MultilingualText / Text Language=...
        for child in mt:
            if _local_tag(child) == "Text":
                child.set("Language", child.get("Language") or "zh-CN")
                _set_tia_text_node(
                    child,
                    text,
                    rich=((mt.get("CompositionName") or "") in _RICH_TEXT_COMPOSITIONS),
                )
                changed = True
    return changed


def _set_tia_text_node(text_node: ET.Element, text: str, rich: bool = False):
    """设置 TIA 文本节点。

    Text/TextOff/TextOn 等显示属性在 WinCC Advanced / Comfort 的导出 XML 中
    使用 <Text><body><p>...</p></body></Text>。写成纯文本会导致
    Openness 报 argument 'text' invalid format。
    """
    for sub in list(text_node):
        text_node.remove(sub)
    text_node.text = None
    if rich:
        body = ET.SubElement(text_node, "body")
        p = ET.SubElement(body, "p")
        p.text = text or " "
    else:
        text_node.text = text or None


def _set_process_tag(item: ET.Element, tag: str):
    """设置变量连接字段 ProcessValue / ProcessTag / TagName / Variable / HmiTag。"""
    for prop_name in ("ProcessTag", "ProcessValue", "TagName", "Variable", "HmiTag"):
        # 先尝试子元素
        found = False
        for child in item.iter():
            ctag = _local_tag(child)
            if ctag == prop_name:
                child.text = tag
                found = True
                break
        if found:
            return

        # 再尝试属性
        if prop_name in item.attrib:
            item.set(prop_name, tag)
            return


def _set_background_color(item: ET.Element, hex_color: str, warnings: list):
    """设置背景颜色。"""
    rgb = _hex_to_rgb_str(hex_color)
    for prop_name in ("BackColor", "BackgroundColor", "FillColor"):
        _set_nested_property(item, prop_name, rgb)


def _set_foreground_color(item: ET.Element, hex_color: str, warnings: list):
    """设置前景/文字颜色。"""
    rgb = _hex_to_rgb_str(hex_color)
    for prop_name in ("ForeColor", "TextColor", "Color"):
        _set_nested_property(item, prop_name, rgb)


def _set_indicator_colors(item: ET.Element, obj: dict, warnings: list):
    """设置指示灯的颜色动画属性。"""
    # 指示灯的动画结构较复杂，尝试改写 Animation → Range 中的 FillColor
    color_on = obj.get("color_on", "")
    color_off = obj.get("color_off", "")
    blink = obj.get("blink", False)

    for animation in item.iter():
        atag = _local_tag(animation)
        if atag in ("Animations", "ColorAnimation", "FlashAnimation"):
            for range_elem in animation.iter():
                rtag = _local_tag(range_elem)
                if rtag == "Range":
                    val = range_elem.get("Value", "")
                    if val == "1" and color_on:
                        range_elem.set("FillColor", _hex_to_rgb_str(color_on))
                    elif val == "0" and color_off:
                        range_elem.set("FillColor", _hex_to_rgb_str(color_off))


def _set_button_event(item: ET.Element, event_key: str, script_name: str, warnings: list):
    """设置按钮的脚本事件引用。"""
    event_map = {
        "press_script": "Press",
        "release_script": "Release",
        "click_script": "Click",
    }
    ev_name = event_map.get(event_key)
    if not ev_name:
        return

    for events_elem in item.iter():
        etag = _local_tag(events_elem)
        if etag == "Events":
            for event in events_elem:
                if event.get("Name") == ev_name:
                    for child in event:
                        ctag = _local_tag(child)
                        if ctag in ("VBSFunction", "Script", "Function"):
                            child.text = script_name
                            return


def _set_nested_property(
    item: ET.Element,
    prop_name: str,
    value: str,
    skip_help_text: bool = False,
) -> bool:
    """尝试在 item 的子树中设置属性值，先试属性再试子元素。"""
    if prop_name in item.attrib:
        item.set(prop_name, value)
        return True

    parent_map = {child: parent for parent in item.iter() for child in parent}
    for child in item.iter():
        ctag = _local_tag(child)
        if ctag != prop_name:
            continue
        if skip_help_text and _is_under_help_text(child, parent_map):
            continue
        for sub in list(child):
            child.remove(sub)
        child.text = value
        return True

    return False


def _is_under_help_text(elem: ET.Element, parent_map: dict) -> bool:
    """判断 elem 是否位于 CompositionName=HelpText 的 MultilingualText 内。"""
    cur = elem
    while cur in parent_map:
        cur = parent_map[cur]
        if _local_tag(cur) == "MultilingualText" and cur.get("CompositionName") == "HelpText":
            return True
    return False


def _hex_to_rgb_str(hex_color: str) -> str:
    """#RRGGBB → 'R,G,B'（WinCC 常用格式）。"""
    c = (hex_color or "#000000").lstrip("#")
    if len(c) == 6:
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        return f"{r},{g},{b}"
    return "0,0,0"


# ========================================================================
# 辅助：克隆模板控件（用于模板控件数量不足时）
# ========================================================================

def _build_parent_map(root: ET.Element) -> dict:
    """构建 child -> parent 映射，ElementTree 默认没有 getparent。"""
    return {child: parent for parent in root.iter() for child in list(parent)}


def _collect_existing_ids(root: ET.Element) -> set:
    """收集 XML 中所有 SimaticML ID 属性。"""
    ids = set()
    for elem in root.iter():
        if "ID" in elem.attrib:
            ids.add(str(elem.attrib["ID"]))
    return ids


def _next_simatic_id(used_ids: set) -> str:
    """生成一个尽量贴近 TIA V16 导出风格的十六进制 ID。"""
    max_value = -1
    for value in used_ids:
        try:
            max_value = max(max_value, int(str(value), 16))
        except Exception:
            continue
    nxt = max_value + 1 if max_value >= 0 else len(used_ids) + 1
    while format(nxt, "X") in used_ids:
        nxt += 1
    result = format(nxt, "X")
    used_ids.add(result)
    return result


def _make_unique_ids(node: ET.Element, used_ids: set):
    """确保克隆节点及其子元素的 ID 唯一。"""
    for elem in node.iter():
        if "ID" in elem.attrib:
            elem.set("ID", _next_simatic_id(used_ids))


def _clone_template_item(item: ET.Element, new_name: str, used_ids: set) -> ET.Element | None:
    """深拷贝一个模板控件并赋予新名称和唯一 ID。"""
    try:
        cloned = copy.deepcopy(item)
        _make_unique_ids(cloned, used_ids)
        _set_item_name(cloned, new_name)
        return cloned
    except Exception:
        return None


def _clone_matching_template_item(
    obj: dict,
    type_map: dict,
    parent_map: dict,
    used_ids: set,
    warnings: list,
) -> tuple | None:
    """当同类型模板控件数量不足时，复制一个同类型控件。"""
    otype = obj.get("type", "")
    target_xml_tag = _IR_TYPE_TO_XML_TAG.get(otype)
    if not target_xml_tag:
        return None

    candidates = type_map.get(target_xml_tag, [])
    if not candidates:
        return None

    source, source_name = candidates[0]
    parent = parent_map.get(source)
    if parent is None:
        return None

    new_name = obj.get("id") or f"{otype}_{len(candidates) + 1}"
    cloned = _clone_template_item(source, new_name, used_ids)
    if cloned is None:
        return None

    children = list(parent)
    try:
        idx = children.index(source)
        parent.insert(idx + 1, cloned)
    except Exception:
        parent.append(cloned)

    parent_map[cloned] = parent
    warnings.append(
        f"模板中 {otype} 控件数量不足，已复制模板控件 '{source_name}' 生成 '{new_name}'。"
    )
    return cloned, new_name


# ========================================================================
# V4.0 模板原型管线 — generate_from_template_v4
# ========================================================================


def generate_from_template_v4(
    ir: dict,
    template_xml: str,
    options: dict | None = None,
) -> dict:
    """V4.0 模板原型管线：IR + 模板 XML → 新 XML（使用控件原型克隆 + 变量替换）。

    与旧版 generate_from_template_xml 的区别：
      - 按钮/指示灯使用模板原型系统（behavior/inidicator_mode 感知）
      - 事件变量和动态绑定变量完全替换（无残留）
      - 返回完整诊断信息（template_analyzed, prototype_matched, pre_import_validated）

    参数:
        ir: 校验后的 HMI 画面 IR。
        template_xml: 从 TIA Portal 导出的模板画面 XML 字符串。
        options: 可选配置 dict。

    返回:
        {
            "ok": bool,
            "xml": str | None,
            "xml_path": str | None,
            "warnings": list[str],
            "diagnostics": {
                "template_analyzed": { "buttons": int, "indicators": int, "total": int },
                "prototype_matched": [{ "item_id": str, "prototype_id": str, ... }],
                "pre_import_validated": { "errors": int, "warnings": int },
            },
        }
    """
    import xml.etree.ElementTree as ET
    from backend.template.prototype_extractor import analyze_template_screen
    from backend.template.prototype_registry import PrototypeRegistry, PrototypeNotFoundError
    from backend.template.xml_rewrite_rules import (
        clone_prototype_node,
        replace_control_name,
        replace_control_text,
        replace_geometry,
        replace_all_tag_references,
        ensure_no_placeholder_tags,
        assign_unique_control_ids,
    )
    from backend.template.xml_utils import collect_existing_ids, deepcopy_xml_node
    from backend.template.template_binding_validator import validate_generated_screen_xml
    from backend.variable_engine import VariableEngine

    options = options or {}
    warnings: list[str] = []
    diagnostics: dict[str, Any] = {
        "template_analyzed": {},
        "prototype_matched": [],
        "pre_import_validated": {},
    }

    # ---- Step 1: VariableEngine enrich ----
    engine = VariableEngine()
    project = engine.enrich(ir)

    # ---- Step 2: Template analysis ----
    try:
        profile = analyze_template_screen(template_xml)
    except Exception as e:
        return {
            "ok": False,
            "xml": None, "xml_path": None,
            "warnings": [f"模板分析失败: {e}"],
            "diagnostics": diagnostics,
        }

    diagnostics["template_analyzed"] = {
        "buttons": len(profile.buttons),
        "indicators": len(profile.indicators),
        "others": len(profile.others),
        "total": len(profile.all_prototypes()),
    }
    warnings.extend(profile.diagnostics)

    # ---- Step 3: Prototype matching for each screen item ----
    registry = PrototypeRegistry(profile)

    # Collect template variable names
    template_tags: set[str] = set()
    for proto in profile.all_prototypes():
        for ref in proto.tag_references:
            if "Template_" in ref.tag_name or proto.source_name in ref.tag_name:
                template_tags.add(ref.tag_name)

    # Parse template root for XML operations
    try:
        root = ET.fromstring(template_xml)
    except ET.ParseError:
        return {
            "ok": False,
            "xml": None, "xml_path": None,
            "warnings": ["模板 XML 格式无效"],
            "diagnostics": diagnostics,
        }

    used_ids = collect_existing_ids(root)

    # Build screen XML
    meta = ir.get("meta", {})
    screen_name = meta.get("screen_name", "GeneratedScreen")
    resolution = meta.get("resolution", "1280x800")
    try:
        w, h = resolution.split("x") if "x" in resolution else (1280, 800)
        w, h = int(w), int(h)
    except Exception:
        w, h = 1280, 800

    # Generate controls
    all_generated_xml: list[str] = []
    matched_count = 0
    failed_items: list[str] = []

    for screen in project.screens:
        for item in screen.items:
            try:
                proto = registry.find_for_item(item)
            except PrototypeNotFoundError as e:
                failed_items.append(item.id)
                warnings.append(str(e))
                continue

            # Clone prototype
            item_id = item.id
            item_name = item.name or item_id
            item_text = item.text.get("zh-CN", item_id) if item.text else item_id
            tag_binding = item.tag_binding or ""

            cloned = clone_prototype_node(proto.xml_node, item_name, used_ids)

            # Replace geometry
            geo = item.geometry
            replace_geometry(cloned, {
                "x": geo.x, "y": geo.y,
                "width": geo.width, "height": geo.height,
                "radius": geo.radius,
            })

            # Replace text
            if item_text:
                replace_control_text(cloned, item_text)

            # Replace tag references
            old_tags = [t for t in template_tags if t in proto.replaceable_tags or "Template_" in t]
            if old_tags and tag_binding:
                replaced = replace_all_tag_references(cloned, old_tags, tag_binding)
                if replaced == 0 and old_tags:
                    # Try broader replacement
                    for ot in old_tags:
                        replace_all_tag_references(cloned, [ot], tag_binding)

            # Verify no placeholder remains
            remaining = ensure_no_placeholder_tags(cloned, list(template_tags))
            if remaining:
                warnings.append(f"控件 '{item_id}' 残留模板变量: {remaining}")

            # Serialize
            xml_str = ET.tostring(cloned, encoding="unicode")
            all_generated_xml.append(xml_str)
            matched_count += 1

            diagnostics["prototype_matched"].append({
                "item_id": item_id,
                "prototype_id": proto.prototype_id,
                "item_type": item.type.value if hasattr(item.type, "value") else str(item.type),
                "tag_replaced": tag_binding,
                "placeholder_remaining": len(remaining) if remaining else 0,
            })

    # ---- Step 4: Build screen XML ----
    screen_xml_parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<Document xmlns="http://www.siemens.com/automation/SimaticML">',
        f'  <SW.Screen>',
        f'    <AttributeList><Name>{screen_name}</Name><Width>{w}</Width><Height>{h}</Height></AttributeList>',
        f'    <ObjectList>',
    ]
    screen_xml_parts.extend(f"      {ctrl}" for ctrl in all_generated_xml)
    screen_xml_parts.append(f'    </ObjectList>')
    screen_xml_parts.append(f'  </SW.Screen>')
    screen_xml_parts.append(f'</Document>')

    screen_xml = "\n".join(screen_xml_parts)

    # ---- Step 5: Pre-import validation ----
    tag_names = [t.name for t in project.tags]
    item_ids = [item.id for screen in project.screens for item in screen.items]
    forbidden_placeholders = [t for t in template_tags if "Template_" in t]

    pre_diags = validate_generated_screen_xml(
        screen_xml, tag_names, forbidden_placeholders, item_ids
    )
    pre_errors = [d for d in pre_diags if d.get("severity") == "error"]
    pre_warnings = [d for d in pre_diags if d.get("severity") == "warning"]

    diagnostics["pre_import_validated"] = {
        "errors": len(pre_errors),
        "warnings": len(pre_warnings),
        "error_details": [d.get("message", "") for d in pre_errors],
    }

    ok = len(pre_errors) == 0 and len(failed_items) == 0

    return {
        "ok": ok,
        "xml": screen_xml if ok else None,
        "xml_path": None,
        "warnings": warnings + [d.get("message", "") for d in pre_warnings],
        "diagnostics": diagnostics,
        "matched_count": matched_count,
        "failed_items": failed_items,
    }

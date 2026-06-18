# -*- coding: utf-8 -*-
"""
HMI 画面 IR（中间表示）校验与归一化。
对大模型产出的 JSON 做结构检查、补默认值、交叉引用校验，
保证后续 SimaticML 生成与前端预览拿到的是干净数据。
"""

VALID_OBJECT_TYPES = {
    "IOField", "SymbolicIOField", "Button", "Indicator", "Text"
}
VALID_MODES = {"Input", "Output", "InputOutput"}
VALID_FORMATS = {"Decimal", "String", "Hex", "Binary"}
VALID_DATATYPES = {"Bool", "Int", "DInt", "Real", "Word", "String"}
VALID_RES = {
    "1920x1080", "1366x768", "1280x800", "1024x768",
    "800x480", "640x480", "480x272", "320x240",
}
VALID_HMI_TYPES = {"Basic", "Comfort", "Unified"}


class IRValidationError(Exception):
    pass


def _req(d, key, where):
    if key not in d or d[key] in (None, ""):
        raise IRValidationError(f"{where} 缺少必填字段 '{key}'")
    return d[key]


def _normalize_hmi_type(value: str) -> str:
    """把用户/模型输入的 HMI 类型归一化为 Basic / Comfort / Unified。"""
    raw = str(value or "Comfort").strip()
    low = raw.lower()
    if "unified" in low:
        return "Unified"
    if "basic" in low or "ktp" in low:
        return "Basic"
    if "comfort" in low:
        return "Comfort"
    return raw if raw in VALID_HMI_TYPES else "Comfort"


def _unique_id(base_id: str, seen_ids: set) -> str:
    """生成唯一对象 ID，并登记到 seen_ids。"""
    candidate = str(base_id or "Text")
    if candidate not in seen_ids:
        seen_ids.add(candidate)
        return candidate
    idx = 1
    while f"{candidate}_{idx}" in seen_ids:
        idx += 1
    unique = f"{candidate}_{idx}"
    seen_ids.add(unique)
    return unique


def _estimate_text_width(text: str, font_size: int) -> int:
    """粗略估算静态文本宽度，避免自动生成的标签/单位被截断。"""
    total = 0.0
    for ch in str(text or ""):
        # 中文/全角字符约占一个字号宽度，ASCII 约占 0.55 个字号。
        total += 1.0 if ord(ch) > 127 else 0.55
    return int(round(total * max(8, int(font_size)))) + 10


def _make_text_object(
    seen_ids: set,
    obj_id: str,
    x: int,
    y: int,
    width: int,
    height: int,
    text: str,
    font_size: int,
    bold: bool = False,
    color: str = "#C9D3DE",
) -> dict:
    """构造一个真实 Text 对象。TIA 中静态文字本身也是 ScreenItem。"""
    return {
        "id": _unique_id(obj_id, seen_ids),
        "type": "Text",
        "x": int(max(0, x)),
        "y": int(max(0, y)),
        "width": int(max(1, width)),
        "height": int(max(1, height)),
        "text": str(text or ""),
        "font_size": int(max(8, font_size)),
        "bold": bool(bold),
        "color": color or "#C9D3DE",
    }


def _expand_label_and_unit_text_objects(norm_objs: list, seen_ids: set, warnings: list) -> list:
    """把 label/unit 从控件附属字段展开为真实 Text 对象。

    原因：WinCC/TIA 中每一段静态文字都是独立 ScreenItem。如果 IR 里只把
    IOField/Indicator 的 label、IOField 的 unit 当作属性，前端统计会少算，
    模板 XML 路线也无法为这些文字创建/克隆控件，导致导入画面不完整。

    展开后会清空原控件上的 label/unit，避免预览渲染和 SimaticML 生成时重复画文字。
    """
    expanded = []
    auto_count = 0
    for o in norm_objs:
        otype = o.get("type")

        # 左侧标签：IOField / SymbolicIOField / Indicator 都需要真实 TextField。
        label = str(o.get("label") or "").strip()
        if label and otype in ("IOField", "SymbolicIOField", "Indicator"):
            fs = max(10, min(14, int(o.get("font_size", 16)) - 2))
            h = int(o.get("height", int(o.get("radius", 20)) * 2))
            w = min(128, max(42, _estimate_text_width(label, fs)))
            x = int(o.get("x", 0)) - w - 8
            y = int(o.get("y", 0)) + max(0, (h - fs) // 2) - 2
            expanded.append(_make_text_object(
                seen_ids=seen_ids,
                obj_id=f"{o.get('id', otype)}_lbl",
                x=x,
                y=y,
                width=w,
                height=max(20, fs + 8),
                text=label,
                font_size=fs,
                bold=False,
                color="#C9D3DE",
            ))
            o["label"] = ""
            auto_count += 1

        expanded.append(o)

        # 右侧单位：IOField 的单位同样是独立 TextField。
        unit = str(o.get("unit") or "").strip()
        if unit and otype == "IOField":
            fs = max(10, min(14, int(o.get("font_size", 16)) - 2))
            w = min(96, max(32, _estimate_text_width(unit, fs)))
            h = int(o.get("height", 40))
            x = int(o.get("x", 0)) + int(o.get("width", 140)) + 8
            y = int(o.get("y", 0)) + max(0, (h - fs) // 2) - 2
            expanded.append(_make_text_object(
                seen_ids=seen_ids,
                obj_id=f"{o.get('id', otype)}_unit",
                x=x,
                y=y,
                width=w,
                height=max(20, fs + 8),
                text=unit,
                font_size=fs,
                bold=False,
                color="#9AA7B4",
            ))
            o["unit"] = ""
            auto_count += 1

    if auto_count:
        warnings.append(f"已将 {auto_count} 个 label/unit 展开为真实 Text 对象，前端对象数与 TIA 对象数保持一致")
    return expanded


def validate_ir(ir: dict) -> dict:
    """校验并返回归一化后的 IR；不合法则抛 IRValidationError。"""
    if not isinstance(ir, dict):
        raise IRValidationError("IR 必须是 JSON 对象")

    # ---- meta ----
    meta = ir.get("meta") or {}
    meta.setdefault("screen_name", "Screen_1")
    meta.setdefault("title", meta["screen_name"])
    meta.setdefault("description", "")
    warnings = []

    res = str(meta.get("resolution", "1280x800") or "1280x800").strip()
    if res not in VALID_RES:
        parsed = parse_resolution(res)
        if parsed:
            res = f"{parsed[0]}x{parsed[1]}"
            warnings.append(f"使用自定义 HMI 分辨率 {res}，请确认与目标面板一致。")
        else:
            warnings.append(f"非法分辨率 '{res}'，已回退到 1280x800。")
            res = "1280x800"
    meta["resolution"] = res

    meta["hmi_type"] = _normalize_hmi_type(meta.get("hmi_type", "Comfort"))

    # 双路线生成可选字段（默认值）
    VALID_GEN_MODES = {"auto", "unified_direct", "classic_template_xml", "simaticml"}
    gen_mode = meta.get("generation_mode", "auto")
    if gen_mode not in VALID_GEN_MODES:
        gen_mode = "auto"
    meta["generation_mode"] = gen_mode
    meta.setdefault("template_screen", "")
    meta.setdefault("template_xml", "")

    ir["meta"] = meta

    # 画面像素尺寸
    w, h = res.split("x")
    screen_w, screen_h = int(w), int(h)

    # ---- tags ----
    tags = ir.get("tags") or []
    tag_names = set()
    norm_tags = []
    for i, t in enumerate(tags):
        name = _req(t, "name", f"tags[{i}]")
        dtype = t.get("data_type", "Bool")
        if dtype not in VALID_DATATYPES:
            dtype = "Bool"
        norm_tags.append({
            "name": name,
            "data_type": dtype,
            "address": t.get("address", ""),
            "comment": t.get("comment", ""),
        })
        tag_names.add(name)
    ir["tags"] = norm_tags

    # ---- text_lists ----
    text_lists = ir.get("text_lists") or []
    list_names = set()
    norm_lists = []
    for i, tl in enumerate(text_lists):
        name = _req(tl, "name", f"text_lists[{i}]")
        entries = tl.get("entries") or []
        norm_entries = []
        for e in entries:
            norm_entries.append({
                "value": int(e.get("value", 0)),
                "text": str(e.get("text", "")),
            })
        norm_lists.append({"name": name, "entries": norm_entries})
        list_names.add(name)
    ir["text_lists"] = norm_lists

    # ---- scripts ----
    scripts = ir.get("scripts") or []
    script_names = set()
    norm_scripts = []
    for i, s in enumerate(scripts):
        name = _req(s, "name", f"scripts[{i}]")
        norm_scripts.append({
            "name": name,
            "language": s.get("language", "VBS"),
            "purpose": s.get("purpose", ""),
            "code": s.get("code", ""),
        })
        script_names.add(name)
    ir["scripts"] = norm_scripts
    if meta.get("hmi_type") == "Basic" and norm_scripts:
        warnings.append(
            "当前 IR 目标为 Basic 面板：Basic/KTP Basic 对脚本和高级控件支持有限；"
            "推荐通过 Basic 面板导出的模板 XML 预置按钮事件或改为 PLC 变量触发。"
        )

    # ---- objects ----
    objects = ir.get("objects") or []
    if not objects:
        raise IRValidationError("objects 为空，画面没有任何对象")

    norm_objs = []
    seen_ids = set()
    for i, o in enumerate(objects):
        where = f"objects[{i}]"
        otype = _req(o, "type", where)
        if otype not in VALID_OBJECT_TYPES:
            raise IRValidationError(f"{where} 非法对象类型 '{otype}'")
        oid = o.get("id") or f"{otype}_{i}"
        if oid in seen_ids:
            oid = f"{oid}_{i}"
        seen_ids.add(oid)

        x = int(o.get("x", 0)); y = int(o.get("y", 0))
        # 越界裁剪提示（不强制报错）
        if x < 0 or y < 0 or x > screen_w or y > screen_h:
            warnings.append(f"{where}({oid}) 坐标超出画面范围，已保留原值")

        base = {"id": oid, "type": otype, "x": x, "y": y}
        # 模板引用（可选，仅经典模板 XML 模式使用）
        if o.get("template_ref"):
            base["template_ref"] = o["template_ref"]

        if otype in ("IOField", "SymbolicIOField"):
            base["width"] = int(o.get("width", 140))
            base["height"] = int(o.get("height", 40))
            mode = o.get("mode", "Output")
            base["mode"] = mode if mode in VALID_MODES else "Output"
            tag = _req(o, "process_tag", where)
            if tag not in tag_names:
                warnings.append(f"{where}({oid}) 关联变量 '{tag}' 未在 tags 中声明")
            base["process_tag"] = tag
            base["font_size"] = int(o.get("font_size", 16))
            base["label"] = o.get("label", "")
            if otype == "IOField":
                fmt = o.get("display_format", "Decimal")
                base["display_format"] = fmt if fmt in VALID_FORMATS else "Decimal"
                base["decimal_digits"] = int(o.get("decimal_digits", 0))
                base["unit"] = o.get("unit", "")
            else:
                tl = _req(o, "text_list", where)
                if tl not in list_names:
                    warnings.append(f"{where}({oid}) 引用文本列表 '{tl}' 未声明")
                base["text_list"] = tl

        elif otype == "Button":
            base["width"] = int(o.get("width", 120))
            base["height"] = int(o.get("height", 50))
            base["text"] = o.get("text", "按钮")
            for ev in ("press_script", "release_script", "click_script"):
                sc = o.get(ev)
                if sc and sc not in script_names:
                    warnings.append(f"{where}({oid}) 事件 {ev} 引用脚本 '{sc}' 未定义")
                base[ev] = sc or None
            base["background_color"] = o.get("background_color", "#2BB673")
            if meta.get("hmi_type") == "Basic" and any(base.get(ev) for ev in ("press_script", "release_script", "click_script")):
                warnings.append(
                    f"{where}({oid}) 绑定了脚本事件；Basic 面板建议使用模板中预置的按钮事件或 PLC 变量触发。"
                )

        elif otype == "Indicator":
            base["radius"] = int(o.get("radius", 22))
            tag = _req(o, "process_tag", where)
            if tag not in tag_names:
                warnings.append(f"{where}({oid}) 关联变量 '{tag}' 未声明")
            base["process_tag"] = tag
            base["color_on"] = o.get("color_on", "#27D17F")
            base["color_off"] = o.get("color_off", "#3A4250")
            base["blink"] = bool(o.get("blink", False))
            base["label"] = o.get("label", "")

        elif otype == "Text":
            base["width"] = int(o.get("width", 200))
            base["height"] = int(o.get("height", 40))
            base["text"] = o.get("text", "")
            base["font_size"] = int(o.get("font_size", 18))
            base["bold"] = bool(o.get("bold", False))
            base["color"] = o.get("color", "#E6EDF3")

        norm_objs.append(base)

    # WinCC/TIA 中静态文字本身也是画面对象。
    # 因此把 IOField/Indicator 的 label 与 IOField 的 unit 展开为显式 Text 对象，
    # 避免“前端 9 个对象、TIA 实际 15 个对象”的数量不一致。
    norm_objs = _expand_label_and_unit_text_objects(norm_objs, seen_ids, warnings)

    ir["objects"] = norm_objs
    ir["_warnings"] = warnings
    ir["_screen_size"] = {"width": screen_w, "height": screen_h}
    return ir


# ---------------------------------------------------------------------------
# 分辨率 / 坐标适配辅助函数
# ---------------------------------------------------------------------------

def parse_resolution(value: str):
    """解析 "800x480" 形式的分辨率，失败返回 None。"""
    if not value or not isinstance(value, str) or "x" not in value.lower():
        return None
    try:
        w, h = value.lower().split("x", 1)
        w, h = int(w.strip()), int(h.strip())
        if w > 0 and h > 0:
            return w, h
    except Exception:
        return None
    return None


def scale_ir_to_resolution(ir: dict, target_resolution: str, in_place: bool = False) -> dict:
    """把 IR 的 meta.resolution、_screen_size 以及对象坐标统一到目标分辨率。

    用途：让前端预览、视觉审查、模板 XML 导入使用同一坐标系。
    例如 LLM 输出 1280x800，但实际 Comfort 面板为 800x480 时，
    这里会把 x/y/width/height/radius/font_size 按比例缩放。
    """
    import copy

    target = parse_resolution(target_resolution)
    if not target:
        return ir

    result = ir if in_place else copy.deepcopy(ir)
    meta = result.setdefault("meta", {})

    old_size = None
    ss = result.get("_screen_size") or {}
    try:
        old_size = (int(ss.get("width")), int(ss.get("height")))
    except Exception:
        old_size = None
    if not old_size:
        old_size = parse_resolution(meta.get("resolution", ""))
    if not old_size:
        old_size = target

    ow, oh = old_size
    tw, th = target
    if ow <= 0 or oh <= 0:
        return result

    if (ow, oh) != (tw, th):
        sx, sy = tw / ow, th / oh
        sm = min(sx, sy)
        for o in result.get("objects") or []:
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
            if "font_size" in o and o["font_size"] is not None:
                try:
                    o["font_size"] = max(10, int(round(float(o["font_size"]) * sm)))
                except Exception:
                    pass

        result.setdefault("_warnings", []).append(
            f"已将 IR 布局从 {ow}x{oh} 缩放到目标 HMI 分辨率 {tw}x{th}。"
        )

    meta["resolution"] = f"{tw}x{th}"
    result["_screen_size"] = {"width": tw, "height": th}
    return result

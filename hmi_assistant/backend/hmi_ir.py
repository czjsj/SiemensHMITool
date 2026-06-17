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
VALID_RES = {"1920x1080", "1280x800", "1024x768", "800x480"}


class IRValidationError(Exception):
    pass


def _req(d, key, where):
    if key not in d or d[key] in (None, ""):
        raise IRValidationError(f"{where} 缺少必填字段 '{key}'")
    return d[key]


def validate_ir(ir: dict) -> dict:
    """校验并返回归一化后的 IR；不合法则抛 IRValidationError。"""
    if not isinstance(ir, dict):
        raise IRValidationError("IR 必须是 JSON 对象")

    # ---- meta ----
    meta = ir.get("meta") or {}
    meta.setdefault("screen_name", "Screen_1")
    meta.setdefault("title", meta["screen_name"])
    meta.setdefault("description", "")
    res = meta.get("resolution", "1280x800")
    if res not in VALID_RES:
        res = "1280x800"
    meta["resolution"] = res
    meta.setdefault("hmi_type", "Comfort")
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

    # ---- objects ----
    objects = ir.get("objects") or []
    if not objects:
        raise IRValidationError("objects 为空，画面没有任何对象")

    warnings = []
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

    ir["objects"] = norm_objs
    ir["_warnings"] = warnings
    ir["_screen_size"] = {"width": screen_w, "height": screen_h}
    return ir

# -*- coding: utf-8 -*-
"""
HMI 画面 IR（中间表示）校验与归一化。
对大模型产出的 JSON 做结构检查、补默认值、交叉引用校验，
保证后续 SimaticML 生成与前端预览拿到的是干净数据。

本版重点优化：
1. 支持 Basic / Comfort / Unified；
2. 接受常见分辨率及合法自定义 WxH 分辨率；
3. 在 validate_ir() 末尾增加轻量级自动排版优化，
   重点缓解控件重叠、行间距过小、同一行控件过密的问题。
"""

from __future__ import annotations

import copy

VALID_OBJECT_TYPES = {
    "IOField", "SymbolicIOField", "Button", "Indicator", "Text"
}
VALID_MODES = {"Input", "Output", "InputOutput"}
VALID_FORMATS = {"Decimal", "String", "Hex", "Binary"}
VALID_DATATYPES = {"Bool", "Int", "DInt", "Real", "Word", "String"}
VALID_HMI_TYPES = {"Basic", "Comfort", "Unified"}
VALID_TAG_MODES = {"momentary", "toggle"}

# 变量命名前缀规则（VariableEngine 同步）
TAG_PREFIX_MAP = {
    "Button":    "BTN_",        # 瞬时按钮
    "Indicator": "STS_",        # 运行/状态指示灯（报警类用 LMP_）
    "IOField":   "IO_",
    "SymbolicIOField": "SIO_",
}
VALID_RES = {
    "1920x1080", "1280x800", "1024x768", "800x480", "480x272",
    "640x480", "320x240"
}


class IRValidationError(Exception):
    pass


def _req(d, key, where):
    if key not in d or d[key] in (None, ""):
        raise IRValidationError(f"{where} 缺少必填字段 '{key}'")
    return d[key]


def parse_resolution(value: str):
    """解析 '800x480' 形式的分辨率，失败返回 None。"""
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


def _bbox(o: dict) -> tuple[int, int, int, int]:
    """对象外接矩形 bbox: (x1, y1, x2, y2)。"""
    if o.get("type") == "Indicator":
        r = int(o.get("radius", 22))
        x = int(o.get("x", 0)) - r
        y = int(o.get("y", 0)) - r
        return x, y, x + 2 * r, y + 2 * r
    x = int(o.get("x", 0))
    y = int(o.get("y", 0))
    w = int(o.get("width", 0))
    h = int(o.get("height", 0))
    return x, y, x + max(1, w), y + max(1, h)


def _move_to_bbox(o: dict, x1: int, y1: int):
    """把对象移动到给定左上角。"""
    if o.get("type") == "Indicator":
        r = int(o.get("radius", 22))
        o["x"] = int(x1 + r)
        o["y"] = int(y1 + r)
    else:
        o["x"] = int(x1)
        o["y"] = int(y1)


def _is_title_text(o: dict) -> bool:
    return (
        o.get("type") == "Text" and (
            bool(o.get("bold")) or int(o.get("font_size", 0)) >= 22 or o.get("id") == "TXT_Title"
        )
    )


def _text_width(text: str, font_size: int) -> int:
    """估算文本像素宽度（CJK 近似全角，ASCII 按 0.6 倍）。"""
    if not text:
        return 0
    cjk = sum(1 for c in text if ord(c) > 0x2E7F)
    other = len(text) - cjk
    return int(font_size * cjk + font_size * 0.6 * other)


def _is_label_text(o: dict) -> bool:
    """判断 Text 对象是否为控件的标签文字（非标题）。"""
    if o.get("type") != "Text" or _is_title_text(o):
        return False
    oid = (o.get("id") or "").lower()
    return oid.endswith("_label") or oid.endswith("_lbl")


def _find_control_for_label(label: dict, controls: list) -> dict | None:
    """根据 id 前缀和邻近关系找到标签对应的控件。"""
    lid = label.get("id", "")
    base = lid
    for suf in ("_Label", "_lbl", "_Lbl", "_label", "_LBL"):
        if base.endswith(suf):
            base = base[:-len(suf)]
            break
    name_part = base[4:] if base.startswith("TXT_") else base
    for ctrl in controls:
        cid = ctrl.get("id", "")
        for prefix in ("IO_", "SIO_", "LMP_", "BTN_", "STS_"):
            if cid.startswith(prefix) and cid[len(prefix):] == name_part:
                return ctrl
    lx1, ly1, lx2, ly2 = _bbox(label)
    candidates = []
    for ctrl in controls:
        if ctrl.get("type") not in ("IOField", "SymbolicIOField", "Indicator"):
            continue
        cx1, cy1, cx2, cy2 = _bbox(ctrl)
        v_overlap = min(ly2, cy2) - max(ly1, cy1)
        if v_overlap <= 0:
            continue
        gap = cx1 - lx2
        if -10 <= gap <= 140:
            candidates.append((gap, ctrl))
    if candidates:
        candidates.sort(key=lambda t: t[0])
        return candidates[0][1]
    return None


def _relocate_label(label: dict, ctrl: dict, sw: int, sh: int,
                    margin_x: int, margin_y: int):
    """将标签 Text 重定位到控件正上方（IO 域）或正下方（指示灯），居中对齐。"""
    text = label.get("text", "")
    fs = int(label.get("font_size", 16))
    tw = _text_width(text, fs)
    th = fs + 4
    gap = 10
    ctype = ctrl.get("type")
    if ctype in ("IOField", "SymbolicIOField"):
        cw = int(ctrl.get("width", 140))
        cx = int(ctrl.get("x", 0)) + cw // 2
        cy = int(ctrl.get("y", 0))
        ly = cy - gap - th
        if ly < margin_y:
            delta = margin_y - ly
            ctrl["y"] = int(ctrl.get("y", 0)) + delta
            ly = margin_y
        label["x"] = cx
        label["y"] = ly
    elif ctype == "Indicator":
        r = int(ctrl.get("radius", 22))
        cx = int(ctrl.get("x", 0)) + r
        cy = int(ctrl.get("y", 0))
        ly = cy + 2 * r + gap
        if ly + th > sh - margin_y:
            delta = (ly + th) - (sh - margin_y)
            ctrl["y"] = int(ctrl.get("y", 0)) - delta
            ly = cy - delta + 2 * r + gap
        label["x"] = cx
        label["y"] = ly
    label["width"] = tw + 12
    label["height"] = th
    label["_anchor"] = "middle"
    label["_attached_to"] = ctrl.get("id", "")
    if ctrl.get("label"):
        ctrl["label"] = ""


def _associate_and_relocate_labels(objects: list, sw: int, sh: int,
                                   margin_x: int, margin_y: int):
    """关联标签 Text 与控件，并重定位为垂直分组居中布局。"""
    controls = [o for o in objects
                if o.get("type") in ("IOField", "SymbolicIOField", "Indicator")]
    for label in objects:
        if not _is_label_text(label):
            continue
        ctrl = _find_control_for_label(label, controls)
        if ctrl:
            _relocate_label(label, ctrl, sw, sh, margin_x, margin_y)


def _object_center_y(o: dict) -> float:
    x1, y1, x2, y2 = _bbox(o)
    return (y1 + y2) / 2.0


def _min_h_gap(a: dict, b: dict) -> int:
    ta, tb = a.get("type"), b.get("type")
    pair = {ta, tb}
    if pair == {"Button"}:
        return 24
    if pair == {"Indicator"}:
        return 24
    if ta == "Text" or tb == "Text":
        return 12
    return 20


def _min_v_gap(prev_row: list[dict], next_row: list[dict]) -> int:
    types = {o.get("type") for o in prev_row + next_row}
    if "Button" in types:
        return 24
    return 24


def _row_bounds(row: list[dict]) -> tuple[int, int, int, int]:
    xs1, ys1, xs2, ys2 = [], [], [], []
    for o in row:
        x1, y1, x2, y2 = _bbox(o)
        xs1.append(x1); ys1.append(y1); xs2.append(x2); ys2.append(y2)
    return min(xs1), min(ys1), max(xs2), max(ys2)


def _cluster_rows(objs: list[dict], tolerance: int = 26) -> list[list[dict]]:
    rows: list[list[dict]] = []
    for o in sorted(objs, key=lambda item: (_bbox(item)[1], _bbox(item)[0])):
        cy = _object_center_y(o)
        placed = False
        for row in rows:
            row_cy = sum(_object_center_y(x) for x in row) / len(row)
            if abs(cy - row_cy) <= tolerance:
                row.append(o)
                placed = True
                break
        if not placed:
            rows.append([o])
    for row in rows:
        row.sort(key=lambda item: _bbox(item)[0])
    rows.sort(key=lambda row: _row_bounds(row)[1])
    return rows


def _optimize_layout(ir: dict) -> dict:
    """对对象做轻量自动排版。"""
    screen = ir.get("_screen_size") or {}
    sw = int(screen.get("width", 1280))
    sh = int(screen.get("height", 800))
    margin_x = 24 if sw >= 800 else 18
    margin_y = 20 if sh >= 480 else 14

    objects = ir.get("objects") or []
    if not objects:
        return ir

    warnings = ir.setdefault("_warnings", [])

    # 标题强制水平居中：使用中心锚点，文字中心与画布中心线重合。
    for o in objects:
        if _is_title_text(o):
            w = int(o.get("width", min(360, sw - 2 * margin_x)))
            o["width"] = min(w, max(80, sw - 2 * margin_x))
            o["x"] = sw // 2
            o["_anchor"] = "middle"
            o["y"] = max(margin_y, min(int(o.get("y", margin_y)), margin_y + 12))
            break

    title_ids = {o.get("id") for o in objects if _is_title_text(o)}
    controls = [o for o in objects if o.get("id") not in title_ids]
    if not controls:
        return ir

    rows = _cluster_rows(controls)

    # 逐行做水平对齐与最小间距修复。
    for row in rows:
        row.sort(key=lambda item: _bbox(item)[0])
        top_targets = [_bbox(o)[1] for o in row]
        target_top = int(round(sum(top_targets) / len(top_targets)))

        for idx, o in enumerate(row):
            x1, y1, x2, y2 = _bbox(o)
            _move_to_bbox(o, x1, target_top)
            if idx == 0:
                x1, y1, x2, y2 = _bbox(o)
                if x1 < margin_x:
                    _move_to_bbox(o, margin_x, y1)
                continue

            prev = row[idx - 1]
            px1, py1, px2, py2 = _bbox(prev)
            cx1, cy1, cx2, cy2 = _bbox(o)
            min_gap = _min_h_gap(prev, o)
            if cx1 < px2 + min_gap:
                cx1 = px2 + min_gap
                _move_to_bbox(o, cx1, cy1)

        # 如果该行整体超出右边界，整行左移到可见范围内。
        _, _, rx2, _ = _row_bounds(row)
        max_right = sw - margin_x
        if rx2 > max_right:
            shift = rx2 - max_right
            for o in row:
                x1, y1, x2, y2 = _bbox(o)
                _move_to_bbox(o, max(margin_x, x1 - shift), y1)

    # 逐行拉开垂直间距，避免区块过密。
    rows = _cluster_rows(controls)
    for i in range(1, len(rows)):
        prev_row = rows[i - 1]
        row = rows[i]
        _, _, _, prev_bottom = _row_bounds(prev_row)
        _, row_top, _, _ = _row_bounds(row)
        min_gap = _min_v_gap(prev_row, row)
        if row_top < prev_bottom + min_gap:
            delta = (prev_bottom + min_gap) - row_top
            for o in row:
                x1, y1, x2, y2 = _bbox(o)
                _move_to_bbox(o, x1, y1 + delta)

    # 多轮全局重叠修复：后出现的对象尽量向下避让。
    all_objs = sorted(objects, key=lambda item: (_bbox(item)[1], _bbox(item)[0]))
    for _ in range(3):
        moved = False
        for i in range(len(all_objs)):
            ax1, ay1, ax2, ay2 = _bbox(all_objs[i])
            for j in range(i + 1, len(all_objs)):
                bx1, by1, bx2, by2 = _bbox(all_objs[j])
                overlap_x = min(ax2, bx2) - max(ax1, bx1)
                overlap_y = min(ay2, by2) - max(ay1, by1)
                if overlap_x > 0 and overlap_y > 0:
                    shift = overlap_y + 12
                    _move_to_bbox(all_objs[j], bx1, by1 + shift)
                    moved = True
        if not moved:
            break

    # 最终边界裁剪，保证对象不出界。
    for o in all_objs:
        x1, y1, x2, y2 = _bbox(o)
        width = x2 - x1
        height = y2 - y1
        if x1 < margin_x:
            x1 = margin_x
        if y1 < margin_y:
            y1 = margin_y
        if x1 + width > sw - margin_x:
            x1 = max(margin_x, sw - margin_x - width)
        if y1 + height > sh - margin_y:
            y1 = max(margin_y, sh - margin_y - height)
        _move_to_bbox(o, x1, y1)

    # 标签 Text 与控件的垂直分组居中布局（IO 域标签在正上方，指示灯标签在正下方）。
    _associate_and_relocate_labels(objects, sw, sh, margin_x, margin_y)

    warnings.append("已对 IR 自动执行轻量布局优化：对齐、最小间距、重叠与越界修正。")
    ir["_layout_optimized"] = True
    return ir


def validate_ir(ir: dict) -> dict:
    """校验并返回归一化后的 IR；不合法则抛 IRValidationError。"""
    if not isinstance(ir, dict):
        raise IRValidationError("IR 必须是 JSON 对象")

    meta = ir.get("meta") or {}
    meta.setdefault("screen_name", "Screen_1")
    meta.setdefault("title", meta["screen_name"])
    meta.setdefault("description", "")

    res = meta.get("resolution", "1280x800")
    if res not in VALID_RES and not parse_resolution(res):
        res = "1280x800"
    meta["resolution"] = res

    hmi_type = meta.get("hmi_type", "Comfort")
    if hmi_type not in VALID_HMI_TYPES:
        hmi_type = "Comfort"
    meta["hmi_type"] = hmi_type

    VALID_GEN_MODES = {"auto", "unified_direct", "classic_template_xml", "simaticml"}
    gen_mode = meta.get("generation_mode", "auto")
    if gen_mode not in VALID_GEN_MODES:
        gen_mode = "auto"
    meta["generation_mode"] = gen_mode
    meta.setdefault("template_screen", "")
    meta.setdefault("template_xml", "")
    ir["meta"] = meta

    screen_w, screen_h = parse_resolution(res) or (1280, 800)

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

        x = int(o.get("x", 0))
        y = int(o.get("y", 0))
        if x < 0 or y < 0 or x > screen_w or y > screen_h:
            warnings.append(f"{where}({oid}) 坐标超出画面范围，已保留原值")

        base = {"id": oid, "type": otype, "x": x, "y": y}
        if o.get("template_ref"):
            base["template_ref"] = o["template_ref"]

        if otype in ("IOField", "SymbolicIOField"):
            base["width"] = int(o.get("width", 140))
            base["height"] = int(o.get("height", 40))
            mode = o.get("mode", "Output")
            base["mode"] = mode if mode in VALID_MODES else "Output"
            # 自动生成 process_tag（若缺失则按前缀规则默认）
            prefix = TAG_PREFIX_MAP.get(otype, "IO_")
            from backend.utils.tag_prefix_utils import ensure_tag_prefix
            tag = o.get("process_tag") or ensure_tag_prefix(oid, prefix)
            if tag not in tag_names:
                # 自动补全到 tags 列表
                dtype = o.get("data_type", "Real")
                if dtype not in VALID_DATATYPES:
                    dtype = "Real" if otype == "IOField" else "Int"
                ir.setdefault("tags", []).append({
                    "name": tag, "data_type": dtype,
                    "address": o.get("address", ""),
                    "comment": f"自动生成 — {o.get('label', oid)}",
                })
                tag_names.add(tag)
                warnings.append(f"{where}({oid}) 变量 '{tag}' 自动添加到 tags 列表。")
            base["process_tag"] = tag
            base["font_size"] = int(o.get("font_size", 16))
            base["label"] = o.get("label", "")
            if otype == "IOField":
                fmt = o.get("display_format", "Decimal")
                base["display_format"] = fmt if fmt in VALID_FORMATS else "Decimal"
                base["decimal_digits"] = int(o.get("decimal_digits", 0))
                base["unit"] = o.get("unit", "")
            else:
                tl = o.get("text_list") or ""
                if not tl:
                    warnings.append(f"{where}({oid}) SymbolicIOField 缺少 text_list 引用")
                elif tl not in list_names:
                    warnings.append(f"{where}({oid}) 引用文本列表 '{tl}' 未声明")
                base["text_list"] = tl

        elif otype == "Button":
            base["width"] = int(o.get("width", 120))
            base["height"] = int(o.get("height", 50))
            base["text"] = o.get("text", "按钮")
            # 自动生成 process_tag（若缺失则按前缀规则默认）
            tag_mode = o.get("tag_mode") or "momentary"
            if tag_mode not in VALID_TAG_MODES:
                tag_mode = "momentary"
            base["tag_mode"] = tag_mode
            btn_prefix = "MEM_" if tag_mode == "toggle" else "BTN_"
            from backend.utils.tag_prefix_utils import ensure_tag_prefix
            btn_tag = o.get("process_tag") or ensure_tag_prefix(oid, btn_prefix)
            if btn_tag not in tag_names:
                ir.setdefault("tags", []).append({
                    "name": btn_tag, "data_type": "Bool",
                    "address": o.get("address", ""),
                    "comment": f"自动生成 — {o.get('text', oid)}"
                           f"{'（自保持切换）' if tag_mode == 'toggle' else '（瞬时按钮）'}",
                })
                tag_names.add(btn_tag)
                warnings.append(f"{where}({oid}) 变量 '{btn_tag}' 自动添加到 tags 列表。")
            base["process_tag"] = btn_tag
            for ev in ("press_script", "release_script", "click_script"):
                sc = o.get(ev)
                if sc and sc not in script_names:
                    warnings.append(f"{where}({oid}) 事件 {ev} 引用脚本 '{sc}' 未定义")
                base[ev] = sc or None
            base["background_color"] = o.get("background_color", "#2BB673")

        elif otype == "Indicator":
            base["radius"] = int(o.get("radius", 22))
            # 自动生成 process_tag（若缺失则按前缀规则默认；报警类用 LMP_，状态类用 STS_）
            is_alarm_like = bool(
                o.get("blink") or
                (o.get("color_on") or "").startswith("#E2") or
                (o.get("color_on") or "").startswith("#e2")
            )
            ind_prefix = "LMP_" if is_alarm_like else "STS_"
            from backend.utils.tag_prefix_utils import ensure_tag_prefix
            ind_tag = o.get("process_tag") or ensure_tag_prefix(oid, ind_prefix)
            if ind_tag not in tag_names:
                ir.setdefault("tags", []).append({
                    "name": ind_tag, "data_type": "Bool",
                    "address": o.get("address", ""),
                    "comment": f"自动生成 — {o.get('label', oid)}"
                           f"{'（报警/故障指示）' if is_alarm_like else '（状态指示）'}",
                })
                tag_names.add(ind_tag)
                warnings.append(f"{where}({oid}) 变量 '{ind_tag}' 自动添加到 tags 列表。")
            base["process_tag"] = ind_tag
            base["blink_tag"] = o.get("blink_tag") or (ind_tag if o.get("blink") else None)
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
    return _optimize_layout(ir)


def scale_ir_to_resolution(ir: dict, target_resolution: str, in_place: bool = False) -> dict:
    """把 IR 的 meta.resolution、_screen_size 以及对象坐标统一到目标分辨率。"""
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

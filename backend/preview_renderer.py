# -*- coding: utf-8 -*-
"""
HMI 画面预览渲染器
==================
将校验后的 IR 直接绘制为 PNG 图像，供 MiMo 进行视觉审查。
使用 Pillow（项目唯一新依赖，Windows 预编译 wheel，零系统依赖）。

五种 HMI 对象 → Pillow 绘制映射：
  Text           → draw.text()
  IOField        → rounded_rectangle + 居中文本
  SymbolicIOField→ rounded_rectangle + "[列表]" 文本 + 下拉三角
  Button         → rounded_rectangle(填充色) + 居中文本
  Indicator      → 填充圆 + 高光弧 + blink 虚线环
"""
from __future__ import annotations

import io
import os
import struct
from typing import Any, Dict, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

# ---- 字体缓存 ----
_font_cache: Dict[Tuple[int, bool], Optional[ImageFont.FreeTypeFont]] = {}
_DEFAULT_FONT_PATHS = [
    # Windows
    "C:/Windows/Fonts/msyh.ttc",       # Microsoft YaHei (CJK 优先)
    "C:/Windows/Fonts/msyhbd.ttc",     # Microsoft YaHei Bold
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    # Linux
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
]


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """#RRGGBB → (R, G, B)"""
    c = (hex_color or "#000000").lstrip("#")
    if len(c) == 6:
        return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))
    return (0, 0, 0)


def _contrast_color(bg_hex: str) -> str:
    """根据背景色返回合适的前景色（黑或白）。"""
    r, g, b = _hex_to_rgb(bg_hex)
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return "#06281F" if luminance > 140 else "#FFFFFF"


def _get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """获取字体，优先系统字体，找不到则回退到 Pillow 默认字体。"""
    key = (size, bold)
    if key in _font_cache:
        return _font_cache[key]

    font = None
    for fp in _DEFAULT_FONT_PATHS:
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, size)
                break
            except (OSError, IOError, struct.error):
                continue

    if font is None:
        # 回退：从 bold 样式中尝试任意可用路径
        for fp in _DEFAULT_FONT_PATHS:
            if os.path.exists(fp):
                try:
                    font = ImageFont.truetype(fp, size)
                    break
                except (OSError, IOError, struct.error):
                    continue

    if font is None:
        font = ImageFont.load_default()

    _font_cache[key] = font
    return font


# ---------------------------------------------------------------------------
# 各对象绘制函数
# ---------------------------------------------------------------------------

def _draw_text(draw: ImageDraw.Draw, o: Dict[str, Any], _screen_size: Tuple[int, int]):
    """静态文本"""
    x, y = o.get("x", 0), o.get("y", 0)
    text = o.get("text", "")
    font_size = o.get("font_size", 18)
    bold = o.get("bold", False)
    color = o.get("color", "#E6EDF3")
    font = _get_font(font_size, bold)
    if o.get("_anchor") == "middle":
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
        except Exception:
            tw = font_size * len(text)
        draw.text((x - tw // 2, y), text, fill=color, font=font)
    else:
        draw.text((x, y), text, fill=color, font=font)


def _draw_io_label(draw: ImageDraw.Draw, o: Dict[str, Any]):
    """IO 域标签：正上方居中"""
    label = o.get("label", "")
    if not label:
        return
    x = o.get("x", 0)
    y = o.get("y", 0)
    w = o.get("width", 140)
    font_size = 14
    font = _get_font(font_size)
    try:
        bbox = draw.textbbox((0, 0), label, font=font)
        tw = bbox[2] - bbox[0]
    except Exception:
        tw = font_size * len(label)
    cx = x + w // 2
    lx = cx - tw // 2
    ly = y - 10 - font_size
    draw.text((lx, ly), label, fill="#C9D3DE", font=font)


def _draw_indicator_label(draw: ImageDraw.Draw, o: Dict[str, Any]):
    """指示灯标签：正下方居中"""
    label = o.get("label", "")
    if not label:
        return
    x = o.get("x", 0)
    y = o.get("y", 0)
    r = o.get("radius", 22)
    font_size = 13
    font = _get_font(font_size)
    try:
        bbox = draw.textbbox((0, 0), label, font=font)
        tw = bbox[2] - bbox[0]
    except Exception:
        tw = font_size * len(label)
    cx = x + r
    lx = cx - tw // 2
    ly = y + 2 * r + 12
    draw.text((lx, ly), label, fill="#C9D3DE", font=font)


def _draw_io_field(draw: ImageDraw.Draw, o: Dict[str, Any], ss: Tuple[int, int]):
    """文本/数值 IO 域"""
    x, y = o.get("x", 0), o.get("y", 0)
    w, h = o.get("width", 140), o.get("height", 40)
    font_size = o.get("font_size", 16)
    display_format = o.get("display_format", "Decimal")
    unit = o.get("unit", "")

    # 背景框
    draw.rounded_rectangle(
        [x, y, x + w, y + h], radius=5,
        fill="#0E1622", outline="#2A86FF", width=2,
    )

    # 示例值
    sample = "ABC" if display_format == "String" else "123"
    font = _get_font(font_size)
    try:
        bbox = draw.textbbox((0, 0), sample, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        tw, th = font_size * len(sample), font_size
    tx = x + (w - tw) // 2
    ty = y + (h - th) // 2 - 2
    draw.text((tx, ty), sample, fill="#CFE3FF", font=font)

    # 单位
    if unit:
        ux = x + w + 8
        uy = y + (h - font_size) // 2
        ufont = _get_font(font_size - 2)
        draw.text((ux, uy), unit, fill="#9AA7B4", font=ufont)

    _draw_io_label(draw, o)


def _draw_symbolic_io_field(draw: ImageDraw.Draw, o: Dict[str, Any], ss: Tuple[int, int]):
    """符号 IO 域"""
    x, y = o.get("x", 0), o.get("y", 0)
    w, h = o.get("width", 160), o.get("height", 40)
    font_size = o.get("font_size", 16)

    draw.rounded_rectangle(
        [x, y, x + w, y + h], radius=5,
        fill="#15101F", outline="#8A5CFF", width=2,
    )

    font = _get_font(font_size)
    draw.text((x + 10, y + h // 2 - font_size // 2), "〔列表〕", fill="#D9CAFF", font=font)

    # 下拉三角
    tx, ty = x + w - 18, y + h // 2 - 3
    draw.polygon([(tx, ty), (tx + 6, ty + 7), (tx + 12, ty)], fill="#8A5CFF")

    _draw_io_label(draw, o)


def _draw_button(draw: ImageDraw.Draw, o: Dict[str, Any], ss: Tuple[int, int]):
    """按钮"""
    x, y = o.get("x", 0), o.get("y", 0)
    w, h = o.get("width", 120), o.get("height", 50)
    text = o.get("text", "按钮")
    bg = o.get("background_color", "#2BB673")
    has_script = any(o.get(k) for k in ("press_script", "release_script", "click_script"))

    draw.rounded_rectangle(
        [x, y, x + w, y + h], radius=8,
        fill=bg, outline=None,
    )

    fg = _contrast_color(bg)
    font = _get_font(17, bold=True)
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        tw, th = 17 * len(text), 20
    tx = x + (w - tw) // 2
    ty = y + (h - th) // 2 - 2
    draw.text((tx, ty), text, fill=fg, font=font)

    # 脚本标记小圆点
    if has_script:
        draw.ellipse([x + w - 14, y + 6, x + w - 6, y + 14], fill=fg, outline=None)


def _draw_indicator(draw: ImageDraw.Draw, o: Dict[str, Any], ss: Tuple[int, int]):
    """指示灯（圆 + 颜色 + 可能的闪烁虚线环）"""
    x, y = o.get("x", 0), o.get("y", 0)
    r = o.get("radius", 22)
    color_on = o.get("color_on", "#27D17F")
    blink = o.get("blink", False)

    cx, cy = x + r, y + r

    # 主圆
    draw.ellipse([x, y, x + 2 * r, y + 2 * r], fill=color_on, outline="#0A0E14", width=2)

    # 高光（左上白色反光）
    hr = r / 3.5
    draw.ellipse(
        [cx - r / 3 - hr / 2, cy - r / 3 - hr / 2,
         cx - r / 3 + hr / 2, cy - r / 3 + hr / 2],
        fill=(255, 255, 255, 90),
    )

    # blink 虚线环（静态 PNG 中表现为半透明环）
    if blink:
        draw.ellipse(
            [x - 4, y - 4, x + 2 * r + 4, y + 2 * r + 4],
            fill=None, outline=color_on, width=2,
        )

    _draw_indicator_label(draw, o)


# 对象类型 → 绘制函数
_DRAW_DISPATCH = {
    "Text": _draw_text,
    "IOField": _draw_io_field,
    "SymbolicIOField": _draw_symbolic_io_field,
    "Button": _draw_button,
    "Indicator": _draw_indicator,
}


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def render_ir_to_png(ir: Dict[str, Any]) -> bytes:
    """
    将校验后的 IR 渲染为 PNG 图像。

    参数:
        ir: 校验并归一化后的 IR (包含 _screen_size)。

    返回:
        PNG 图像的 bytes。

    异常:
        ValueError: IR 缺少 _screen_size 或 objects。
        Exception: Pillow 绘制过程中的各类错误。
    """
    ss = ir.get("_screen_size")
    if not ss:
        raise ValueError("IR 缺少 _screen_size，请先通过 validate_ir() 校验。")

    screen_w, screen_h = ss["width"], ss["height"]

    # 背景色
    bg_hex = ir.get("meta", {}).get("background_color", "#1F2630")
    bg_rgb = _hex_to_rgb(bg_hex)

    img = Image.new("RGB", (screen_w, screen_h), bg_rgb)
    draw = ImageDraw.Draw(img)

    objects = ir.get("objects") or []
    if not objects:
        raise ValueError("IR 中 objects 为空，无法渲染预览。")

    for o in objects:
        otype = o.get("type", "")
        draw_func = _DRAW_DISPATCH.get(otype)
        if draw_func:
            draw_func(draw, o, (screen_w, screen_h))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

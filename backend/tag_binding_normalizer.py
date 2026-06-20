# -*- coding: utf-8 -*-
"""
统一变量绑定规范化模块 — 统一 legacy IR 中的变量字段。

处理字段:
  - process_tag
  - tag_binding
  - binding.tag
  - tags[]

控件类型:
  - Button
  - Indicator
  - IOField
  - SymbolicIOField

职责:
  1. normalize_legacy_tag_bindings(ir) — 规范化所有控件变量字段
  2. infer_tag_name_from_object(obj) — 根据对象类型和名称自动生成变量名
  3. infer_legacy_tag_spec(obj, tag_name) — 生成 tag spec
  4. assert_legacy_tags_complete(ir) — 断言所有变量绑定完整
"""

from __future__ import annotations

import copy
import re
from typing import Any

# ---------------------------------------------------------------------------
# 需要变量绑定的控件类型
# ---------------------------------------------------------------------------

CONTROL_TYPES_REQUIRING_TAG = {
    "Button",
    "Indicator",
    "IOField",
    "SymbolicIOField",
}

# ---------------------------------------------------------------------------
# 变量命名前缀规则
# ---------------------------------------------------------------------------

BTN_PREFIX_MOMENTARY = "BTN_"
BTN_PREFIX_TOGGLE = "MEM_"
INDICATOR_PREFIX_STATUS = "STS_"
INDICATOR_PREFIX_ALARM = "LMP_"
IOFIELD_PREFIX = "IO_"
SYMBOLIC_IOFIELD_PREFIX = "SIO_"

# ---------------------------------------------------------------------------
# TIA 变量名非法字符
# ---------------------------------------------------------------------------

_ILLEGAL_NAME_CHARS: set[str] = {
    "/", "\\", "@", "#", "$", "%", "^", "&", "*", "(", ")",
    "-", "+", "=", "[", "]", "{", "}", "|", ";", ":", "\"",
    "'", "<", ">", ",", "?", " ", "\t", "~", "`",
    "！", "＃", "￥", "％", "…", "（", "）", "—", "＋",
    "【", "】", "｛", "｝", "｜", "；", "：", "＂",
    "＇", "＜", "＞", "，", "？", "　",
}

# 中文到英文的简单映射（常见 HMI 控件文本）
_CHINESE_TO_ENGLISH: dict[str, str] = {
    "启动": "Start",
    "停止": "Stop",
    "复位": "Reset",
    "急停": "EStop",
    "运行": "Run",
    "故障": "Fault",
    "报警": "Alarm",
    "手动": "Manual",
    "自动": "Auto",
    "开门": "DoorOpen",
    "关门": "DoorClose",
    "上升": "Up",
    "下降": "Down",
    "前进": "Forward",
    "后退": "Backward",
    "左移": "Left",
    "右移": "Right",
    "正转": "Fwd",
    "反转": "Rev",
    "速度": "Speed",
    "温度": "Temp",
    "压力": "Pressure",
    "液位": "Level",
    "流量": "Flow",
    "电流": "Current",
    "电压": "Voltage",
    "功率": "Power",
    "频率": "Freq",
    "开": "On",
    "关": "Off",
    "主": "Main",
    "备": "Standby",
    "确认": "Ack",
    "取消": "Cancel",
    "设置": "Set",
    "选择": "Select",
    "切换": "Toggle",
    "模式": "Mode",
    "状态": "Status",
}

# 按键关键词 → 行为推断
TOGGLE_KEYWORDS = {
    "切换", "自保持", "自锁", "toggle", "latch", "保持",
    "手动/自动", "手自动", "本地/远程", "就地/远方",
    "启动/停止", "正转/反转", "开/关",
}

ALARM_KEYWORDS = {
    "故障", "报警", "alarm", "fault", "error", "警告",
    "急停", "过载", "超温", "过流", "过压", "欠压",
    "断线", "跳闸", "异常", "联锁",
}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _normalize_var_name(name: str) -> str:
    """将变量名中的非法字符统一替换为下划线。

    TIA Portal 变量名要求：只能包含字母、数字、下划线，不能以数字开头。
    """
    if not name:
        return ""
    result = name
    for ch in _ILLEGAL_NAME_CHARS:
        result = result.replace(ch, "_")
    # 合并连续下划线
    while "__" in result:
        result = result.replace("__", "_")
    # 去除首尾下划线
    result = result.strip("_")
    # 不能以数字开头
    if result and result[0].isdigit():
        result = "VAR_" + result
    if not result:
        result = "VAR_Unnamed"
    return result


def _text_to_safe_var(text: str) -> str:
    """将控件文本转为安全变量名片段。

    优先使用中文→英文映射，否则非法字符替换。
    """
    if not text:
        return ""
    text = text.strip()
    # 尝试中文→英文映射
    if text in _CHINESE_TO_ENGLISH:
        return _CHINESE_TO_ENGLISH[text]
    # 对多字符文本逐个尝试映射
    result_parts = []
    for ch in text:
        if ch in _CHINESE_TO_ENGLISH:
            result_parts.append(_CHINESE_TO_ENGLISH[ch])
        elif ch.isascii() and (ch.isalnum() or ch == "_"):
            result_parts.append(ch)
    if result_parts:
        return "".join(result_parts)
    # Fallback: 规范化整个文本
    return _normalize_var_name(text)


def _detect_toggle_from_obj(obj: dict) -> bool:
    """从旧 dict 对象检测是否 toggle 按钮。"""
    if obj.get("self_holding") or obj.get("tag_mode") == "toggle":
        return True
    if obj.get("tag_mode") == "momentary":
        return False
    text = (obj.get("text") or "").lower()
    label = (obj.get("label") or "").lower()
    oid = (obj.get("id") or "").lower()
    combined = f"{text} {label} {oid}"
    for kw in TOGGLE_KEYWORDS:
        if kw.lower() in combined:
            return True
    if oid.startswith("mem_"):
        return True
    return False


def _detect_alarm_from_obj(obj: dict) -> bool:
    """从旧 dict 对象检测是否报警指示灯。"""
    if obj.get("blink"):
        return True
    color_on = (obj.get("color_on") or "").lower()
    if color_on:
        try:
            r = int(color_on.lstrip("#")[0:2], 16)
            if r > 200:
                return True
        except Exception:
            pass
    text = (obj.get("label") or obj.get("text") or "").lower()
    oid = (obj.get("id") or "").lower()
    combined = f"{text} {oid}"
    for kw in ALARM_KEYWORDS:
        if kw.lower() in combined:
            return True
    if oid.startswith("lmp_"):
        return True
    return False


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------


def infer_tag_name_from_object(obj: dict) -> str:
    """根据对象类型和名称自动生成变量名。

    命名规则：
      - Button 瞬时按钮：BTN_*
      - Button 自保持 / toggle：MEM_*
      - Indicator 普通状态：STS_*
      - Indicator 故障 / 报警：LMP_*
      - IOField：IO_*
      - SymbolicIOField：SIO_*

    中文/特殊字符转换为安全变量名。
    不生成空变量名、不带空格/中文标点/非法 XML 字符。
    """
    obj_type = obj.get("type", "")
    obj_id = obj.get("id", "")
    obj_text = obj.get("text") or obj.get("label") or ""

    # 先从 id 中提取基础名
    base_name = _normalize_var_name(obj_id)
    from backend.utils.tag_prefix_utils import strip_known_tag_prefixes
    base_name = strip_known_tag_prefixes(base_name)

    # 如果 base_name 为空或纯数字，尝试从文本生成
    if not base_name or base_name.isdigit():
        if obj_text:
            text_safe = _text_to_safe_var(obj_text)
            if text_safe:
                base_name = text_safe

    if not base_name:
        base_name = "Unnamed"

    # 根据类型选择前缀
    if obj_type == "Button":
        if _detect_toggle_from_obj(obj):
            prefix = BTN_PREFIX_TOGGLE
        else:
            prefix = BTN_PREFIX_MOMENTARY
    elif obj_type == "Indicator":
        if _detect_alarm_from_obj(obj):
            prefix = INDICATOR_PREFIX_ALARM
        else:
            prefix = INDICATOR_PREFIX_STATUS
    elif obj_type == "IOField":
        prefix = IOFIELD_PREFIX
    elif obj_type == "SymbolicIOField":
        prefix = SYMBOLIC_IOFIELD_PREFIX
    else:
        prefix = "VAR_"

    tag_name = _normalize_var_name(f"{prefix}{base_name}")
    return tag_name


def infer_legacy_tag_spec(obj: dict, tag_name: str) -> dict:
    """根据对象类型推断默认 tag spec。

    默认数据类型：
      - Button：Bool
      - Indicator：Bool
      - IOField：Real，除非 obj.data_type / format 指定 Int / DInt / Real
      - SymbolicIOField：Int
      - 其他：Bool

    返回结构至少包含：
      {"name": tag_name, "data_type": "...", "address": "", "comment": "..."}
    """
    obj_type = obj.get("type", "")

    # 数据类型推断
    if obj_type == "SymbolicIOField":
        data_type = "Int"
    elif obj_type == "IOField":
        data_type = _infer_iofield_datatype(obj)
    else:
        data_type = "Bool"

    # 注释
    obj_text = obj.get("text") or obj.get("label") or obj.get("id", "")
    comment = f"Auto generated for {obj_type} '{obj_text}' (id={obj.get('id', '?')})"

    return {
        "name": tag_name,
        "data_type": data_type,
        "address": "",
        "comment": comment,
    }


def _infer_iofield_datatype(obj: dict) -> str:
    """从旧 dict 推断 IOField 数据类型。"""
    # 显式数据类型
    explicit = obj.get("data_type", "")
    if explicit in ("Bool", "Int", "DInt", "Real", "Word", "String"):
        return explicit

    fmt = (obj.get("display_format") or "").strip()
    if fmt == "String":
        return "String"
    elif fmt in ("Hex", "Binary"):
        return "Word"
    elif fmt == "Decimal":
        decimals = obj.get("decimal_digits", 0)
        return "Real" if decimals > 0 else "Int"
    return "Real"


def normalize_legacy_tag_bindings(ir: dict) -> dict:
    """统一 legacy IR 中的变量字段。

    处理:
      - 遍历 ir["objects"]。
      - 对 Button / Indicator / IOField / SymbolicIOField 自动推断变量名。
      - 如果对象已有 process_tag，则以 process_tag 为准。
      - 如果没有 process_tag 但有 tag_binding，则使用 tag_binding。
      - 如果没有上述两个，但 binding.tag 存在，则使用 binding.tag。
      - 如果三个都不存在，则根据对象类型和名称自动生成变量名。
      - 最终必须写回：obj["process_tag"], obj["tag_binding"], obj["binding"]["tag"]
      - 同时保证 ir["tags"] 中存在该变量。

    如果同名变量数据类型冲突，则抛出错误或返回 blocking diagnostic。
    """
    ir = copy.deepcopy(ir)
    objects = ir.setdefault("objects", [])
    tags: list[dict] = ir.setdefault("tags", [])

    # 建立已有 tag 索引
    tag_map: dict[str, dict] = {}
    for tag in tags:
        if isinstance(tag, dict) and tag.get("name"):
            name = str(tag["name"]).strip()
            if name:
                tag_map[name] = tag

    # 检测旧字段冲突（单个对象内多个字段指向不同变量名）
    conflict_errors: list[dict] = []
    for obj in objects:
        if obj.get("type") not in CONTROL_TYPES_REQUIRING_TAG:
            continue

        pt = str(obj.get("process_tag", "")).strip() if obj.get("process_tag") else ""
        tb = str(obj.get("tag_binding", "")).strip() if obj.get("tag_binding") else ""
        bt = ""
        binding = obj.get("binding")
        if isinstance(binding, dict):
            bt = str(binding.get("tag", "")).strip()

        # 收集非空的不同值
        values = set()
        if pt:
            values.add(pt)
        if tb:
            values.add(tb)
        if bt:
            values.add(bt)

        if len(values) > 1:
            conflict_errors.append({
                "object_id": obj.get("id", "?"),
                "object_type": obj.get("type", "?"),
                "conflicting_fields": {
                    "process_tag": pt,
                    "tag_binding": tb,
                    "binding.tag": bt,
                },
                "message": (
                    f"控件 '{obj.get('id', '?')}' 的 process_tag='{pt}', "
                    f"tag_binding='{tb}', binding.tag='{bt}' 不一致"
                ),
            })

    if conflict_errors:
        raise ValueError(
            f"Tag binding conflicts detected in {len(conflict_errors)} object(s): "
            + "; ".join(e["message"] for e in conflict_errors)
        )

    # 规范化每个控件
    for obj in objects:
        if obj.get("type") not in CONTROL_TYPES_REQUIRING_TAG:
            continue

        tag_name = (
            str(obj.get("process_tag", "")).strip()
            or str(obj.get("tag_binding", "")).strip()
            or (
                str(obj.get("binding", {}).get("tag", "")).strip()
                if isinstance(obj.get("binding"), dict)
                else ""
            )
        )

        if not tag_name:
            tag_name = infer_tag_name_from_object(obj)

        # 确保 tag_name 安全
        tag_name = _normalize_var_name(tag_name)
        if not tag_name:
            tag_name = f"VAR_{obj.get('id', 'Unnamed')}"
            tag_name = _normalize_var_name(tag_name)

        # 写回三个字段
        obj["process_tag"] = tag_name
        obj["tag_binding"] = tag_name
        if not isinstance(obj.get("binding"), dict):
            obj["binding"] = {}
        obj["binding"]["tag"] = tag_name

        # 确保变量存在于 tags 列表
        if tag_name not in tag_map:
            tag_spec = infer_legacy_tag_spec(obj, tag_name)
            # 检查同名不同类型冲突
            existing = tag_map.get(tag_name)
            if existing:
                existing_dt = existing.get("data_type", "?")
                new_dt = tag_spec.get("data_type", "?")
                if existing_dt != new_dt:
                    raise ValueError(
                        f"Variable type conflict for '{tag_name}': "
                        f"existing type '{existing_dt}' vs inferred type '{new_dt}' "
                        f"(object: {obj.get('id', '?')} type={obj.get('type', '?')})"
                    )
            else:
                tags.append(tag_spec)
                tag_map[tag_name] = tag_spec

    assert_legacy_tags_complete(ir)
    return ir


def assert_legacy_tags_complete(ir: dict) -> None:
    """断言 legacy IR 中所有变量绑定完整。

    要求：
      - 每个需要变量的控件必须有 process_tag/tag_binding/binding.tag。
      - 三者必须一致。
      - 绑定变量必须存在于 ir["tags"]。
      - 否则 raise ValueError，错误信息里列出 object id/name/type/tag/reason。
    """
    objects = ir.get("objects") or []
    tags = ir.get("tags") or []

    tag_names: set[str] = set()
    for t in tags:
        if isinstance(t, dict) and t.get("name"):
            name = str(t["name"]).strip()
            if name:
                tag_names.add(name)

    errors: list[str] = []

    for obj in objects:
        if obj.get("type") not in CONTROL_TYPES_REQUIRING_TAG:
            continue

        oid = obj.get("id", "?")
        otype = obj.get("type", "?")
        oname = obj.get("text") or obj.get("label") or oid

        pt = str(obj.get("process_tag", "")).strip()
        tb = str(obj.get("tag_binding", "")).strip()
        bt = ""
        binding = obj.get("binding")
        if isinstance(binding, dict):
            bt = str(binding.get("tag", "")).strip()

        # 检查是否有绑定
        if not pt and not tb and not bt:
            errors.append(
                f"[{otype}] id='{oid}' name='{oname}': "
                f"no process_tag, tag_binding, or binding.tag set"
            )
            continue

        # 检查一致性
        values = {v for v in (pt, tb, bt) if v}
        if len(values) > 1:
            errors.append(
                f"[{otype}] id='{oid}' name='{oname}': "
                f"inconsistent bindings: process_tag='{pt}', "
                f"tag_binding='{tb}', binding.tag='{bt}'"
            )
            continue

        tag_name = next(iter(values)) if values else ""

        # 检查变量是否在 tags 中
        if tag_name and tag_name not in tag_names:
            errors.append(
                f"[{otype}] id='{oid}' name='{oname}': "
                f"binding tag '{tag_name}' not found in ir['tags']"
            )

    if errors:
        raise ValueError(
            f"Legacy IR tag binding completeness check failed "
            f"({len(errors)} error(s)):\n  " + "\n  ".join(errors)
        )


def validate_legacy_ir_tag_bindings(ir: dict) -> list[dict]:
    """校验 legacy IR 而不抛出异常。

    返回诊断列表。
    """
    diagnostics: list[dict] = []
    try:
        assert_legacy_tags_complete(ir)
    except ValueError as e:
        diagnostics.append({
            "severity": "error",
            "code": "LEGACY_IR_TAG_INCOMPLETE",
            "message": str(e),
        })
    return diagnostics


def summarize_legacy_ir_tags(ir: dict) -> dict:
    """生成 legacy IR 的 tag 摘要。"""
    objects = ir.get("objects") or []
    tags = ir.get("tags") or []

    tag_names = [
        t.get("name", "") for t in tags
        if isinstance(t, dict) and t.get("name")
    ]

    missing_tags: list[str] = []
    object_refs: list[dict] = []
    for obj in objects:
        if obj.get("type") not in CONTROL_TYPES_REQUIRING_TAG:
            continue
        pt = str(obj.get("process_tag", "")).strip()
        tb = str(obj.get("tag_binding", "")).strip()
        bt = ""
        binding = obj.get("binding")
        if isinstance(binding, dict):
            bt = str(binding.get("tag", "")).strip()

        tag = pt or tb or bt
        if tag and tag not in tag_names:
            missing_tags.append(tag)

        object_refs.append({
            "id": obj.get("id", ""),
            "name": obj.get("text") or obj.get("label") or obj.get("id", ""),
            "type": obj.get("type", ""),
            "process_tag": pt,
            "tag_binding": tb,
            "binding_tag": bt,
        })

    return {
        "tag_count": len(tags),
        "tag_names": tag_names,
        "object_count": len(objects),
        "tag_bound_object_count": len(object_refs),
        "object_refs": object_refs,
        "missing_tags": sorted(set(missing_tags)),
    }

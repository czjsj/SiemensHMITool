# -*- coding: utf-8 -*-
"""
HMI 变量引擎 — 自动变量生成、绑定规则、Tag Table 管理
========================================================
将 IR 中的画面对象自动映射为工程级 HMI 变量系统，实现：
  1. 自动变量命名（BTN_/MEM_/STS_/LMP_/IO_ 前缀规则）
  2. Button 行为模式检测（momentary 瞬时 / toggle 自保持）
  3. Indicator 动态颜色与闪烁变量绑定
  4. IOField 数据类型自动推断
  5. 完整 HMI Tags 列表生成（可直接写入 TIA Tag Table）

管线位置（在 pipeline_orchestrator 中）:
  validate_ir(ir) → VariableEngine.generate(ir) → generate_simaticml(ir)
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# 变量命名规则 — 前缀映射
# ---------------------------------------------------------------------------

# 按钮前缀：瞬时按钮用 BTN_，自保持按钮用 MEM_
BTN_PREFIX_MOMENTARY = "BTN_"
BTN_PREFIX_TOGGLE = "MEM_"

# 指示灯前缀：运行/状态类用 STS_，报警/故障类用 LMP_
INDICATOR_PREFIX_STATUS = "STS_"
INDICATOR_PREFIX_ALARM = "LMP_"

# IOField 前缀
IOFIELD_PREFIX = "IO_"

# SymbolicIOField 前缀
SYMBOLIC_IOFIELD_PREFIX = "SIO_"

# 数据类型默认值映射
DEFAULT_DATA_TYPES = {
    "Bool": "Bool",
    "Int": "Int",
    "DInt": "DInt",
    "Real": "Real",
    "Word": "Word",
    "String": "String",
}


# ---------------------------------------------------------------------------
# VBS 脚本模板
# ---------------------------------------------------------------------------

VBS_TOGGLE_TEMPLATE = (
    "' {purpose}\n"
    "SmartTags(\"{tag_name}\") = Not SmartTags(\"{tag_name}\")\n"
)

VBS_MOMENTARY_PRESS_TEMPLATE = (
    "' {purpose} — 按下置位\n"
    "SmartTags(\"{tag_name}\") = 1\n"
)

VBS_MOMENTARY_RELEASE_TEMPLATE = (
    "' {purpose} — 释放复位\n"
    "SmartTags(\"{tag_name}\") = 0\n"
)


# ---------------------------------------------------------------------------
# 关键词检测 — 用于推断按钮是否为自保持 / 指示灯是否为报警类
# ---------------------------------------------------------------------------

# 自保持/切换类按钮特征词
TOGGLE_KEYWORDS = {
    "切换", "自保持", "自锁", "toggle", "latch", "保持",
    "手动/自动", "手自动", "本地/远程", "就地/远方",
    "启动/停止", "正转/反转", "开/关",
}

# 报警/故障类指示灯特征词
ALARM_KEYWORDS = {
    "故障", "报警", "alarm", "fault", "error", "警告",
    "急停", "过载", "超温", "过流", "过压", "欠压",
    "断线", "跳闸", "异常", "联锁",
}


# ===================================================================
# VariableEngine 主类
# ===================================================================

class VariableEngine:
    """HMI 变量引擎 — 自动为 IR 对象生成工程级变量绑定。

    职责：
      1. 根据对象类型和语义自动分配 process_tag
      2. 检测 Button 的 tag_mode（momentary / toggle）
      3. 为 Indicator 分配颜色与闪烁的动态变量
      4. 生成完整的 tags 数组（HMI Tag Table 格式）
      5. 生成对应的 VBS 脚本（toggle/momentary 按钮）

    使用方式：
        engine = VariableEngine()
        ir = engine.generate(ir)  # 原地修改 + 返回引用
    """

    def __init__(self, plc_prefix: str = ""):
        """
        参数:
            plc_prefix: 可选的 PLC 变量前缀（如 "DB1." 或 "HMI_"），
                       用于生成 address 字段。
        """
        self.plc_prefix = plc_prefix

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------

    def generate(self, ir: Dict[str, Any]) -> Dict[str, Any]:
        """主入口：为 IR 中的所有对象自动生成变量绑定。

        处理流程：
          1. 遍历 objects，为每个对象推断 process_tag 和 tag_mode
          2. 收集所有生成的变量到 tags 数组中
          3. 为 toggle 按钮生成 VBS 脚本
          4. 合并到 ir["tags"] 和 ir["scripts"]

        返回修改后的 IR（原地修改 + 返回引用）。
        """
        objects = ir.get("objects") or []
        if not objects:
            return ir

        # 收集已有的 tag names 和 script names，避免冲突
        existing_tags: Dict[str, dict] = {}
        for t in ir.get("tags") or []:
            name = (t.get("name") or "").strip()
            if name:
                existing_tags[name] = dict(t)

        existing_scripts: Dict[str, dict] = {}
        for s in ir.get("scripts") or []:
            name = (s.get("name") or "").strip()
            if name:
                existing_scripts[name] = dict(s)

        new_tags: List[dict] = []
        new_scripts: List[dict] = []

        for obj in objects:
            otype = obj.get("type", "")
            oid = obj.get("id", "")

            if otype == "Button":
                self._process_button(obj, oid, existing_tags, new_tags,
                                     existing_scripts, new_scripts)

            elif otype == "Indicator":
                self._process_indicator(obj, oid, existing_tags, new_tags)

            elif otype == "IOField":
                self._process_iofield(obj, oid, existing_tags, new_tags)

            elif otype == "SymbolicIOField":
                self._process_symbolic_iofield(obj, oid, existing_tags, new_tags)

            elif otype == "Text":
                # 静态文本不需要变量绑定
                pass

        # 合并到 IR
        if new_tags:
            all_tags = list(ir.get("tags") or [])
            # 去重：按 name 覆盖（后面的覆盖前面的）
            merged_tags: Dict[str, dict] = {}
            for t in all_tags:
                name = (t.get("name") or "").strip()
                if name:
                    merged_tags[name] = dict(t)
            for t in new_tags:
                name = (t.get("name") or "").strip()
                if name:
                    merged_tags[name] = dict(t)
            ir["tags"] = list(merged_tags.values())

        if new_scripts:
            all_scripts = list(ir.get("scripts") or [])
            merged_scripts: Dict[str, dict] = {}
            for s in all_scripts:
                name = (s.get("name") or "").strip()
                if name:
                    merged_scripts[name] = dict(s)
            for s in new_scripts:
                name = (s.get("name") or "").strip()
                if name:
                    merged_scripts[name] = dict(s)
            ir["scripts"] = list(merged_scripts.values())

        # 记录变量引擎处理标记
        ir.setdefault("_warnings", [])
        tag_count = len(new_tags)
        script_count = len(new_scripts)
        if tag_count or script_count:
            ir["_warnings"].append(
                f"[VariableEngine] 自动生成 {tag_count} 个变量绑定、"
                f"{script_count} 个 VBS 脚本。"
            )
        ir["_variable_engine_applied"] = True

        return ir

    # ------------------------------------------------------------------
    # 对象类型处理器
    # ------------------------------------------------------------------

    def _process_button(
        self,
        obj: dict,
        oid: str,
        existing_tags: dict,
        new_tags: list,
        existing_scripts: dict,
        new_scripts: list,
    ):
        """处理 Button 对象。

        规则：
          - 瞬时按钮（momentary）: process_tag = BTN_{name}
            Press → SetBit(1), Release → ResetBit(0)
          - 自保持按钮（toggle）: process_tag = MEM_{name}
            Press → NOT variable (翻转)
        """
        # 推断是否为自保持/切换按钮
        is_toggle = self._detect_toggle(obj, oid)

        # 分配变量名
        if is_toggle:
            tag_name = self._make_tag_name(oid, BTN_PREFIX_TOGGLE, existing_tags)
            obj["tag_mode"] = "toggle"
        else:
            tag_name = self._make_tag_name(oid, BTN_PREFIX_MOMENTARY, existing_tags)
            obj["tag_mode"] = "momentary"

        # 如果对象已有 process_tag 且前缀不符合推荐规则，保留用户指定
        existing_pt = obj.get("process_tag", "").strip()
        if existing_pt and existing_pt not in (oid, ""):
            tag_name = existing_pt
        else:
            obj["process_tag"] = tag_name

        # 生成变量条目
        if tag_name not in existing_tags:
            new_tags.append({
                "name": tag_name,
                "data_type": "Bool",
                "address": self._make_address(tag_name),
                "comment": f"{obj.get('text', oid)} — "
                           f"{'自保持切换' if is_toggle else '瞬时按钮'}",
            })

        # 生成 VBS 脚本
        if is_toggle:
            self._add_toggle_scripts(
                obj, oid, tag_name, existing_scripts, new_scripts
            )
        else:
            self._add_momentary_scripts(
                obj, oid, tag_name, existing_scripts, new_scripts
            )

    def _process_indicator(
        self,
        obj: dict,
        oid: str,
        existing_tags: dict,
        new_tags: list,
    ):
        """处理 Indicator 对象。

        规则：
          - 运行/状态类: process_tag = STS_{name}
          - 报警/故障类: process_tag = LMP_{name}
          - color_on → 关联变量 = 1 时显示的颜色
          - color_off → 关联变量 = 0 时显示的颜色
          - blink → 关联变量 = 1 时闪烁（通常为报警变量）
        """
        is_alarm = self._detect_alarm(obj, oid)

        if is_alarm:
            tag_name = self._make_tag_name(oid, INDICATOR_PREFIX_ALARM, existing_tags)
            # 报警指示灯默认红色 + 闪烁
            obj.setdefault("color_on", "#E25563")
            obj.setdefault("color_off", "#3A4250")
            obj.setdefault("blink", True)
            comment = f"报警指示 — {obj.get('label', oid)}"
        else:
            tag_name = self._make_tag_name(oid, INDICATOR_PREFIX_STATUS, existing_tags)
            # 运行/状态指示灯默认绿色 + 不闪烁
            obj.setdefault("color_on", "#27D17F")
            obj.setdefault("color_off", "#3A4250")
            obj.setdefault("blink", False)
            comment = f"状态指示 — {obj.get('label', oid)}"

        # 尊重用户显式指定的 process_tag
        existing_pt = obj.get("process_tag", "").strip()
        if existing_pt and existing_pt not in (oid, ""):
            tag_name = existing_pt
        else:
            obj["process_tag"] = tag_name

        if tag_name not in existing_tags:
            new_tags.append({
                "name": tag_name,
                "data_type": "Bool",
                "address": self._make_address(tag_name),
                "comment": comment,
            })

        # 报警指示灯附加闪烁变量（blink_tag）
        if is_alarm and obj.get("blink"):
            blink_tag = tag_name  # 闪烁复用同一变量
            obj["blink_tag"] = blink_tag

    def _process_iofield(
        self,
        obj: dict,
        oid: str,
        existing_tags: dict,
        new_tags: list,
    ):
        """处理 IOField 对象。

        规则：
          - process_tag = IO_{name}
          - data_type 根据 display_format 推断：
            Decimal → Real (默认) 或 Int
            String → String
            Hex/Binary → Word
          - 如果对象已标注 data_type，则尊重标注
        """
        tag_name = self._make_tag_name(oid, IOFIELD_PREFIX, existing_tags)

        existing_pt = obj.get("process_tag", "").strip()
        if existing_pt and existing_pt not in (oid, ""):
            tag_name = existing_pt
        else:
            obj["process_tag"] = tag_name

        # 数据类型推断
        data_type = self._infer_iofield_datatype(obj)

        if tag_name not in existing_tags:
            unit = obj.get("unit", "")
            comment_parts = [f"数值显示 — {obj.get('label', oid)}"]
            if unit:
                comment_parts.append(f"单位: {unit}")
            new_tags.append({
                "name": tag_name,
                "data_type": data_type,
                "address": self._make_address(tag_name),
                "comment": "；".join(comment_parts),
            })

    def _process_symbolic_iofield(
        self,
        obj: dict,
        oid: str,
        existing_tags: dict,
        new_tags: list,
    ):
        """处理 SymbolicIOField 对象。

        规则：
          - process_tag = SIO_{name}
          - data_type = Int（枚举值）
        """
        tag_name = self._make_tag_name(oid, SYMBOLIC_IOFIELD_PREFIX, existing_tags)

        existing_pt = obj.get("process_tag", "").strip()
        if existing_pt and existing_pt not in (oid, ""):
            tag_name = existing_pt
        else:
            obj["process_tag"] = tag_name

        if tag_name not in existing_tags:
            new_tags.append({
                "name": tag_name,
                "data_type": "Int",
                "address": self._make_address(tag_name),
                "comment": f"枚举选择 — {obj.get('label', oid)} "
                           f"(关联文本列表: {obj.get('text_list', '')})",
            })

    # ------------------------------------------------------------------
    # 检测方法
    # ------------------------------------------------------------------

    def _detect_toggle(self, obj: dict, oid: str) -> bool:
        """检测按钮是否为自保持/切换类型。

        判断依据（按优先级）：
          1. 显式 self_holding / tag_mode 字段
          2. 按钮文本包含切换类关键词（启动/停止、手动/自动等）
          3. 按钮 ID 以 MEM_ 开头
          4. 默认：非切换（momentary）
        """
        # 显式标记
        if obj.get("self_holding") or obj.get("tag_mode") == "toggle":
            return True
        if obj.get("tag_mode") == "momentary":
            return False

        # 文本关键词检测
        text = (obj.get("text") or "").lower()
        label = (obj.get("label") or "").lower()
        combined = f"{text} {label} {oid.lower()}"

        for kw in TOGGLE_KEYWORDS:
            if kw.lower() in combined:
                return True

        # ID 前缀
        if oid.startswith("MEM_"):
            return True

        return False

    def _detect_alarm(self, obj: dict, oid: str) -> bool:
        """检测指示灯是否为报警/故障类。

        判断依据：
          1. 显式 blink = True
          2. color_on 为红色系
          3. 标签/ID 包含报警关键词
          4. ID 以 LMP_ 开头
        """
        # 显式闪烁
        if obj.get("blink"):
            return True

        # 颜色检测
        color_on = (obj.get("color_on") or "").lower()
        red_colors = {"#e25563", "#ff0000", "#ff3333", "#cc0000", "#d32f2f",
                      "red", "255,0,0"}
        if color_on in red_colors or (color_on.startswith("#") and
                any(c in color_on for c in ["e2", "ff", "d3", "cc"])):
            # 粗略判断：以红色调开头
            try:
                r = int(color_on.lstrip("#")[0:2], 16)
                if r > 200:
                    return True
            except Exception:
                pass

        # 关键词检测
        text = (obj.get("label") or "").lower()
        combined = f"{text} {oid.lower()}"
        for kw in ALARM_KEYWORDS:
            if kw.lower() in combined:
                return True

        # ID 前缀
        if oid.startswith("LMP_"):
            return True

        return False

    def _infer_iofield_datatype(self, obj: dict) -> str:
        """根据 IOField 的 display_format 推断数据类型。"""
        fmt = (obj.get("display_format") or "").strip()
        # 如果对象已有 data_type，尊重它
        if obj.get("data_type") in DEFAULT_DATA_TYPES:
            return obj["data_type"]

        if fmt == "String":
            return "String"
        elif fmt in ("Hex", "Binary"):
            return "Word"
        elif fmt == "Decimal":
            # 有小数位 → Real，无小数位 → Int
            decimals = obj.get("decimal_digits", 0)
            return "Real" if decimals > 0 else "Int"
        return "Real"  # 默认

    # ------------------------------------------------------------------
    # 命名与地址生成
    # ------------------------------------------------------------------

    def _make_tag_name(
        self,
        oid: str,
        prefix: str,
        existing_tags: dict,
    ) -> str:
        """生成变量名：去除对象 ID 的原有前缀，加上新前缀。

        例如: oid="BTN_Start", prefix="MEM_" → "MEM_Start"
              oid="Start",     prefix="BTN_" → "BTN_Start"
        """
        # 如果 oid 已有某个已知前缀，去除后再加新前缀
        all_prefixes = {
            "BTN_", "MEM_", "STS_", "LMP_", "IO_", "SIO_", "TXT_",
        }
        base_name = oid
        for p in sorted(all_prefixes, key=len, reverse=True):
            if oid.startswith(p) and len(oid) > len(p):
                base_name = oid[len(p):]
                break

        candidate = f"{prefix}{base_name}"

        # 如果候选名冲突，追加数字后缀
        if candidate in existing_tags and existing_tags[candidate].get("name") != candidate:
            idx = 2
            while f"{candidate}_{idx}" in existing_tags:
                idx += 1
            candidate = f"{candidate}_{idx}"

        return candidate

    def _make_address(self, tag_name: str) -> str:
        """生成 PLC 地址（占位，需要根据实际 PLC 映射确定）。"""
        if self.plc_prefix:
            return f"{self.plc_prefix}{tag_name}"
        return ""  # 留空表示需要手动分配

    # ------------------------------------------------------------------
    # VBS 脚本生成
    # ------------------------------------------------------------------

    def _add_toggle_scripts(
        self,
        obj: dict,
        oid: str,
        tag_name: str,
        existing_scripts: dict,
        new_scripts: list,
    ):
        """为 toggle 按钮生成翻转脚本。"""
        script_name = f"Sub_{oid}_Toggle"
        text = obj.get("text", oid)
        purpose = f"切换按钮「{text}」— 翻转变量 {tag_name}"

        code = VBS_TOGGLE_TEMPLATE.format(
            purpose=purpose,
            tag_name=tag_name,
        )

        if script_name not in existing_scripts:
            new_scripts.append({
                "name": script_name,
                "language": "VBS",
                "purpose": purpose,
                "code": code,
            })

        # 只设置 click_script — toggle 按钮不需要 press/release
        if not obj.get("click_script"):
            obj["click_script"] = script_name
        # 清除可能从模板继承的 press/release
        if obj.get("tag_mode") == "toggle":
            obj.setdefault("press_script", None)
            obj.setdefault("release_script", None)

    def _add_momentary_scripts(
        self,
        obj: dict,
        oid: str,
        tag_name: str,
        existing_scripts: dict,
        new_scripts: list,
    ):
        """为 momentary 按钮生成按下置位/释放复位脚本。"""
        text = obj.get("text", oid)

        # Press 脚本
        press_name = f"Sub_{oid}_Press"
        press_code = VBS_MOMENTARY_PRESS_TEMPLATE.format(
            purpose=f"按钮「{text}」按下",
            tag_name=tag_name,
        )
        if press_name not in existing_scripts:
            new_scripts.append({
                "name": press_name,
                "language": "VBS",
                "purpose": f"按钮「{text}」— 按下置位 {tag_name}",
                "code": press_code,
            })

        # Release 脚本
        release_name = f"Sub_{oid}_Release"
        release_code = VBS_MOMENTARY_RELEASE_TEMPLATE.format(
            purpose=f"按钮「{text}」释放",
            tag_name=tag_name,
        )
        if release_name not in existing_scripts:
            new_scripts.append({
                "name": release_name,
                "language": "VBS",
                "purpose": f"按钮「{text}」— 释放复位 {tag_name}",
                "code": release_code,
            })

        # 设置事件引用（不覆盖用户已有脚本）
        if not obj.get("press_script"):
            obj["press_script"] = press_name
        if not obj.get("release_script"):
            obj["release_script"] = release_name

    # ------------------------------------------------------------------
    # 静态便捷方法
    # ------------------------------------------------------------------

    @staticmethod
    def get_tag_table(ir: Dict[str, Any]) -> List[Dict[str, Any]]:
        """从 IR 中提取完整的 HMI Tag Table（含自动生成和手动声明的变量）。"""
        return list(ir.get("tags") or [])

    @staticmethod
    def get_tag_names(ir: Dict[str, Any]) -> List[str]:
        """获取所有变量名列表。"""
        return [t.get("name", "") for t in ir.get("tags") or [] if t.get("name")]

    @staticmethod
    def get_binding_summary(ir: Dict[str, Any]) -> Dict[str, Any]:
        """获取变量绑定摘要。

        返回:
            {
                "total_tags": N,
                "by_type": {"Bool": N, "Real": N, ...},
                "by_prefix": {"BTN_": [...], "STS_": [...], ...},
                "objects_bound": N,
                "objects_unbound": [...],
            }
        """
        tags = ir.get("tags") or []
        objects = ir.get("objects") or []

        by_type: Dict[str, int] = {}
        by_prefix: Dict[str, list] = {}
        for t in tags:
            dtype = t.get("data_type", "Unknown")
            by_type[dtype] = by_type.get(dtype, 0) + 1

            name = t.get("name", "")
            for prefix in ("BTN_", "MEM_", "STS_", "LMP_", "IO_", "SIO_"):
                if name.startswith(prefix):
                    by_prefix.setdefault(prefix, []).append(name)
                    break
            else:
                by_prefix.setdefault("other", []).append(name)

        bound = 0
        unbound = []
        for obj in objects:
            if obj.get("type") == "Text":
                continue  # 文本不需要变量
            if obj.get("process_tag", "").strip():
                bound += 1
            else:
                unbound.append(obj.get("id", "?"))

        return {
            "total_tags": len(tags),
            "by_type": by_type,
            "by_prefix": {k: sorted(v) for k, v in by_prefix.items()},
            "objects_bound": bound,
            "objects_unbound": unbound,
        }


# ===================================================================
# 模块级便捷函数
# ===================================================================

def auto_bind_variables(ir: Dict[str, Any], plc_prefix: str = "") -> Dict[str, Any]:
    """便捷函数：一行调用完成变量自动绑定。

    用法:
        from backend.variable_engine import auto_bind_variables
        ir = auto_bind_variables(ir, plc_prefix="DB_HMI.")
    """
    engine = VariableEngine(plc_prefix=plc_prefix)
    return engine.generate(ir)

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

V3.0 改造：核心逻辑输出语义模型 (HmiProjectSpec)，
VBS 生成仅保留在 generate() 的 backward-compat 层。

管线位置（在 pipeline_orchestrator 中）:
  validate_ir(ir) → VariableEngine.generate(ir) → generate_simaticml(ir)
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from .domain.ir_v2 import (
    ActionSpec,
    BindingSpec,
    EventSpec,
    GeometrySpec,
    HmiProjectSpec,
    ScreenItemSpec,
    ScreenSpec,
    TagSpec,
)
from .domain.enums import (
    BindingKind,
    HmiFamily,
    SemanticActionType,
    SemanticEvent,
    ScreenItemType,
    TagScope,
)
from .domain.legacy_adapter import LegacyIrAdapter
from .domain.diagnostics import Diagnostic, DiagnosticCodes
from .domain.enums import DiagnosticSeverity
from .tag_binding_normalizer import (
    normalize_legacy_tag_bindings,
    assert_legacy_tags_complete,
)
from .validation.tag_binding_gate import (
    validate_project_tag_bindings,
    raise_if_project_tag_bindings_invalid,
)

# ---------------------------------------------------------------------------
# 变量命名规则 — 前缀映射
# ---------------------------------------------------------------------------

BTN_PREFIX_MOMENTARY = "BTN_"
BTN_PREFIX_TOGGLE = "MEM_"
INDICATOR_PREFIX_STATUS = "STS_"
INDICATOR_PREFIX_ALARM = "LMP_"
IOFIELD_PREFIX = "IO_"
SYMBOLIC_IOFIELD_PREFIX = "SIO_"

DEFAULT_DATA_TYPES = {
    "Bool": "Bool",
    "Int": "Int",
    "DInt": "DInt",
    "Real": "Real",
    "Word": "Word",
    "String": "String",
}


def normalize_data_type(value: str | None, fallback: str = "Int") -> str:
    """将用户输入的类型字符串归一化为 TIA Portal 标准类型名。

    支持缩写、别名、常见拼写变体。
    """
    if not value:
        return fallback

    key = str(value).strip().lower()

    mapping = {
        "bool": "Bool",
        "boolean": "Bool",
        "bit": "Bool",

        "int": "Int",
        "integer": "Int",
        "short": "Int",

        "dint": "DInt",
        "doubleint": "DInt",

        "real": "Real",
        "float": "Real",
        "double": "Real",

        "string": "String",
        "str": "String",
        "char": "Char",

        "word": "Word",
        "dword": "DWord"
    }

    return mapping.get(key, fallback)

# ---------------------------------------------------------------------------
# VBS 脚本模板（仅用于 backward-compat generate()）
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
# 关键词检测
# ---------------------------------------------------------------------------

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


# ===================================================================
# VariableEngine 主类
# ===================================================================

class VariableEngine:
    """HMI 变量引擎 — 自动为 IR 对象生成工程级变量绑定。

    V3.0 职责：
      1. enrich() — 将旧 IR 转换为语义 HmiProjectSpec（推荐新用法）
      2. generate() — 旧兼容入口，内部走 enrich 再回填旧字段
      3. 静态工具方法 get_tag_table / get_tag_names / get_binding_summary

    使用方式（新）：
        engine = VariableEngine()
        project_spec = engine.enrich(legacy_ir, target_hint="comfort")

    使用方式（旧，仍兼容）：
        engine = VariableEngine()
        ir = engine.generate(ir)
    """

    def __init__(self, plc_prefix: str = ""):
        self.plc_prefix = plc_prefix

    # ------------------------------------------------------------------
    # 公共入口 — 新 V3.0 API
    # ------------------------------------------------------------------

    def enrich(
        self,
        legacy_ir: Dict[str, Any],
        target_hint: str | None = None,
        plc_tag_mapping: Dict[str, str] | None = None,
    ) -> HmiProjectSpec:
        """将旧 IR dict 转换为语义 HmiProjectSpec 并补齐推断。

        推断内容：
          - 缺失的 TagSpec（自动命名、数据类型推断）
          - EventSpec/ActionSpec（根据 tag_mode 推断语义动作）
          - BindingSpec（Indicator 颜色/闪烁动态绑定）
          - 命名建议
          - PLC 地址映射（通过 plc_tag_mapping 进行语义匹配）

        参数:
            legacy_ir: 旧版 IR dict（validate_ir 输出）
            target_hint: 可选设备提示 "basic"/"comfort"/"unified"
            plc_tag_mapping: 可选 PLC 地址映射 {"Motor_Start": "DB10.DBX0.0", ...}
                             支持 4 级语义匹配：
                               1. 精确变量名匹配
                               2. 去掉 BTN_/STS_/LMP_ 前缀后匹配
                               3. 按 item id 匹配
                               4. 按中文文本匹配

        返回:
            HmiProjectSpec 实例
        """
        # 变量冲突检测 — 在适配器转换之前，对原始 IR 中的 tags 进行
        self._detect_variable_conflicts_in_raw_ir(legacy_ir)

        adapter = LegacyIrAdapter(target_hint=target_hint)
        project, _diags = adapter.convert(legacy_ir)

        # 将原始 IR 中的变量冲突传递到项目诊断
        raw_conflicts = legacy_ir.get("_variable_conflicts") or []
        for c in raw_conflicts:
            project.diagnostics.append(Diagnostic(
                code=DiagnosticCodes.IR_VALIDATION_ERROR,
                severity=DiagnosticSeverity.ERROR,
                phase="P20_TAGS",
                object_type="tag",
                object_name=c["name"],
                message=f"变量冲突: '{c['name']}' 存在{c['kind']} ({c['detail']})",
                remediation="请统一变量定义，避免同名不同类型或不同地址",
            ))

        # 收集已有 tag/screen/script 名称
        existing_tags: Dict[str, TagSpec] = {}
        for t in project.tags:
            if t.name:
                existing_tags[t.name] = t

        existing_screen_names: set[str] = {
            s.name for s in project.screens if s.name
        }

        new_tags: list[TagSpec] = []

        for screen in project.screens:
            for item in screen.items:
                oid = item.id
                otype = item.type

                if otype == ScreenItemType.BUTTON:
                    self._enrich_button(item, oid, existing_tags, new_tags)

                elif otype == ScreenItemType.INDICATOR:
                    self._enrich_indicator(item, oid, existing_tags, new_tags)

                elif otype == ScreenItemType.IO_FIELD:
                    self._enrich_iofield(item, oid, existing_tags, new_tags)

                elif otype == ScreenItemType.SYMBOLIC_IO_FIELD:
                    self._enrich_symbolic_iofield(item, oid, existing_tags, new_tags)

                # Text 不需要变量绑定

        # 合并新增 tag
        if new_tags:
            merged: Dict[str, TagSpec] = dict(existing_tags)
            for t in new_tags:
                if t.name and t.name not in merged:
                    merged[t.name] = t
            project.tags = list(merged.values())

        # PLC 地址映射（语义匹配四层策略）
        if plc_tag_mapping:
            self._apply_plc_mapping(project, plc_tag_mapping)

        return project

    # ------------------------------------------------------------------
    # 旧兼容入口
    # ------------------------------------------------------------------

    def generate(self, ir: Dict[str, Any]) -> Dict[str, Any]:
        """主入口（旧兼容）：为 IR 中的所有对象自动生成变量绑定。

        内部流程：
          1. normalize_legacy_tag_bindings(ir) — 统一变量字段
          2. 调用 enrich() 获取 HmiProjectSpec
          3. raise_if_project_tag_bindings_invalid(project) — 校验 tag 完整性
          4. 回填 legacy IR 字段（process_tag, scripts 等）
          5. normalize_legacy_tag_bindings(legacy) — 二次规范化
          6. assert_legacy_tags_complete(legacy) — 断言完整性
          7. 生成 VBS 脚本（仅用于旧版 compatibility）

        返回修改后的 IR（深拷贝 + 修改 + 返回引用）。
        """
        objects = ir.get("objects") or []
        if not objects:
            return ir

        # V4.1: Step 0 — 入口规范化
        ir = normalize_legacy_tag_bindings(ir)

        project = self.enrich(ir)

        # V4.1: 校验 project 的 tag 完整性
        raise_if_project_tag_bindings_invalid(project)

        # ---- 回填旧 IR 字段 ----
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

        new_tags_for_legacy: List[dict] = []
        new_scripts_for_legacy: List[dict] = []

        for screen in project.screens:
            for item in screen.items:
                oid = item.id
                otype = item.type

                # 回填 process_tag
                for obj in objects:
                    if obj.get("id") == oid:
                        if item.tag_binding and not obj.get("process_tag"):
                            obj["process_tag"] = item.tag_binding
                        # 同步 binding.tag
                        if item.tag_binding:
                            obj.setdefault("binding", {})
                            obj["binding"]["tag"] = item.tag_binding
                            obj["tag_binding"] = item.tag_binding
                        self._backfill_legacy_scripts(
                            obj, oid, item,
                            existing_scripts, new_scripts_for_legacy,
                        )
                        break

                # 回填 tags 到旧格式
                for tag in project.tags:
                    if tag.name not in existing_tags:
                        new_tags_for_legacy.append({
                            "name": tag.name,
                            "data_type": tag.data_type,
                            "address": tag.address or "",
                            "comment": tag.comment.get("zh-CN", ""),
                        })
                        existing_tags[tag.name] = new_tags_for_legacy[-1]

        # V5.5: 将 enrich 阶段修正后的 data_type 同步回 legacy IR
        # enrich() 在 _enrich_button/_enrich_indicator/_enrich_iofield 中
        # 会把已存在 tag 的错误类型（如 Int）强制修正为 Bool/Real，
        # 但 generate() 的回填循环只添加新 tag，不更新已有 tag 的 data_type。
        # 此处将 project.tags 中的正确 data_type 写回 ir["tags"]。
        _project_tag_types: Dict[str, str] = {}
        for t in project.tags:
            if t.name and t.data_type:
                _project_tag_types[t.name] = t.data_type
        for legacy_tag in ir.get("tags", []):
            name = (legacy_tag.get("name") or "").strip()
            corrected = _project_tag_types.get(name)
            if corrected and legacy_tag.get("data_type") != corrected:
                legacy_tag["data_type"] = corrected

        # 合并 tags
        if new_tags_for_legacy:
            merged_tags: Dict[str, dict] = {}
            for t in ir.get("tags") or []:
                name = (t.get("name") or "").strip()
                if name:
                    merged_tags[name] = dict(t)
            for t in new_tags_for_legacy:
                name = (t.get("name") or "").strip()
                if name:
                    merged_tags[name] = dict(t)
            ir["tags"] = list(merged_tags.values())

        # 合并 scripts（VBS backward compat）
        if new_scripts_for_legacy:
            merged_scripts: Dict[str, dict] = {}
            for s in ir.get("scripts") or []:
                name = (s.get("name") or "").strip()
                if name:
                    merged_scripts[name] = dict(s)
            for s in new_scripts_for_legacy:
                name = (s.get("name") or "").strip()
                if name:
                    merged_scripts[name] = dict(s)
            ir["scripts"] = list(merged_scripts.values())

        ir.setdefault("_warnings", [])
        tag_count = len(new_tags_for_legacy)
        script_count = len(new_scripts_for_legacy)
        if tag_count or script_count:
            ir["_warnings"].append(
                f"[VariableEngine] 自动生成 {tag_count} 个变量绑定、"
                f"{script_count} 个 VBS 脚本。"
            )
        ir["_variable_engine_applied"] = True

        # V4.1: 二次规范化 + 完整性断言
        ir = normalize_legacy_tag_bindings(ir)
        assert_legacy_tags_complete(ir)

        return ir

    # ------------------------------------------------------------------
    # enrich 辅助方法 — 语义模型推断
    # ------------------------------------------------------------------

    def _find_existing_binding(self, item: ScreenItemSpec) -> str | None:
        """查找 item 上已有的变量绑定，避免生成重复自动变量。"""
        # 1. 检查 tag_binding
        if item.tag_binding and item.tag_binding.strip():
            return item.tag_binding.strip()
        # 2. 检查 bindings 中的 source_tag
        for binding in item.bindings:
            if binding.source_tag and binding.source_tag.strip():
                return binding.source_tag.strip()
        # 3. 检查 events 中 actions 引用的 tag
        for event in item.events:
            for action in event.actions:
                if action.tag and action.tag.strip():
                    return action.tag.strip()
        return None

    def infer_tag_data_type_for_item(self, item: ScreenItemSpec) -> str:
        """根据控件类型和显式配置推断数据类型。

        按钮/开关 → Bool
        指示灯 → Bool（除非显式指定数值类型）
        SymbolicIO → Int
        IOField → 根据显式 data_type 或文本语义推断
        """
        from backend.domain.enums import ScreenItemType as SIT

        otype = item.type

        # 按钮、开关、位操作目标必须是 Bool
        if otype in {SIT.BUTTON}:
            return "Bool"

        # 指示灯默认 Bool
        if otype in {SIT.INDICATOR}:
            explicit = item.properties.get("data_type") or item.properties.get("datatype")
            if explicit:
                return normalize_data_type(explicit)
            return "Bool"

        # SymbolicIO 一般使用 Int 作为文本列表索引
        if otype in {SIT.SYMBOLIC_IO_FIELD}:
            return "Int"

        # IOField 根据显式类型或文本语义推断
        if otype in {SIT.IO_FIELD}:
            # 检查 properties 中的显式 data_type
            explicit = item.properties.get("data_type") or item.properties.get("datatype")

            # 也检查 metadata 中的 data_type
            if not explicit:
                explicit = item.metadata.get("data_type") or item.metadata.get("datatype")

            if explicit:
                return normalize_data_type(explicit)

            # 文本语义推断
            text = item.text.get("zh-CN", "") if item.text else ""
            text_lower = text.lower()
            real_keywords = ["温度", "压力", "速度", "流量", "液位", "设定", "频率", "电流", "电压",
                           "temp", "pressure", "speed", "flow", "level", "setpoint", "frequency",
                           "current", "voltage", "power", "energy", "weight", "length", "ratio"]
            if any(k in text_lower for k in real_keywords):
                return "Real"

            return "Int"

        # 默认兜底
        explicit = item.properties.get("data_type") or item.properties.get("datatype")
        if not explicit:
            explicit = item.metadata.get("data_type") or item.metadata.get("datatype")
        return normalize_data_type(explicit) if explicit else "Int"

    def _make_tag_spec(self, name: str, data_type: str, oid: str,
                       existing_tags: dict, new_tags: list):
        """创建 TagSpec（如果名称不重复）。"""
        if name in existing_tags:
            return None
        from backend.domain.ir_v2 import TagSpec
        from backend.domain.enums import TagScope
        ts = TagSpec(
            name=name,
            table="DefaultTagTable",
            scope=TagScope.EXTERNAL if self.plc_prefix else TagScope.INTERNAL,
            data_type=data_type,
            address=self._make_address(name) if self.plc_prefix else None,
            comment={"zh-CN": f"已存在绑定 — {oid}"},
        )
        return ts

    def _enrich_button(
        self,
        item: ScreenItemSpec,
        oid: str,
        existing_tags: dict,
        new_tags: list,
    ):
        """为 Button 推断 TagSpec、EventSpec、ActionSpec。"""

        # V4.2: 先检查已有绑定，避免生成重复自动变量
        existing_tag = self._find_existing_binding(item)
        if existing_tag:
            # 已有绑定 → 复用，不自动生成
            item.tag_binding = existing_tag
            if existing_tag not in existing_tags:
                ts = self._make_tag_spec(existing_tag, "Bool", oid, existing_tags, new_tags)
                if ts:
                    new_tags.append(ts)
                    existing_tags[existing_tag] = ts
            else:
                # V5.5: 已有 tag 但 data_type 可能为 Int 等非 Bool 值，强制修正
                existing = existing_tags.get(existing_tag)
                if existing and getattr(existing, 'data_type', '') != "Bool":
                    try:
                        if isinstance(existing, dict):
                            existing["data_type"] = "Bool"
                        elif hasattr(existing, 'data_type'):
                            existing.data_type = "Bool"
                    except Exception:
                        pass
            return

        is_toggle = self._detect_toggle_from_item(item, oid)

        if is_toggle:
            tag_name = self._make_tag_name(oid, BTN_PREFIX_TOGGLE, existing_tags)
            tag_mode = "toggle"
        else:
            tag_name = self._make_tag_name(oid, BTN_PREFIX_MOMENTARY, existing_tags)
            tag_mode = "momentary"

        # 尊重已有 tag_binding
        existing_pt = (item.tag_binding or "").strip()
        if existing_pt:
            tag_name = existing_pt
        else:
            item.tag_binding = tag_name

        item.properties["tag_mode"] = tag_mode

        # 变量 TagSpec
        if tag_name not in existing_tags:
            ts = TagSpec(
                name=tag_name,
                table="DefaultTagTable",
                scope=TagScope.EXTERNAL if self.plc_prefix else TagScope.INTERNAL,
                data_type="Bool",
                address=self._make_address(tag_name),
                comment={
                    "zh-CN": (
                        f"{item.text.get('zh-CN', oid)} — "
                        f"{'自保持切换' if is_toggle else '瞬时按钮'}"
                    ),
                },
            )
            new_tags.append(ts)
            existing_tags[tag_name] = ts
        else:
            # V5.5: 已有 tag 但 data_type 可能为 Int 等非 Bool 值，强制修正
            existing = existing_tags.get(tag_name)
            if existing and getattr(existing, 'data_type', '') != "Bool":
                try:
                    from backend.domain.ir_v2 import TagSpec as _TS
                    if isinstance(existing, dict):
                        existing["data_type"] = "Bool"
                    elif hasattr(existing, 'data_type'):
                        existing.data_type = "Bool"
                except Exception:
                    pass

        # 语义事件和动作（不生成 VBS）
        if not item.events:  # 只在无已有事件时自动生成
            if is_toggle:
                item.events.append(EventSpec(
                    event=SemanticEvent.CLICK,
                    actions=[ActionSpec(
                        type=SemanticActionType.TOGGLE_BIT,
                        tag=tag_name,
                    )],
                ))
            else:
                item.events.append(EventSpec(
                    event=SemanticEvent.PRESS,
                    actions=[ActionSpec(
                        type=SemanticActionType.SET_BIT,
                        tag=tag_name,
                        value=1,
                    )],
                ))
                item.events.append(EventSpec(
                    event=SemanticEvent.RELEASE,
                    actions=[ActionSpec(
                        type=SemanticActionType.RESET_BIT,
                        tag=tag_name,
                        value=0,
                    )],
                ))

        # 变量绑定
        if not item.bindings:
            item.bindings.append(BindingSpec(
                property="value",
                kind=BindingKind.DIRECT_TAG,
                source_tag=tag_name,
            ))

    def _enrich_indicator(
        self,
        item: ScreenItemSpec,
        oid: str,
        existing_tags: dict,
        new_tags: list,
    ):
        """为 Indicator 推断 TagSpec、BindingSpec。"""

        # V4.2: 先检查已有绑定，避免生成重复自动变量
        existing_tag = self._find_existing_binding(item)
        if existing_tag:
            item.tag_binding = existing_tag
            if existing_tag not in existing_tags:
                ts = self._make_tag_spec(existing_tag, "Bool", oid, existing_tags, new_tags)
                if ts:
                    new_tags.append(ts)
                    existing_tags[existing_tag] = ts
            else:
                # V5.5: 已有 tag 但 data_type 可能为 Int 等非 Bool 值，强制修正
                existing = existing_tags.get(existing_tag)
                if existing and getattr(existing, 'data_type', '') != "Bool":
                    try:
                        if isinstance(existing, dict):
                            existing["data_type"] = "Bool"
                        elif hasattr(existing, 'data_type'):
                            existing.data_type = "Bool"
                    except Exception:
                        pass
            return

        is_alarm = self._detect_alarm_from_item(item, oid)

        if is_alarm:
            tag_name = self._make_tag_name(oid, INDICATOR_PREFIX_ALARM, existing_tags)
            item.properties.setdefault("color_on", "#E25563")
            item.properties.setdefault("color_off", "#3A4250")
            item.properties.setdefault("blink", True)
            comment_text = f"报警指示 — {item.text.get('zh-CN', oid)}"
        else:
            tag_name = self._make_tag_name(oid, INDICATOR_PREFIX_STATUS, existing_tags)
            item.properties.setdefault("color_on", "#27D17F")
            item.properties.setdefault("color_off", "#3A4250")
            item.properties.setdefault("blink", False)
            comment_text = f"状态指示 — {item.text.get('zh-CN', oid)}"

        existing_pt = (item.tag_binding or "").strip()
        if existing_pt:
            tag_name = existing_pt
        else:
            item.tag_binding = tag_name

        # TagSpec
        if tag_name not in existing_tags:
            ts = TagSpec(
                name=tag_name,
                table="DefaultTagTable",
                scope=TagScope.EXTERNAL if self.plc_prefix else TagScope.INTERNAL,
                data_type="Bool",
                address=self._make_address(tag_name),
                comment={"zh-CN": comment_text},
            )
            new_tags.append(ts)
            existing_tags[tag_name] = ts
        else:
            # V5.5: 已有 tag 但 data_type 可能为 Int 等非 Bool 值，强制修正
            existing = existing_tags.get(tag_name)
            if existing and getattr(existing, 'data_type', '') != "Bool":
                try:
                    if isinstance(existing, dict):
                        existing["data_type"] = "Bool"
                    elif hasattr(existing, 'data_type'):
                        existing.data_type = "Bool"
                except Exception:
                    pass

        # 颜色动态绑定（离散）
        blink = bool(item.properties.get("blink", False))
        color_on = item.properties.get("color_on", "#27D17F")
        color_off = item.properties.get("color_off", "#3A4250")

        if not any(b.property == "background_color" for b in item.bindings):
            item.bindings.append(BindingSpec(
                property="background_color",
                kind=BindingKind.DISCRETE,
                source_tag=tag_name,
                config={
                    "states": [
                        {"value": 0, "output": color_off},
                        {"value": 1, "output": color_on},
                    ],
                },
            ))

        # 闪烁绑定
        if blink and not any(b.property == "flashing" for b in item.bindings):
            item.bindings.append(BindingSpec(
                property="flashing",
                kind=BindingKind.FLASHING,
                source_tag=tag_name,
            ))

    def _enrich_iofield(
        self,
        item: ScreenItemSpec,
        oid: str,
        existing_tags: dict,
        new_tags: list,
    ):
        """为 IOField 推断 TagSpec。"""

        # V4.2: 先检查已有绑定，避免生成重复自动变量
        existing_tag = self._find_existing_binding(item)
        if existing_tag:
            item.tag_binding = existing_tag
            if existing_tag not in existing_tags:
                inferred_type = self.infer_tag_data_type_for_item(item)
                ts = self._make_tag_spec(existing_tag, inferred_type, oid, existing_tags, new_tags)
                if ts:
                    new_tags.append(ts)
                    existing_tags[existing_tag] = ts
            else:
                # V5.5R3: 已有 tag 但 data_type 可能为 Int 等非推断类型，强制修正
                existing = existing_tags.get(existing_tag)
                inferred_type = self.infer_tag_data_type_for_item(item)
                if existing and inferred_type:
                    current_type = getattr(existing, 'data_type', '')
                    if current_type != inferred_type:
                        try:
                            if isinstance(existing, dict):
                                existing["data_type"] = inferred_type
                            elif hasattr(existing, 'data_type'):
                                existing.data_type = inferred_type
                        except Exception:
                            pass
            return

        tag_name = self._make_tag_name(oid, IOFIELD_PREFIX, existing_tags)

        existing_pt = (item.tag_binding or "").strip()
        if existing_pt:
            tag_name = existing_pt
        else:
            item.tag_binding = tag_name

        data_type = self._infer_iofield_datatype_from_item(item)
        unit = item.properties.get("unit", "")

        if tag_name not in existing_tags:
            comment_parts = [f"数值显示 — {item.text.get('zh-CN', oid)}"]
            if unit:
                comment_parts.append(f"单位: {unit}")
            ts = TagSpec(
                name=tag_name,
                table="DefaultTagTable",
                scope=TagScope.EXTERNAL if self.plc_prefix else TagScope.INTERNAL,
                data_type=data_type,
                address=self._make_address(tag_name),
                comment={"zh-CN": "；".join(comment_parts)},
            )
            new_tags.append(ts)
            existing_tags[tag_name] = ts

        if not item.bindings:
            item.bindings.append(BindingSpec(
                property="value",
                kind=BindingKind.DIRECT_TAG,
                source_tag=tag_name,
            ))

    def _enrich_symbolic_iofield(
        self,
        item: ScreenItemSpec,
        oid: str,
        existing_tags: dict,
        new_tags: list,
    ):
        """为 SymbolicIOField 推断 TagSpec 和文本列表。

        每个 SymbolicIOField 自动生成:
          - 一个 Int 类型 HMI tag
          - 一个 TextList（名称: {tag_name}_TextList）
          - 默认条目可由 item.properties["text_list_entries"] 覆盖

        如果未创建文本列表，标记降级警告。
        """

        # V4.2: 先检查已有绑定，避免生成重复自动变量
        existing_tag = self._find_existing_binding(item)
        if existing_tag:
            item.tag_binding = existing_tag
            if existing_tag not in existing_tags:
                ts = self._make_tag_spec(existing_tag, "Int", oid, existing_tags, new_tags)
                if ts:
                    new_tags.append(ts)
                    existing_tags[existing_tag] = ts
            return

        tag_name = self._make_tag_name(oid, SYMBOLIC_IOFIELD_PREFIX, existing_tags)

        existing_pt = (item.tag_binding or "").strip()
        if existing_pt:
            tag_name = existing_pt
        else:
            item.tag_binding = tag_name

        # 文本列表名称 — 每个 SIO 独立
        text_list_name = item.properties.get("text_list") or f"{tag_name}_TextList"
        item.properties["text_list"] = text_list_name

        # 文本列表条目（默认或自定义）
        if "text_list_entries" not in item.properties:
            item.properties["text_list_entries"] = [
                (0, "停止"),
                (1, "手动"),
                (2, "自动"),
            ]

        if tag_name not in existing_tags:
            ts = TagSpec(
                name=tag_name,
                table="DefaultTagTable",
                scope=TagScope.EXTERNAL if self.plc_prefix else TagScope.INTERNAL,
                data_type="Int",
                address=self._make_address(tag_name),
                comment={
                    "zh-CN": (
                        f"枚举选择 — {item.text.get('zh-CN', oid)} "
                        f"(关联文本列表: {text_list_name})"
                    ),
                },
            )
            new_tags.append(ts)
            existing_tags[tag_name] = ts

        if not item.bindings:
            item.bindings.append(BindingSpec(
                property="value",
                kind=BindingKind.DIRECT_TAG,
                source_tag=tag_name,
            ))

    # ------------------------------------------------------------------
    # PLC 地址映射 — 语义匹配（四层策略）
    # ------------------------------------------------------------------

    def _apply_plc_mapping(
        self,
        project: HmiProjectSpec,
        plc_tag_mapping: Dict[str, str],
    ):
        """将 PLC 地址映射应用到 HmiProjectSpec 的 tags 中。

        语义匹配四层策略（按优先级依次尝试）：
          1. 精确匹配变量名
          2. 去掉 BTN_/STS_/LMP_/MEM_ 前缀后匹配
          3. 按 screen item id 匹配
          4. 按中文文本匹配

        匹配不到时保留 address=null，标记 pending_mapping=true。
        """
        if not plc_tag_mapping:
            return

        # 建立所有 screen items 的索引（按 id 和中文文本）
        item_by_id: Dict[str, list[ScreenItemSpec]] = {}
        item_by_text: Dict[str, list[ScreenItemSpec]] = {}
        for screen in project.screens:
            for item in screen.items:
                item_by_id.setdefault(item.id, []).append(item)
                zh_text = item.text.get("zh-CN", "").strip()
                if zh_text:
                    item_by_text.setdefault(zh_text, []).append(item)

        # 预处理映射表 — 将 "VariableName" → "DB10.DBX0.0"
        mapping_stripped: Dict[str, str] = {}
        for key, addr in plc_tag_mapping.items():
            mapping_stripped[key] = addr
            from backend.utils.tag_prefix_utils import strip_known_tag_prefixes
            stripped = strip_known_tag_prefixes(key)
            if stripped != key and stripped not in mapping_stripped:
                mapping_stripped[stripped] = addr

        for tag in project.tags:
            tag_name = tag.name
            address = None

            # Level 1: 精确变量名匹配
            if tag_name in plc_tag_mapping:
                address = plc_tag_mapping[tag_name]

            # Level 2: 去掉前缀后匹配
            if address is None:
                from backend.utils.tag_prefix_utils import strip_known_tag_prefixes
                stripped = strip_known_tag_prefixes(tag_name)
                if stripped != tag_name and stripped in plc_tag_mapping:
                    address = plc_tag_mapping[stripped]

            # Level 3: 按 item id 匹配（tag 名与某个 item id 相同）
            if address is None and tag_name in item_by_id:
                for item in item_by_id[tag_name]:
                    if item.id in plc_tag_mapping:
                        address = plc_tag_mapping[item.id]
                        break

            # Level 4: 按中文文本匹配
            if address is None:
                for zh_text, items in item_by_text.items():
                    if zh_text in plc_tag_mapping:
                        # 检查此 tag 是否关联到某个匹配的 item
                        for item in items:
                            if item.tag_binding == tag_name:
                                address = plc_tag_mapping[zh_text]
                                break
                        if address is not None:
                            break

            # 应用地址
            if address is not None:
                tag.address = address
                tag.scope = TagScope.EXTERNAL
                if "pending_mapping" in tag.metadata:
                    del tag.metadata["pending_mapping"]
            else:
                # 未匹配到 — 保持 address 为 None/null
                tag.metadata["pending_mapping"] = True

    @staticmethod
    def _detect_variable_conflicts_in_raw_ir(legacy_ir: Dict[str, Any]):
        """检测旧 IR dict 中的变量冲突（在适配器转换前执行）。

        1. 同名同类型 — 允许复用（不报错）
        2. 同名不同类型 — 记录冲突标记
        3. 同名不同地址 — 记录冲突标记

        冲突标记存储在每个变量的 metadata 中，后续 enrich 流程会检查。
        """
        raw_tags: list = legacy_ir.get("tags") or []
        seen: Dict[str, dict] = {}
        conflicts: list[dict] = []

        for t in raw_tags:
            name = (t.get("name") or "").strip()
            if not name:
                continue
            if name in seen:
                existing = seen[name]
                existing_dt = existing.get("data_type", "?")
                current_dt = t.get("data_type", "?")
                existing_addr = existing.get("address") or ""
                current_addr = t.get("address") or ""

                if existing_dt != current_dt:
                    conflicts.append({
                        "name": name,
                        "kind": "type_conflict",
                        "detail": f"'{existing_dt}' vs '{current_dt}'",
                    })
                elif existing_addr and current_addr and existing_addr != current_addr:
                    conflicts.append({
                        "name": name,
                        "kind": "address_conflict",
                        "detail": f"'{existing_addr}' vs '{current_addr}'",
                    })
            else:
                seen[name] = t

        # 将冲突信息写入 legacy_ir 供后续使用
        if conflicts:
            legacy_ir.setdefault("_variable_conflicts", []).extend(conflicts)

    # ------------------------------------------------------------------
    # Backfill: 旧格式 VBS 脚本生成（仅 backward compat）
    # ------------------------------------------------------------------

    def _backfill_legacy_scripts(
        self,
        obj: dict,
        oid: str,
        item: ScreenItemSpec,
        existing_scripts: dict,
        new_scripts: list,
    ):
        """从语义模型回填旧 IR 的 VBS 脚本字段。"""
        tag_mode = item.properties.get("tag_mode", "momentary")
        tag_name = item.tag_binding or ""

        if item.type != ScreenItemType.BUTTON or not tag_name:
            return

        if tag_mode == "toggle":
            self._add_toggle_scripts_to_legacy(
                obj, oid, tag_name, existing_scripts, new_scripts
            )
        else:
            self._add_momentary_scripts_to_legacy(
                obj, oid, tag_name, existing_scripts, new_scripts
            )

    def _add_toggle_scripts_to_legacy(
        self, obj, oid, tag_name, existing_scripts, new_scripts
    ):
        script_name = f"Sub_{oid}_Toggle"
        text = obj.get("text", oid)
        purpose = f"切换按钮「{text}」— 翻转变量 {tag_name}"

        code = VBS_TOGGLE_TEMPLATE.format(purpose=purpose, tag_name=tag_name)

        if script_name not in existing_scripts:
            new_scripts.append({
                "name": script_name,
                "language": "VBS",
                "purpose": purpose,
                "code": code,
            })

        if not obj.get("click_script"):
            obj["click_script"] = script_name
        if obj.get("tag_mode") == "toggle":
            obj.setdefault("press_script", None)
            obj.setdefault("release_script", None)

    def _add_momentary_scripts_to_legacy(
        self, obj, oid, tag_name, existing_scripts, new_scripts
    ):
        text = obj.get("text", oid)

        press_name = f"Sub_{oid}_Press"
        press_code = VBS_MOMENTARY_PRESS_TEMPLATE.format(
            purpose=f"按钮「{text}」按下", tag_name=tag_name,
        )
        if press_name not in existing_scripts:
            new_scripts.append({
                "name": press_name,
                "language": "VBS",
                "purpose": f"按钮「{text}」— 按下置位 {tag_name}",
                "code": press_code,
            })

        release_name = f"Sub_{oid}_Release"
        release_code = VBS_MOMENTARY_RELEASE_TEMPLATE.format(
            purpose=f"按钮「{text}」释放", tag_name=tag_name,
        )
        if release_name not in existing_scripts:
            new_scripts.append({
                "name": release_name,
                "language": "VBS",
                "purpose": f"按钮「{text}」— 释放复位 {tag_name}",
                "code": release_code,
            })

        if not obj.get("press_script"):
            obj["press_script"] = press_name
        if not obj.get("release_script"):
            obj["release_script"] = release_name

    # ------------------------------------------------------------------
    # 检测方法（从 ScreenItemSpec 属性推断）
    # ------------------------------------------------------------------

    def _detect_toggle_from_item(self, item: ScreenItemSpec, oid: str) -> bool:
        """从 ScreenItemSpec 推断是否 toggle 按钮。"""
        tag_mode = item.properties.get("tag_mode")
        if tag_mode == "toggle":
            return True
        if tag_mode == "momentary":
            return False

        text = item.text.get("zh-CN", "").lower()
        combined = f"{text} {oid.lower()}"
        for kw in TOGGLE_KEYWORDS:
            if kw.lower() in combined:
                return True
        if oid.startswith("MEM_"):
            return True
        return False

    def _detect_alarm_from_item(self, item: ScreenItemSpec, oid: str) -> bool:
        """从 ScreenItemSpec 推断是否报警指示灯。"""
        if item.properties.get("blink"):
            return True

        color_on = (item.properties.get("color_on") or "").lower()
        if color_on:
            try:
                r = int(color_on.lstrip("#")[0:2], 16)
                if r > 200:
                    return True
            except Exception:
                pass

        text = item.text.get("zh-CN", "").lower()
        combined = f"{text} {oid.lower()}"
        for kw in ALARM_KEYWORDS:
            if kw.lower() in combined:
                return True
        if oid.startswith("LMP_"):
            return True
        return False

    # ------------------------------------------------------------------
    # IOField 数据类型推断
    # ------------------------------------------------------------------

    def _infer_iofield_datatype_from_item(self, item: ScreenItemSpec) -> str:
        """从 ScreenItemSpec 属性推断 IOField 数据类型。"""
        fmt = (item.properties.get("display_format") or "").strip()
        if fmt == "String":
            return "String"
        elif fmt in ("Hex", "Binary"):
            return "Word"
        elif fmt == "Decimal":
            decimals = int(item.properties.get("decimal_digits", 0))
            return "Real" if decimals > 0 else "Int"
        return "Real"

    # ------------------------------------------------------------------
    # 命名与地址生成
    # ------------------------------------------------------------------

    # TIA 变量名非法字符（统一替换为下划线）
    _ILLEGAL_NAME_CHARS: set[str] = {
        "/", "\\", "@", "#", "$", "%", "^", "&", "*", "(", ")",
        "-", "+", "=", "[", "]", "{", "}", "|", ";", ":", "\"",
        "'", "<", ">", ",", "?", " ", "\t", "~", "`",
    }

    @classmethod
    def normalize_tag_name(cls, name: str) -> str:
        """将变量名中的非法字符统一替换为下划线。

        TIA Portal 变量名要求：只能包含字母、数字、下划线，不能以数字开头。
        """
        result = name
        for ch in cls._ILLEGAL_NAME_CHARS:
            result = result.replace(ch, "_")
        # 合并连续下划线
        while "__" in result:
            result = result.replace("__", "_")
        # 去除首尾下划线（保留有意义部分）
        result = result.strip("_")
        if not result:
            result = "VAR_Unnamed"
        return result

    def _make_tag_name(
        self,
        oid: str,
        prefix: str,
        existing_tags: dict,
    ) -> str:
        """生成变量名（自动规范化非法字符）。"""
        # 先规范化 oid 中的非法字符
        sanitized_oid = self.normalize_tag_name(oid)
        from backend.utils.tag_prefix_utils import strip_known_tag_prefixes
        base_name = strip_known_tag_prefixes(sanitized_oid)

        candidate = self.normalize_tag_name(f"{prefix}{base_name}")
        if candidate in existing_tags:
            idx = 2
            while f"{candidate}_{idx}" in existing_tags:
                idx += 1
            candidate = f"{candidate}_{idx}"
        return candidate

    def _make_address(self, tag_name: str) -> str:
        if self.plc_prefix:
            return f"{self.plc_prefix}{tag_name}"
        return ""

    # ------------------------------------------------------------------
    # 旧版（V2.3）内部检测方法 — 保留给其他模块直接调用的兼容
    # ------------------------------------------------------------------

    def _detect_toggle(self, obj: dict, oid: str) -> bool:
        """[DEPRECATED] 从旧 dict 检测 toggle。保留供外部兼容。"""
        if obj.get("self_holding") or obj.get("tag_mode") == "toggle":
            return True
        if obj.get("tag_mode") == "momentary":
            return False
        text = (obj.get("text") or "").lower()
        label = (obj.get("label") or "").lower()
        combined = f"{text} {label} {oid.lower()}"
        for kw in TOGGLE_KEYWORDS:
            if kw.lower() in combined:
                return True
        if oid.startswith("MEM_"):
            return True
        return False

    def _detect_alarm(self, obj: dict, oid: str) -> bool:
        """[DEPRECATED] 从旧 dict 检测 alarm。保留供外部兼容。"""
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
        text = (obj.get("label") or "").lower()
        combined = f"{text} {oid.lower()}"
        for kw in ALARM_KEYWORDS:
            if kw.lower() in combined:
                return True
        if oid.startswith("LMP_"):
            return True
        return False

    def _infer_iofield_datatype(self, obj: dict) -> str:
        """[DEPRECATED] 从旧 dict 推断 IOField 类型。保留供外部兼容。"""
        fmt = (obj.get("display_format") or "").strip()
        if obj.get("data_type") in DEFAULT_DATA_TYPES:
            return obj["data_type"]
        if fmt == "String":
            return "String"
        elif fmt in ("Hex", "Binary"):
            return "Word"
        elif fmt == "Decimal":
            decimals = obj.get("decimal_digits", 0)
            return "Real" if decimals > 0 else "Int"
        return "Real"

    # ------------------------------------------------------------------
    # V4.1 Tag integrity validation
    # ------------------------------------------------------------------

    @staticmethod
    def validate_project_tag_integrity(project: HmiProjectSpec) -> list[Diagnostic]:
        """校验 HmiProjectSpec 的 tag 完整性。

        检查:
          - item.binding.tag 为空
          - binding.tag 不在 project.tags
          - 同名变量类型冲突
          - 同名变量地址冲突
        """
        from .validation.tag_binding_gate import validate_project_tag_bindings
        return validate_project_tag_bindings(project)

    @staticmethod
    def raise_if_project_tag_integrity_invalid(project: HmiProjectSpec) -> None:
        """如果 project tag 完整性问题存在阻断错误，抛出 ValueError。"""
        errors = VariableEngine.validate_project_tag_integrity(project)
        blocking = [e for e in errors if e.severity == DiagnosticSeverity.ERROR]
        if blocking:
            msg_lines = [f"Invalid project tag integrity ({len(blocking)} error(s)):"]
            for e in blocking:
                msg_lines.append(f"  - [{e.code}] {e.message}")
            raise ValueError("\n".join(msg_lines))

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
        """获取变量绑定摘要。"""
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
                continue
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
    """便捷函数：一行调用完成变量自动绑定（旧兼容）。"""
    engine = VariableEngine(plc_prefix=plc_prefix)
    return engine.generate(ir)


def enrich_to_v2(ir: Dict[str, Any], target_hint: str | None = None) -> HmiProjectSpec:
    """便捷函数：旧 IR → HmiProjectSpec（新 V3.0 API）。"""
    engine = VariableEngine()
    return engine.enrich(ir, target_hint=target_hint)

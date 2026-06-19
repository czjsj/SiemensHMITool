# -*- coding: utf-8 -*-
"""
Legacy IR Adapter — 将现有 V2.3 格式的 IR dict 转换为 HMI IR V2 (HmiProjectSpec)。

不依赖 Flask、pythonnet 或 Siemens DLL。
方案文档 §6 + §14.1 对齐。

映射策略：
  - 已知字段严格映射
  - 不确定的字段保留在 metadata.extra 中
  - 不做猜测性删除
"""

from __future__ import annotations

from typing import Any

from .enums import (
    BindingKind,
    ButtonBehavior,
    ConnectionKind,
    HmiFamily,
    IndicatorMode,
    ScriptLanguage,
    SemanticEvent,
    SemanticActionType,
    ScreenItemType,
    TagDirection,
    TagScope,
)
from .ir_v2 import (
    ActionSpec,
    BindingSpec,
    EventSpec,
    GeometrySpec,
    HmiProjectSpec,
    ProjectMetadata,
    ResourceSpec,
    ScreenItemSpec,
    ScreenSpec,
    ScriptSpec,
    TagSpec,
    TargetSpec,
)
from .diagnostics import Diagnostic, DiagnosticCodes
from .enums import DiagnosticSeverity


# ---------------------------------------------------------------------------
# 对象类型映射
# ---------------------------------------------------------------------------

_OLD_TYPE_TO_SCREEN_ITEM_TYPE: dict[str, ScreenItemType] = {
    "Button": ScreenItemType.BUTTON,
    "IOField": ScreenItemType.IO_FIELD,
    "SymbolicIOField": ScreenItemType.SYMBOLIC_IO_FIELD,
    "Indicator": ScreenItemType.INDICATOR,
    "Text": ScreenItemType.TEXT,
    "text": ScreenItemType.TEXT,
    "button": ScreenItemType.BUTTON,
    "io_field": ScreenItemType.IO_FIELD,
    "symbolic_io_field": ScreenItemType.SYMBOLIC_IO_FIELD,
    "indicator": ScreenItemType.INDICATOR,
}

_HMI_TYPE_TO_FAMILY: dict[str, HmiFamily] = {
    "Basic": HmiFamily.BASIC,
    "Comfort": HmiFamily.COMFORT,
    "Unified": HmiFamily.UNIFIED,
}

# 旧事件脚本键 → 语义事件
_SCRIPT_KEY_TO_EVENT: dict[str, SemanticEvent] = {
    "press_script": SemanticEvent.PRESS,
    "release_script": SemanticEvent.RELEASE,
    "click_script": SemanticEvent.CLICK,
}

# 旧 tag_mode → 动作推断
_TAG_MODE_TO_ACTIONS: dict[str, list[SemanticActionType]] = {
    "momentary": [SemanticActionType.SET_BIT, SemanticActionType.RESET_BIT],
    "toggle": [SemanticActionType.TOGGLE_BIT],
}


class LegacyIrAdapter:
    """将旧版 IR dict 转换为 HmiProjectSpec。

    使用方式:
        adapter = LegacyIrAdapter()
        project_spec, diagnostics = adapter.convert(old_ir_dict)
    """

    def __init__(self, target_hint: str | None = None):
        """
        参数:
            target_hint: 可选的设备类型提示（"basic"/"comfort"/"unified"），
                        用于在旧 IR 缺少明确 hmi_type 时兜底。
        """
        self._target_hint = target_hint

    def convert(self, legacy_ir: dict[str, Any]) -> tuple[HmiProjectSpec, list[Diagnostic]]:
        """将旧 IR dict 转换为 HmiProjectSpec。

        参数:
            legacy_ir: 旧版 IR 字典（来自 validate_ir 或 VariableEngine 输出）。

        返回:
            (HmiProjectSpec, diagnostics_list)
        """
        diagnostics: list[Diagnostic] = []

        if not isinstance(legacy_ir, dict):
            diagnostics.append(Diagnostic(
                code=DiagnosticCodes.IR_VALIDATION_ERROR,
                severity=DiagnosticSeverity.ERROR,
                message="旧 IR 必须是 dict 类型",
            ))
            return self._empty_project(), diagnostics

        meta = legacy_ir.get("meta") or {}
        objects = legacy_ir.get("objects") or []
        tags = legacy_ir.get("tags") or []
        scripts = legacy_ir.get("scripts") or []
        text_lists = legacy_ir.get("text_lists") or []

        # ---- 项目元数据 ----
        metadata = ProjectMetadata(
            project_name=meta.get("screen_name", ""),
            description=meta.get("description", ""),
            extra={
                "legacy_generation_mode": meta.get("generation_mode", "auto"),
                "legacy_template_screen": meta.get("template_screen", ""),
                "legacy_title": meta.get("title", ""),
            },
        )

        # ---- 目标设备 ----
        target = self._build_target(meta, diagnostics)

        # ---- 变量 ----
        v2_tags = self._build_tags(tags, diagnostics)

        # ---- 脚本 ----
        v2_scripts = self._build_scripts(scripts, diagnostics)

        # ---- 资源（文本列表） ----
        v2_resources = self._build_resources(text_lists, diagnostics)

        # ---- 画面 ----
        screen = self._build_screen(meta, objects, diagnostics)

        project = HmiProjectSpec(
            schema_version="2.0",
            metadata=metadata,
            target=target,
            connections=[],
            tags=v2_tags,
            scripts=v2_scripts,
            resources=v2_resources,
            screens=[screen] if screen else [],
            diagnostics=diagnostics,
        )

        return project, diagnostics

    # ------------------------------------------------------------------
    # 内部构建方法
    # ------------------------------------------------------------------

    def _build_target(self, meta: dict, diagnostics: list[Diagnostic]) -> TargetSpec:
        """构建 TargetSpec。"""
        hmi_type = meta.get("hmi_type", "Comfort")
        family = _HMI_TYPE_TO_FAMILY.get(hmi_type, HmiFamily.COMFORT)

        resolution = meta.get("resolution", "")

        return TargetSpec(
            family=family,
            tia_version=None,
            device_name=None,
            device_type=None,
            resolution=resolution or None,
            language="zh-CN",
        )

    def _build_tags(
        self, old_tags: list[dict], diagnostics: list[Diagnostic]
    ) -> list[TagSpec]:
        """转换旧 tags 到 TagSpec 列表。"""
        result: list[TagSpec] = []
        seen: set[str] = set()

        for t in old_tags:
            name = (t.get("name") or "").strip()
            if not name:
                diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.IR_VALIDATION_ERROR,
                    severity=DiagnosticSeverity.WARNING,
                    phase="P10_VALIDATE_DEPENDENCIES",
                    object_type="tag",
                    message="旧 IR 中存在无名称的变量，已跳过",
                ))
                continue
            if name in seen:
                diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.IR_VALIDATION_ERROR,
                    severity=DiagnosticSeverity.WARNING,
                    phase="P10_VALIDATE_DEPENDENCIES",
                    object_type="tag",
                    object_name=name,
                    message=f"变量名 '{name}' 重复，仅保留第一个",
                ))
                continue
            seen.add(name)

            result.append(TagSpec(
                name=name,
                table="AI_Generated",
                scope=TagScope.EXTERNAL if t.get("address") else TagScope.INTERNAL,
                data_type=t.get("data_type", "Bool"),
                address=t.get("address") or None,
                comment={"zh-CN": t.get("comment", "")} if t.get("comment") else {},
            ))

        return result

    def _build_scripts(
        self, old_scripts: list[dict], diagnostics: list[Diagnostic]
    ) -> list[ScriptSpec]:
        """转换旧 scripts 到 ScriptSpec 列表。"""
        result: list[ScriptSpec] = []
        seen: set[str] = set()

        for s in old_scripts:
            name = (s.get("name") or "").strip()
            if not name:
                continue
            if name in seen:
                continue
            seen.add(name)

            lang = s.get("language", "VBS")
            script_lang = (
                ScriptLanguage.VBS if "vbs" in lang.lower()
                else ScriptLanguage.JAVASCRIPT if "javascript" in lang.lower() or "js" in lang.lower()
                else ScriptLanguage.SEMANTIC
            )

            result.append(ScriptSpec(
                name=name,
                language=script_lang,
                body=s.get("code", ""),
                parameters=[],
                target_families=[],
            ))

        return result

    def _build_resources(
        self, text_lists: list[dict], diagnostics: list[Diagnostic]
    ) -> list[ResourceSpec]:
        """转换旧 text_lists 到 ResourceSpec。"""
        result: list[ResourceSpec] = []

        for tl in text_lists:
            name = (tl.get("name") or "").strip()
            if not name:
                continue
            result.append(ResourceSpec(
                name=name,
                kind="text_list",
                entries=tl.get("entries", []),
            ))

        return result

    def _build_screen(
        self, meta: dict, objects: list[dict], diagnostics: list[Diagnostic]
    ) -> ScreenSpec | None:
        """构建 ScreenSpec。"""
        screen_size = meta.get("_screen_size") or {}
        # 兼容：_screen_size 可能在顶层而非 meta
        if not screen_size:
            res = meta.get("resolution", "1280x800")
            parsed = _parse_resolution(res) or (1280, 800)
            screen_size = {"width": parsed[0], "height": parsed[1]}

        screen_name = meta.get("screen_name", "Screen_1")

        items = self._build_items(objects, diagnostics)

        return ScreenSpec(
            name=screen_name,
            width=int(screen_size.get("width", 1280)),
            height=int(screen_size.get("height", 800)),
            template=meta.get("template_xml") or None,
            items=items,
        )

    def _build_items(
        self, old_objects: list[dict], diagnostics: list[Diagnostic]
    ) -> list[ScreenItemSpec]:
        """转换旧 objects 到 ScreenItemSpec 列表。"""
        result: list[ScreenItemSpec] = []

        for obj in old_objects:
            otype = obj.get("type", "")
            item_type = _OLD_TYPE_TO_SCREEN_ITEM_TYPE.get(otype)
            if item_type is None:
                diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.LEGACY_ADAPTER_WARNING,
                    severity=DiagnosticSeverity.WARNING,
                    object_type=otype,
                    object_name=obj.get("id", "?"),
                    message=f"旧 IR 对象类型 '{otype}' 无 V2 对应类型，已跳过",
                ))
                continue

            oid = obj.get("id", f"{otype}_unknown")
            name = obj.get("id", oid)

            geometry = GeometrySpec(
                x=int(obj.get("x", 0)),
                y=int(obj.get("y", 0)),
                width=int(obj.get("width", 120)),
                height=int(obj.get("height", 40)),
                radius=int(obj.get("radius")) if "radius" in obj else None,
            )

            process_tag = (obj.get("process_tag") or "").strip() or None

            # 动态绑定
            bindings: list[BindingSpec] = []
            events: list[EventSpec] = []

            if item_type == ScreenItemType.BUTTON:
                bindings, events = self._build_button_bindings_and_events(
                    obj, process_tag
                )
            elif item_type == ScreenItemType.INDICATOR:
                bindings, events = self._build_indicator_bindings_and_events(
                    obj, process_tag
                )

            # 静态属性
            properties: dict[str, Any] = {}
            if item_type == ScreenItemType.TEXT:
                properties["font_size"] = int(obj.get("font_size", 18))
                properties["bold"] = bool(obj.get("bold", False))
                properties["color"] = obj.get("color", "#E6EDF3")
            elif item_type == ScreenItemType.BUTTON:
                properties["background_color"] = obj.get(
                    "background_color", "#2BB673"
                )
                # 仅在显式提供 tag_mode 时才设置，不设默认值
                # 让 VariableEngine 根据文本关键词做自动检测
                if "tag_mode" in obj:
                    properties["tag_mode"] = obj["tag_mode"]
            elif item_type == ScreenItemType.IO_FIELD:
                properties["mode"] = obj.get("mode", "Output")
                properties["display_format"] = obj.get("display_format", "Decimal")
                properties["decimal_digits"] = int(obj.get("decimal_digits", 0))
                properties["font_size"] = int(obj.get("font_size", 16))
            elif item_type == ScreenItemType.SYMBOLIC_IO_FIELD:
                properties["mode"] = obj.get("mode", "Output")
                properties["text_list"] = obj.get("text_list", "")
                properties["font_size"] = int(obj.get("font_size", 16))
            elif item_type == ScreenItemType.INDICATOR:
                properties["color_on"] = obj.get("color_on", "#27D17F")
                properties["color_off"] = obj.get("color_off", "#3A4250")
                properties["blink"] = bool(obj.get("blink", False))
                properties["label"] = obj.get("label", "")

            # 多语言文本
            text_dict: dict[str, str] = {}
            text_val = obj.get("text", "")
            if text_val:
                text_dict["zh-CN"] = str(text_val)
            label_val = obj.get("label", "")
            if label_val:
                text_dict.setdefault("zh-CN", str(label_val))

            # V4.0: 自动推断 template_ref, behavior, indicator_mode
            template_ref = None
            behavior = None
            indicator_mode = None
            direction = TagDirection.READ_WRITE

            if item_type == ScreenItemType.BUTTON:
                tag_mode = obj.get("tag_mode", "momentary")
                if tag_mode == "toggle":
                    behavior = ButtonBehavior.TOGGLE
                    template_ref = "BTN_TOGGLE_TEMPLATE"
                    direction = TagDirection.READ_WRITE
                elif tag_mode == "momentary":
                    behavior = ButtonBehavior.MOMENTARY
                    template_ref = "BTN_MOMENTARY_TEMPLATE"
                    direction = TagDirection.WRITE
                else:
                    behavior = ButtonBehavior.MOMENTARY
                    template_ref = "BTN_MOMENTARY_TEMPLATE"

            elif item_type == ScreenItemType.INDICATOR:
                indicator_mode = IndicatorMode.BOOL_COLOR
                template_ref = "LMP_STATUS_TEMPLATE"
                direction = TagDirection.READ

            result.append(ScreenItemSpec(
                id=oid,
                name=name,
                type=item_type,
                geometry=geometry,
                properties=properties,
                text=text_dict,
                tag_binding=process_tag,
                bindings=bindings,
                events=events,
                template_ref=template_ref,
                behavior=behavior,
                indicator_mode=indicator_mode,
                metadata={} if not process_tag else {},
            ))

        return result

    def _build_button_bindings_and_events(
        self, obj: dict, process_tag: str | None
    ) -> tuple[list[BindingSpec], list[EventSpec]]:
        """从旧 Button 对象构建绑定和事件。"""
        bindings: list[BindingSpec] = []
        events: list[EventSpec] = []

        tag_mode = obj.get("tag_mode", "momentary")

        if process_tag:
            # 主变量绑定
            bindings.append(BindingSpec(
                property="value",
                kind=BindingKind.DIRECT_TAG,
                source_tag=process_tag,
            ))

            action_types = _TAG_MODE_TO_ACTIONS.get(tag_mode, [SemanticActionType.SET_BIT])

            # 构建事件
            if tag_mode == "toggle":
                events.append(EventSpec(
                    event=SemanticEvent.CLICK,
                    actions=[ActionSpec(
                        type=SemanticActionType.TOGGLE_BIT,
                        tag=process_tag,
                    )],
                ))
            elif tag_mode == "momentary":
                events.append(EventSpec(
                    event=SemanticEvent.PRESS,
                    actions=[ActionSpec(
                        type=SemanticActionType.SET_BIT,
                        tag=process_tag,
                        value=1,
                    )],
                ))
                events.append(EventSpec(
                    event=SemanticEvent.RELEASE,
                    actions=[ActionSpec(
                        type=SemanticActionType.RESET_BIT,
                        tag=process_tag,
                        value=0,
                    )],
                ))

        return bindings, events

    def _build_indicator_bindings_and_events(
        self, obj: dict, process_tag: str | None
    ) -> tuple[list[BindingSpec], list[EventSpec]]:
        """从旧 Indicator 对象构建绑定和事件。"""
        bindings: list[BindingSpec] = []
        events: list[EventSpec] = []

        if process_tag:
            blink = bool(obj.get("blink", False))
            blink_tag = obj.get("blink_tag") or (process_tag if blink else None)

            # 颜色动态绑定（离散）
            color_on = obj.get("color_on", "#27D17F")
            color_off = obj.get("color_off", "#3A4250")
            bindings.append(BindingSpec(
                property="background_color",
                kind=BindingKind.DISCRETE,
                source_tag=process_tag,
                config={
                    "states": [
                        {"value": 0, "output": color_off},
                        {"value": 1, "output": color_on},
                    ],
                },
            ))

            # 闪烁绑定
            if blink and blink_tag:
                bindings.append(BindingSpec(
                    property="flashing",
                    kind=BindingKind.FLASHING,
                    source_tag=blink_tag,
                ))

        return bindings, events

    @staticmethod
    def _empty_project() -> HmiProjectSpec:
        """返回空项目（用于严重错误时）。"""
        return HmiProjectSpec(
            schema_version="2.0",
            metadata=ProjectMetadata(project_name="__empty__"),
        )


# ---------------------------------------------------------------------------
# 模块级辅助函数
# ---------------------------------------------------------------------------


def _parse_resolution(value: str) -> tuple[int, int] | None:
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

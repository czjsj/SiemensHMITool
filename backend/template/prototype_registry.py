# -*- coding: utf-8 -*-
"""
PrototypeRegistry — 根据 IR 控件查找最合适的模板原型。

匹配优先级:
1. item.template_ref 精确匹配 prototype_id
2. item.type + behavior 匹配
3. item.type + indicator_mode 匹配
4. item.name / tag 前缀匹配
5. 默认同类型原型
6. 找不到则抛出明确异常
"""

from __future__ import annotations

from typing import Any

from .template_profile import ControlPrototype, ItemKind, TemplateProfile


class PrototypeNotFoundError(Exception):
    """找不到匹配的控件原型时抛出。"""

    def __init__(
        self,
        item_id: str,
        item_type: str,
        reason: str,
        available_prototypes: list[str],
    ):
        self.item_id = item_id
        self.item_type = item_type
        self.reason = reason
        self.available_prototypes = available_prototypes
        super().__init__(
            f"控件 '{item_id}' (type={item_type}) 找不到匹配的模板原型。"
            f"原因: {reason}。"
            f"可用原型: {available_prototypes}"
        )


class PrototypeRegistry:
    """模板原型注册表 — 从 TemplateProfile 中查找最合适的原型。

    使用方式:
        profile = analyze_template_screen(template_xml)
        registry = PrototypeRegistry(profile)
        prototype = registry.find_for_item(screen_item)
    """

    def __init__(self, profile: TemplateProfile):
        self._profile = profile
        self._all = profile.all_prototypes()

        # 构建查找索引
        self._by_id: dict[str, ControlPrototype] = {}
        self._by_behavior: dict[str, list[ControlPrototype]] = {}
        self._buttons: list[ControlPrototype] = profile.buttons
        self._indicators: list[ControlPrototype] = profile.indicators

        for proto in self._all:
            # 按 prototype_id 索引
            pid = proto.prototype_id
            if pid:
                self._by_id[pid] = proto

            # 按 behavior 索引 (仅按钮)
            if proto.item_kind == "button" and proto.behavior:
                self._by_behavior.setdefault(proto.behavior, []).append(proto)

            # 按 indicator_mode 索引 (仅指示灯)
            if proto.item_kind == "indicator" and proto.indicator_mode:
                self._by_behavior.setdefault(proto.indicator_mode, []).append(proto)

    def find_for_item(self, item: Any) -> ControlPrototype:
        """根据 IR 控件查找最合适模板原型。

        参数:
            item: ScreenItemSpec 或 dict，需包含 id/type 及其他匹配字段。

        返回:
            ControlPrototype 实例。

        抛出:
            PrototypeNotFoundError: 找不到任何匹配的原型。
        """
        item_id = _get(item, "id", "?")
        item_type = _get(item, "type", "unknown")

        # ---- 优先级 1: template_ref 精确匹配 prototype_id ----
        template_ref = _get(item, "template_ref")
        if template_ref:
            proto = self._by_id.get(template_ref)
            if proto:
                return proto

        # ---- 优先级 2: item.type + behavior 匹配 ----
        behavior = _get(item, "behavior")
        if item_type == "button" and behavior:
            candidates = self._by_behavior.get(behavior, [])
            if candidates:
                return candidates[0]

        # ---- 优先级 3: item.type + indicator_mode 匹配 ----
        indicator_mode = _get(item, "indicator_mode")
        if item_type == "indicator" and indicator_mode:
            candidates = self._by_behavior.get(indicator_mode, [])
            if candidates:
                return candidates[0]

        # ---- 优先级 4: item name/id 前缀匹配 ----
        item_kind = self._item_type_to_kind(item_type)
        if item_kind == "button":
            for proto in self._buttons:
                if _name_matches_prefix(item_id, proto.source_name):
                    return proto
        elif item_kind == "indicator":
            for proto in self._indicators:
                if _name_matches_prefix(item_id, proto.source_name):
                    return proto

        # ---- 优先级 5: 默认同类型原型 ----
        if item_kind == "button" and self._buttons:
            return self._buttons[0]
        if item_kind == "indicator" and self._indicators:
            return self._indicators[0]
        if self._profile.others:
            for proto in self._profile.others:
                if proto.item_kind == item_kind:
                    return proto

        # ---- 优先级 6: 找不到 ----
        available_ids = [p.prototype_id for p in self._all]
        raise PrototypeNotFoundError(
            item_id=item_id,
            item_type=item_type,
            reason=f"没有可用的 {item_type} 模板原型",
            available_prototypes=available_ids,
        )

    def has_prototype_for(self, item_type: str, behavior: str | None = None) -> bool:
        """检查是否存在指定类型的原型。"""
        try:
            # 构建一个临时 item 来测试
            temp_item = {"id": "__test__", "type": item_type}
            if behavior:
                temp_item["behavior"] = behavior
            self.find_for_item(temp_item)
            return True
        except PrototypeNotFoundError:
            return False

    @property
    def button_count(self) -> int:
        return len(self._buttons)

    @property
    def indicator_count(self) -> int:
        return len(self._indicators)

    @property
    def all_prototype_ids(self) -> list[str]:
        return [p.prototype_id for p in self._all]

    @staticmethod
    def _item_type_to_kind(item_type: str) -> ItemKind:
        """IR 类型 → ItemKind。"""
        mapping: dict[str, ItemKind] = {
            "button": "button",
            "Button": "button",
            "indicator": "indicator",
            "Indicator": "indicator",
            "io_field": "io_field",
            "IOField": "io_field",
            "symbolic_io_field": "symbolic_io_field",
            "SymbolicIOField": "symbolic_io_field",
            "text": "text",
            "Text": "text",
        }
        return mapping.get(item_type, "unknown")


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """从 dict 或 Pydantic model 中安全获取属性值。"""
    if isinstance(obj, dict):
        return obj.get(key, default)
    # Pydantic model / dataclass
    return getattr(obj, key, default)


def _name_matches_prefix(item_name: str, proto_name: str) -> bool:
    """检查 item 名称是否与原型名称有共同前缀。

    例如: "BTN_Start" 和 "BTN_Momentary_Template" 都有 "BTN_" 前缀。
    """
    # 找共同前缀
    item_lower = item_name.lower()
    proto_lower = proto_name.lower()

    # 检查至少 3 个字符的共同前缀
    min_len = min(len(item_lower), len(proto_lower))
    for i in range(min_len, 2, -1):
        if item_lower[:i] == proto_lower[:i]:
            return True
    return False

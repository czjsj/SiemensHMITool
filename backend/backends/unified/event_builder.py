# -*- coding: utf-8 -*-
"""Unified Event Builder — EventHandler 创建。

方案文档 §11.8 对齐。
"""
from __future__ import annotations
from backend.domain.ir_v2 import EventSpec, ActionSpec
from backend.domain.enums import SemanticEvent, SemanticActionType
from .reflection_adapter import UnifiedReflectionAdapter


class UnifiedEventBuilder:
    """Unified 事件处理器创建器。"""

    # 语义事件 → Unified EventHandler 类型
    EVENT_TO_HANDLER = {
        SemanticEvent.PRESS: "Press",
        SemanticEvent.RELEASE: "Release",
        SemanticEvent.CLICK: "Click",
        SemanticEvent.CHANGE: "Change",
        SemanticEvent.LOADED: "Load",
        SemanticEvent.UNLOADED: "Unload",
        SemanticEvent.ACTIVATE: "Activate",
        SemanticEvent.DEACTIVATE: "Deactivate",
    }

    def __init__(self, reflection: UnifiedReflectionAdapter | None = None):
        self._reflection = reflection or UnifiedReflectionAdapter()

    def build_event_handler(self, event: EventSpec) -> dict:
        handler_type = self.EVENT_TO_HANDLER.get(event.event, "Click")
        return {
            "HandlerType": handler_type,
            "Actions": [self._build_action_dict(a) for a in event.actions],
        }

    def resolve_event_enum(self, semantic_event: str) -> list[str]:
        return self._reflection.resolve_event(semantic_event)

    def _build_action_dict(self, action: ActionSpec) -> dict:
        d = {"ActionType": action.type.value}
        if action.tag:
            d["Tag"] = action.tag
        if action.value is not None:
            d["Value"] = action.value
        if action.screen:
            d["Screen"] = action.screen
        if action.script:
            d["Script"] = action.script
        if action.expression:
            d["Expression"] = action.expression
        return d

    def build_javascript(self, actions: list[ActionSpec]) -> str:
        """从语义动作列表生成 JavaScript（白名单 API）。"""
        lines = []
        for a in actions:
            if a.type == SemanticActionType.SET_BIT:
                tag = a.tag or "unknown"
                val = 1 if a.value is None else a.value
                lines.append(f'Tags("{tag}").Write({val});')
            elif a.type == SemanticActionType.RESET_BIT:
                tag = a.tag or "unknown"
                lines.append(f'Tags("{tag}").Write(0);')
            elif a.type == SemanticActionType.TOGGLE_BIT:
                tag = a.tag or "unknown"
                lines.append(f'Tags("{tag}").Write(!Tags("{tag}").Read());')
            elif a.type == SemanticActionType.SET_VALUE:
                lines.append(f'Tags("{a.tag}").Write({a.value});')
            elif a.type == SemanticActionType.ACTIVATE_SCREEN:
                lines.append(f'UI.ActivateScreen("{a.screen}");')
            elif a.type == SemanticActionType.INCREMENT:
                tag = a.tag or "unknown"
                lines.append(f'Tags("{tag}").Write(Tags("{tag}").Read() + {a.value or 1});')
            elif a.type == SemanticActionType.DECREMENT:
                tag = a.tag or "unknown"
                lines.append(f'Tags("{tag}").Write(Tags("{tag}").Read() - {a.value or 1});')
            else:
                lines.append(f'// Unsupported action: {a.type.value}')
        return "\n".join(lines)

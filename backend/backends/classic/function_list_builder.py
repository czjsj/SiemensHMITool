# -*- coding: utf-8 -*-
"""FunctionList Builder — 语义动作 → Classic HMI FunctionList XML。

方案文档 §9.3, §13.3 对齐。
"""
from __future__ import annotations
import uuid
from xml.sax.saxutils import escape as xml_escape
from backend.domain.ir_v2 import EventSpec, ActionSpec
from backend.domain.enums import SemanticActionType, SemanticEvent


class FunctionListBuilder:
    """Classic HMI FunctionList 生成器。

    将语义动作映射到系统函数类型模板。
    """

    # 语义动作 → 系统函数类型名（需从黄金 XML 读取，以下为 V18 Comfort 常见值）
    ACTION_SYSTEM_FUNCTION_MAP = {
        SemanticActionType.SET_BIT: "SetBit",
        SemanticActionType.RESET_BIT: "ResetBit",
        SemanticActionType.TOGGLE_BIT: "InvertBit",
        SemanticActionType.SET_VALUE: "SetValue",
        SemanticActionType.INCREMENT: "IncreaseValue",
        SemanticActionType.DECREMENT: "DecreaseValue",
        SemanticActionType.ACTIVATE_SCREEN: "ActivateScreen",
        SemanticActionType.OPEN_POPUP: "OpenPopup",
        SemanticActionType.CLOSE_POPUP: "ClosePopup",
        SemanticActionType.ACKNOWLEDGE_ALARM: "AcknowledgeAlarm",
    }

    # 事件 → WinCC 事件枚举名
    EVENT_ENUM_MAP = {
        SemanticEvent.PRESS: "OnPress",
        SemanticEvent.RELEASE: "OnRelease",
        SemanticEvent.CLICK: "OnClick",
        SemanticEvent.CHANGE: "OnChange",
        SemanticEvent.LOADED: "OnLoaded",
        SemanticEvent.UNLOADED: "OnUnloaded",
        SemanticEvent.ACTIVATE: "OnActivate",
        SemanticEvent.DEACTIVATE: "OnDeactivate",
    }

    def __init__(self):
        pass

    def build(self, event: EventSpec, target_family: str = "comfort") -> str:
        """为事件构建 FunctionList XML。"""
        ev_name = self.EVENT_ENUM_MAP.get(event.event, "OnClick")
        lines = [f'<Events>', f'  <Event Name="{ev_name}">', f'    <FunctionList>']
        for idx, action in enumerate(event.actions):
            lines.append(self.build_action(action, index=idx))
        lines.append(f'    </FunctionList>')
        lines.append(f'  </Event>')
        lines.append(f'</Events>')
        return "\n".join(lines)

    def build_action(self, action: ActionSpec, index: int = 0) -> str:
        sys_func = self.ACTION_SYSTEM_FUNCTION_MAP.get(action.type)
        if sys_func is None:
            return f'      <!-- Unsupported action: {action.type.value} -->'

        lines = [f'      <Function Number="{index}" Type="{sys_func}">']
        if action.tag:
            lines.append(f'        <TagName>{xml_escape(action.tag)}</TagName>')
        if action.value is not None:
            lines.append(f'        <Value>{xml_escape(str(action.value))}</Value>')
        if action.screen:
            lines.append(f'        <ScreenName>{xml_escape(action.screen)}</ScreenName>')
        if action.expression:
            lines.append(f'        <Expression>{xml_escape(action.expression)}</Expression>')
        lines.append(f'      </Function>')
        return "\n".join(lines)

    def supports_action(self, action: ActionSpec, target_family: str = "comfort") -> bool:
        if target_family == "basic":
            unsupported = {SemanticActionType.CALL_SCRIPT, SemanticActionType.WRITE_EXPRESSION, SemanticActionType.OPEN_POPUP}
            return action.type not in unsupported
        sys_func = self.ACTION_SYSTEM_FUNCTION_MAP.get(action.type)
        return sys_func is not None

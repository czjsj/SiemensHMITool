# -*- coding: utf-8 -*-
"""
HMI IR V2 枚举定义。

不依赖 Flask、pythonnet 或 Siemens DLL。
"""

from enum import Enum


class HmiFamily(str, Enum):
    """HMI 面板家族。"""
    BASIC = "basic"
    COMFORT = "comfort"
    UNIFIED = "unified"
    AUTO = "auto"


class TagScope(str, Enum):
    """变量作用域。"""
    INTERNAL = "internal"
    EXTERNAL = "external"


class ConnectionKind(str, Enum):
    """连接类型。"""
    INTEGRATED = "integrated"
    NON_INTEGRATED = "non_integrated"
    OPCUA = "opcua"
    INTERNAL = "internal"


class ScreenItemType(str, Enum):
    """画面控件类型。"""
    TEXT = "text"
    BUTTON = "button"
    IO_FIELD = "io_field"
    SYMBOLIC_IO_FIELD = "symbolic_io_field"
    INDICATOR = "indicator"
    RECTANGLE = "rectangle"
    ELLIPSE = "ellipse"
    SWITCH = "switch"
    SLIDER = "slider"
    GRAPHIC_VIEW = "graphic_view"
    SCREEN_WINDOW = "screen_window"


class BindingKind(str, Enum):
    """动态绑定类型。"""
    DIRECT_TAG = "direct_tag"
    DISCRETE = "discrete"
    RANGE = "range"
    LINEAR = "linear"
    FLASHING = "flashing"
    RESOURCE_LIST = "resource_list"
    EXPRESSION = "expression"
    SCRIPT = "script"


class SemanticEvent(str, Enum):
    """语义事件类型。"""
    CLICK = "click"
    PRESS = "press"
    RELEASE = "release"
    CHANGE = "change"
    LOADED = "loaded"
    UNLOADED = "unloaded"
    ACTIVATE = "activate"
    DEACTIVATE = "deactivate"


class SemanticActionType(str, Enum):
    """语义动作类型。"""
    SET_BIT = "set_bit"
    RESET_BIT = "reset_bit"
    TOGGLE_BIT = "toggle_bit"
    SET_VALUE = "set_value"
    INCREMENT = "increment"
    DECREMENT = "decrement"
    ACTIVATE_SCREEN = "activate_screen"
    OPEN_POPUP = "open_popup"
    CLOSE_POPUP = "close_popup"
    ACKNOWLEDGE_ALARM = "acknowledge_alarm"
    CALL_SCRIPT = "call_script"
    WRITE_EXPRESSION = "write_expression"


class ScriptLanguage(str, Enum):
    """脚本语言。"""
    SEMANTIC = "semantic"
    VBS = "vbs"
    JAVASCRIPT = "javascript"


class DiagnosticSeverity(str, Enum):
    """诊断严重等级。"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class DeploymentPhase(str, Enum):
    """部署阶段（按依赖顺序）。"""
    P00_DISCOVERY = "P00_DISCOVERY"
    P10_VALIDATE_DEPENDENCIES = "P10_VALIDATE_DEPENDENCIES"
    P20_CONNECTIONS = "P20_CONNECTIONS"
    P30_TAG_TABLES_AND_TAGS = "P30_TAG_TABLES_AND_TAGS"
    P40_SCRIPTS_AND_RESOURCES = "P40_SCRIPTS_AND_RESOURCES"
    P50_SCREENS = "P50_SCREENS"
    P60_BINDINGS_AND_EVENTS = "P60_BINDINGS_AND_EVENTS"
    P70_COMPILE = "P70_COMPILE"
    P80_VERIFY = "P80_VERIFY"
    P90_SAVE = "P90_SAVE"


class ConflictPolicy(str, Enum):
    """名称冲突策略。"""
    OVERRIDE = "override"
    RENAME = "rename"
    ERROR = "error"


class UnsupportedFeaturePolicy(str, Enum):
    """不支持功能策略。"""
    ERROR = "error"
    WARN_AND_SKIP = "warn_and_skip"
    EMULATE = "emulate"


class MissingDependencyPolicy(str, Enum):
    """缺失依赖策略。"""
    ERROR = "error"
    WARN_AND_SKIP = "warn_and_skip"

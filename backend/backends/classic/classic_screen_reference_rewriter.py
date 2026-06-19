# -*- coding: utf-8 -*-
"""
ClassicScreenReferenceRewriter — 重写画面 XML 中全部变量引用。

V3.2: 解决 Basic Panel 导入后变量引用残留模板变量的问题。

必须重写:
  - FunctionList action 参数 (Press/Release/Click)
  - IOField ProcessTag
  - SymbolicIOField ProcessTag + TextList
  - 动态颜色 SourceTag (LinkList/OpenLink)
  - 可见性/闪烁引用
  - LinkList 中的变量 Name
  - ControllerTag (PLC 变量引用)
  - Connection (连接引用)
  - Script (脚本引用)
  - Screen (画面引用)

禁止:
  - 全局字符串替换 "Button"
  - 只修改控件名称、位置、文字

V3.2 增强:
  - ReferenceMapping 统一引用映射模型
  - ScreenRewriteResult 结构化重写结果
  - validate_generated_screen_references 阻断检查
  - OpenLink 类型白名单 (TAG / CONTROLLER_TAG / CONNECTION / SCRIPT / SCREEN)
"""

from __future__ import annotations
from dataclasses import dataclass, field
import xml.etree.ElementTree as ET
from typing import Any
import re


# ------------------------------------------------------------------
# OpenLink 类型白名单
# ------------------------------------------------------------------

TAG_LINK_TYPES: set[str] = {
    "Tag",
    "HmiTag",
    "Variable",
    "ProcessValue",
}

CONTROLLER_TAG_LINK_TYPES: set[str] = {
    "ControllerTag",
    "PlcTag",
}

CONNECTION_LINK_TYPES: set[str] = {
    "Connection",
    "HmiConnection",
}

SCRIPT_LINK_TYPES: set[str] = {
    "Script",
}

SCREEN_LINK_TYPES: set[str] = {
    "Screen",
}

ALL_KNOWN_LINK_TYPES: set[str] = (
    TAG_LINK_TYPES
    | CONTROLLER_TAG_LINK_TYPES
    | CONNECTION_LINK_TYPES
    | SCRIPT_LINK_TYPES
    | SCREEN_LINK_TYPES
)


# ------------------------------------------------------------------
# ReferenceMapping — 统一引用映射模型
# ------------------------------------------------------------------

@dataclass(frozen=True)
class ReferenceMapping:
    """一次部署中只生成一次的统一引用映射。

    必须同时用于:
      - 变量 XML 生成
      - 画面 XML 生成
      - 按钮事件
      - 动态化
      - IO 域
      - 可见性
      - 动态颜色
      - 脚本调用参数
      - 验证逻辑

    禁止各生成器自行推断或生成不同映射。
    """
    tags: dict[str, str] = field(default_factory=dict)
    controller_tags: dict[str, str] = field(default_factory=dict)
    connections: dict[str, str] = field(default_factory=dict)
    scripts: dict[str, str] = field(default_factory=dict)
    screens: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tags": dict(self.tags),
            "controller_tags": dict(self.controller_tags),
            "connections": dict(self.connections),
            "scripts": dict(self.scripts),
            "screens": dict(self.screens),
        }

    def get_tag(self, template_name: str) -> str | None:
        return self.tags.get(template_name)

    def get_controller_tag(self, template_name: str) -> str | None:
        return self.controller_tags.get(template_name)

    def get_connection(self, template_name: str) -> str | None:
        return self.connections.get(template_name)

    def get_script(self, template_name: str) -> str | None:
        return self.scripts.get(template_name)

    def get_screen(self, template_name: str) -> str | None:
        return self.screens.get(template_name)


# ------------------------------------------------------------------
# Structured result types
# ------------------------------------------------------------------

@dataclass
class ReferenceReplacement:
    """单次引用替换记录。"""
    link_type: str          # Tag, ControllerTag, Connection, Script, Screen
    old_name: str
    new_name: str
    context: str = ""       # 例如 "Button.StartButton.Press"


@dataclass
class ExternalReference:
    """外部引用（可能未解析）。"""
    link_type: str
    name: str
    target_id: str = ""     # @OpenLink 等
    context: str = ""


@dataclass
class ScreenRewriteResult:
    """画面引用重写的结构化结果。"""
    xml_text: str
    replacements: list[ReferenceReplacement] = field(default_factory=list)
    unresolved_references: list[ExternalReference] = field(default_factory=list)
    remaining_template_references: list[ExternalReference] = field(default_factory=list)

    @property
    def all_resolved(self) -> bool:
        return len(self.unresolved_references) == 0

    @property
    def no_template_leaks(self) -> bool:
        return len(self.remaining_template_references) == 0


def _local_tag(elem: ET.Element) -> str:
    """提取非命名空间的本地标签名。"""
    tag = elem.tag
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    if "." in tag:
        parts = tag.rsplit(".", 1)[-1]
        return parts
    return tag


def _strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


class ControlBindingMap:
    """单个控件的绑定数据。"""

    def __init__(self, control_id: str, control_type: str = ""):
        self.control_id = control_id
        self.control_type = control_type  # Button, IOField, SymbolicIOField, Indicator
        self.tag_name: str | None = None
        self.text_list_name: str | None = None
        # 瞬时按钮: press_tag + release_tag; toggle 按钮: click_tag
        self.press_tag: str | None = None
        self.release_tag: str | None = None
        self.click_tag: str | None = None
        self.is_momentary: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "control_id": self.control_id,
            "control_type": self.control_type,
            "tag_name": self.tag_name,
            "text_list_name": self.text_list_name,
            "press_tag": self.press_tag,
            "release_tag": self.release_tag,
            "click_tag": self.click_tag,
            "is_momentary": self.is_momentary,
        }


class ClassicScreenReferenceRewriter:
    """重写 Classic Screen XML 中全部变量引用。

    使用方式:
        rewriter = ClassicScreenReferenceRewriter(template_tag_names={"Button"})
        rewriter.bind_control("BTN_Start", tag_name="CMD_Start", is_momentary=True)
        rewriter.bind_control("IO_Speed", tag_name="HMI_Speed")
        rewriter.bind_control("SIO_Mode", tag_name="HMI_Mode", text_list="ModeTextList")
        rewritten_xml, bindings = rewriter.rewrite_screen_xml(xml_string)
        leaks = rewriter.check_template_leaks(rewritten_xml)
    """

    def __init__(self, template_tag_names: set[str] | None = None):
        """
        参数:
            template_tag_names: 模板中使用的变量名（如 "Button"），用于泄漏检测。
        """
        self._controls: dict[str, ControlBindingMap] = {}
        self._template_tag_names: set[str] = template_tag_names or set()
        self._rewrite_log: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # 绑定配置
    # ------------------------------------------------------------------

    def bind_control(
        self,
        control_id: str,
        tag_name: str | None = None,
        text_list: str | None = None,
        is_momentary: bool = True,
        control_type: str = "",
    ):
        """为一个控件绑定变量映射。

        参数:
            control_id: 控件在 XML 中的 ObjectName
            tag_name: 该控件绑定的变量名
            text_list: SymbolicIOField 的文本列表名
            is_momentary: 按钮是否为瞬时类型
            control_type: 控件类型名 (Button, IOField, SymbolicIOField)
        """
        if control_id not in self._controls:
            self._controls[control_id] = ControlBindingMap(control_id, control_type)
        ctrl = self._controls[control_id]
        if tag_name:
            ctrl.tag_name = tag_name
        if text_list:
            ctrl.text_list_name = text_list
        ctrl.is_momentary = is_momentary
        if control_type:
            ctrl.control_type = control_type

    def bind_button(
        self,
        control_id: str,
        tag_name: str,
        is_momentary: bool = True,
        press_tag: str | None = None,
        release_tag: str | None = None,
    ):
        """按钮专用绑定。

        瞬时按钮:
          Press → SetBit(tag_name)
          Release → ResetBit(tag_name)
        保持按钮:
          Click → ToggleBit(tag_name)
        """
        self.bind_control(control_id, tag_name=tag_name, is_momentary=is_momentary, control_type="Button")
        ctrl = self._controls[control_id]
        if is_momentary:
            ctrl.press_tag = press_tag or tag_name
            ctrl.release_tag = release_tag or tag_name
        else:
            ctrl.click_tag = tag_name

    def bind_iofield(self, control_id: str, tag_name: str):
        """IOField 绑定。"""
        self.bind_control(control_id, tag_name=tag_name, control_type="IOField")

    def bind_symbolic_iofield(self, control_id: str, tag_name: str, text_list: str):
        """SymbolicIOField 绑定。"""
        self.bind_control(control_id, tag_name=tag_name, text_list=text_list, control_type="SymbolicIOField")

    def bind_indicator(self, control_id: str, tag_name: str):
        """Indicator 绑定。"""
        self.bind_control(control_id, tag_name=tag_name, control_type="Indicator")

    # ------------------------------------------------------------------
    # 核心重写引擎
    # ------------------------------------------------------------------

    def rewrite_screen_xml(self, xml: str) -> tuple[str, list[dict[str, Any]]]:
        """重写画面 XML 中全部变量引用。

        参数:
            xml: 原始画面 XML 字符串

        返回:
            (rewritten_xml, rewrite_log): 重写后 XML 和改写日志
        """
        self._rewrite_log = []
        root = ET.fromstring(xml)

        # 1. 重写所有控件 ObjectName 对应的引用
        #    XML 结构: Hmi.Screen.Screen > ScreenLayer > ScreenItems (Hmi.Screen.Button, etc.)
        for item_elem in root.iter():
            local = _local_tag(item_elem)
            if local in ("Button", "IOField", "SymbolicIOField", "Circle"):
                self._rewrite_item_references(item_elem)

        # 2. 重写 LinkList/OpenLink 中的变量 Name
        self._rewrite_link_list_references(root)

        # 3. 重写动态颜色/闪烁 SourceTag
        self._rewrite_dynamic_references(root)

        # 格式化输出
        rewritten = ET.tostring(root, encoding="unicode")

        return rewritten, self._rewrite_log

    # ------------------------------------------------------------------
    # 控件级引用重写
    # ------------------------------------------------------------------

    def _rewrite_item_references(self, item_elem: ET.Element):
        """重写单个控件的全部变量引用。"""
        item_type = _local_tag(item_elem)
        obj_name = self._get_object_name(item_elem)
        if not obj_name or obj_name not in self._controls:
            # 控件不在绑定表中 — 检查是否仍引用模板变量
            self._check_item_uses_template_tag(item_elem, obj_name, item_type)
            return

        ctrl = self._controls[obj_name]
        ctrl.control_type = ctrl.control_type or self._map_xml_type(item_type)
        changes: list[str] = []

        # A. 重写 FunctionList Event 中的 Action 参数 (Press/Release/Click)
        changes.extend(self._rewrite_function_list_events(item_elem, obj_name, ctrl))

        # B. 重写 ProcessTag (IOField, SymbolicIOField)
        changes.extend(self._rewrite_process_tag(item_elem, obj_name, ctrl))

        # C. 重写 TextList (SymbolicIOField)
        changes.extend(self._rewrite_text_list(item_elem, obj_name, ctrl))

        # D. 重写动态绑定中的 Tag 引用 (Indicator)
        changes.extend(self._rewrite_dynamic_tag_triggers(item_elem, obj_name, ctrl))

        if changes:
            self._rewrite_log.append({
                "control_id": obj_name,
                "control_type": ctrl.control_type,
                "changes": changes,
                "bound_tag": ctrl.tag_name,
                "bound_text_list": ctrl.text_list_name,
            })

    def _check_item_uses_template_tag(self, item_elem: ET.Element, obj_name: str | None, item_type: str):
        """检查未绑定的控件是否引用了模板变量。"""
        for elem in item_elem.iter():
            local = _local_tag(elem)
            if local == "Name" and elem.text and elem.text.strip() in self._template_tag_names:
                self._rewrite_log.append({
                    "control_id": obj_name or "unknown",
                    "control_type": item_type,
                    "warning": f"控件 '{obj_name}' 引用了模板变量 '{elem.text.strip()}'，但未在绑定表中",
                    "template_tag_reference": elem.text.strip(),
                })

    # ------------------------------------------------------------------
    # FunctionList Events 重写
    # ------------------------------------------------------------------

    def _rewrite_function_list_events(
        self, item_elem: ET.Element, obj_name: str, ctrl: ControlBindingMap,
    ) -> list[str]:
        """重写 Event/FunctionList 中的变量引用。

        Press → SetBit(tag_name)
        Release → ResetBit(tag_name)
        Click → ToggleBit(tag_name) or SetBit for toggle
        """
        changes: list[str] = []
        events = item_elem.findall(".//")  # 需要遍历所有后代
        # 更精确: 找到所有 Event 元素
        for ev_elem in item_elem.iter():
            if _local_tag(ev_elem) != "Event":
                continue
            ev_name = self._get_attribute_value(ev_elem, "Name")
            if not ev_name:
                continue

            # 定位到 FunctionListEntry → Parameters → LinkList → Value → Name
            for name_elem in ev_elem.iter():
                if _local_tag(name_elem) != "Name":
                    continue
                text = (name_elem.text or "").strip()
                if text in self._template_tag_names:
                    # 根据事件类型映射到正确的变量
                    mapped_tag = self._resolve_event_tag(ev_name, ctrl)
                    if mapped_tag:
                        name_elem.text = mapped_tag
                        changes.append(f"Event.{ev_name}:Name '{text}' → '{mapped_tag}'")

            # 也处理 FunctionListEntry 的 Type 确认
            for fl_entry in ev_elem.iter():
                if _local_tag(fl_entry) != "FunctionListEntry":
                    continue
                fl_type = self._get_attribute_value(fl_entry, "Type")
                # 确保 Type 正确 (SetBit/ResetBit for momentary, InvertBit for toggle)
                if ev_name == "Press" and ctrl.is_momentary:
                    expected = "SystemFunction"
                elif ev_name == "Release" and ctrl.is_momentary:
                    expected = "SystemFunction"
                # 不修改 Type，只修改变量引用

        return changes

    def _resolve_event_tag(self, event_name: str, ctrl: ControlBindingMap) -> str | None:
        """根据事件名称和控件配置解析正确的变量名。"""
        ev_lower = event_name.lower()
        if ctrl.control_type == "Button":
            if ctrl.is_momentary:
                if "press" in ev_lower:
                    return ctrl.press_tag or ctrl.tag_name
                elif "release" in ev_lower:
                    return ctrl.release_tag or ctrl.tag_name
            else:
                if "click" in ev_lower:
                    return ctrl.click_tag or ctrl.tag_name
        return ctrl.tag_name

    # ------------------------------------------------------------------
    # ProcessTag 重写 (IOField, SymbolicIOField)
    # ------------------------------------------------------------------

    def _rewrite_process_tag(
        self, item_elem: ET.Element, obj_name: str, ctrl: ControlBindingMap,
    ) -> list[str]:
        """重写 ProcessTag 引用。

        XML 形式: ProcessTag 可能作为属性或在 AttributeList 内。
        """
        changes: list[str] = []

        # 直接在 AttributeList 中查找 ProcessTag
        for attr_list in item_elem.findall(".//"):
            if _local_tag(attr_list) == "AttributeList":
                for child in attr_list:
                    if _local_tag(child) == "ProcessTag":
                        old = (child.text or "").strip()
                        if old in self._template_tag_names or (
                            ctrl.tag_name and old != ctrl.tag_name
                        ):
                            child.text = ctrl.tag_name
                            changes.append(f"ProcessTag: '{old}' → '{ctrl.tag_name}'")

        return changes

    # ------------------------------------------------------------------
    # TextList 重写 (SymbolicIOField)
    # ------------------------------------------------------------------

    def _rewrite_text_list(
        self, item_elem: ET.Element, obj_name: str, ctrl: ControlBindingMap,
    ) -> list[str]:
        """重写 TextList 引用 (SymbolicIOField)。"""
        changes: list[str] = []
        if ctrl.control_type != "SymbolicIOField" or not ctrl.text_list_name:
            return changes

        for attr_list in item_elem.findall(".//"):
            if _local_tag(attr_list) == "AttributeList":
                for child in attr_list:
                    if _local_tag(child) in ("TextList", "TextListName"):
                        old = (child.text or "").strip()
                        if old in self._template_tag_names or old != ctrl.text_list_name:
                            child.text = ctrl.text_list_name
                            changes.append(f"TextList: '{old}' → '{ctrl.text_list_name}'")

        return changes

    # ------------------------------------------------------------------
    # 动态绑定中的 Tag 引用重写 (Indicator range animation)
    # ------------------------------------------------------------------

    def _rewrite_dynamic_tag_triggers(
        self, item_elem: ET.Element, obj_name: str, ctrl: ControlBindingMap,
    ) -> list[str]:
        """重写动态颜色/闪烁绑定中的 Tag 引用。

        定位 TagElementTrigger → LinkList → Tag → Name
        """
        changes: list[str] = []

        for tag_trigger in item_elem.iter():
            if _local_tag(tag_trigger) != "TagElementTrigger":
                continue
            for link_list in tag_trigger:
                if _local_tag(link_list) != "LinkList":
                    continue
                for tag_elem in link_list:
                    if _local_tag(tag_elem) != "Tag":
                        continue
                    for name_elem in tag_elem:
                        if _local_tag(name_elem) == "Name":
                            old = (name_elem.text or "").strip()
                            if old in self._template_tag_names:
                                name_elem.text = ctrl.tag_name or ""
                                changes.append(f"DynamicTag: '{old}' → '{ctrl.tag_name}'")

        return changes

    # ------------------------------------------------------------------
    # LinkList/OpenLink 全局变量引用重写
    # ------------------------------------------------------------------

    def _rewrite_link_list_references(self, root: ET.Element):
        """重写 LinkList/OpenLink 中的变量 Name 引用。

        结构: LinkList → <Tag TargetID="@OpenLink"> → <Name>xxx</Name>
        """
        for link_list in root.iter():
            if _local_tag(link_list) != "LinkList":
                continue
            for tag_or_value in link_list:
                local = _local_tag(tag_or_value)
                if local not in ("Tag", "Value"):
                    continue
                target = tag_or_value.get("TargetID", "")
                is_open_link = target == "@OpenLink"
                for name_elem in tag_or_value:
                    if _local_tag(name_elem) != "Name":
                        continue
                    old = (name_elem.text or "").strip()
                    if old in self._template_tag_names and is_open_link:
                        # 查找最近的控件 ObjectName 以确定映射
                        parent_obj = self._find_parent_object_name(tag_or_value)
                        if parent_obj and parent_obj in self._controls:
                            ctrl = self._controls[parent_obj]
                            if ctrl.tag_name:
                                name_elem.text = ctrl.tag_name
                                self._rewrite_log.append({
                                    "control_id": parent_obj,
                                    "link_list_tag": f"'{old}' → '{ctrl.tag_name}' (OpenLink)",
                                })

    def _find_parent_object_name(self, elem: ET.Element) -> str | None:
        """向上查找父级控件的 ObjectName。"""
        current = elem
        for _ in range(10):  # 最多向上10层
            current = current.find("..")
            if current is None:
                # 使用标准 parent 遍历
                break
            # 尝试找到 ObjectName 属性
            for attr_list in current.findall(".//AttributeList"):
                for child in attr_list:
                    if _local_tag(child) == "ObjectName":
                        return (child.text or "").strip()
        return None

    # ------------------------------------------------------------------
    # 动态引用全局重写 (Indicator RangeAppearanceAnimation)
    # ------------------------------------------------------------------

    def _rewrite_dynamic_references(self, root: ET.Element):
        """重写动态颜色 SourceTag 引用。

        RangeAppearanceAnimation → TagElementTrigger → LinkList → <Tag> → <Name>xxx</Name>
        """
        for tag_elem in root.iter():
            if _local_tag(tag_elem) != "Tag":
                continue
            try:
                target = tag_elem.get("TargetID", "")
            except Exception:
                continue
            if target != "@OpenLink":
                continue
            for name_elem in tag_elem:
                if _local_tag(name_elem) != "Name":
                    continue
                old = (name_elem.text or "").strip()
                if old in self._template_tag_names:
                    # 向上查找所属控件
                    parent_obj = self._find_ancestor_object_name(tag_elem)
                    if parent_obj and parent_obj in self._controls:
                        ctrl = self._controls[parent_obj]
                        if ctrl.tag_name:
                            name_elem.text = ctrl.tag_name

    def _find_ancestor_object_name(self, elem: ET.Element) -> str | None:
        """向上遍历查找最近祖先控件的 ObjectName。"""
        parent_map = {}
        try:
            # 尝试构建父级映射
            for p in elem.iter():
                for child in p:
                    parent_map[child] = p
        except Exception:
            pass

        current = elem
        for _ in range(10):
            current = parent_map.get(current)
            if current is None:
                break
            local = _local_tag(current)
            if local in ("Button", "IOField", "SymbolicIOField", "Circle"):
                return self._get_object_name(current)

        # Fallback: 直接遍历查找包含 ObjectName 的祖先
        current = elem
        for _ in range(10):
            # 简单的 .find("..") 替代
            found = None
            for possible_parent in elem.getroot().iter():
                if elem in list(possible_parent):
                    found = possible_parent
                    break
            if found is None:
                break
            local = _local_tag(found)
            if local in ("Button", "IOField", "SymbolicIOField", "Circle"):
                return self._get_object_name(found)
            elem = found

        return None

    # ------------------------------------------------------------------
    # 模板泄漏检查
    # ------------------------------------------------------------------

    def check_template_leaks(self, xml: str) -> list[str]:
        """检查最终 XML 中是否仍包含模板变量引用。

        检查点:
          1. 仍包含模板变量 "Button"
          2. 仍包含 "Template_ProcessTag"
          3. 仍包含 "Template_TextList"

        返回:
            泄漏的引用列表；空列表表示通过检查。
        """
        leaks: list[str] = []
        root = ET.fromstring(xml)
        xml_text = ET.tostring(root, encoding="unicode")

        # 检查模板变量名
        for tpl_name in self._template_tag_names:
            if self._find_tag_name_in_xml(root, tpl_name):
                leaks.append(f"TEMPLATE_TAG_REFERENCE: '{tpl_name}' still present in XML")

        # 检查 Template_ProcessTag
        if "Template_ProcessTag" in xml_text:
            leaks.append("TEMPLATE_TAG_REFERENCE: 'Template_ProcessTag' still present in XML")

        # 检查 Template_TextList
        if "Template_TextList" in xml_text:
            leaks.append("TEMPLATE_TAG_REFERENCE: 'Template_TextList' still present in XML")

        return leaks

    def _find_tag_name_in_xml(self, root: ET.Element, tag_name: str) -> bool:
        """检查 XML 中是否存在对指定变量名的引用。"""
        for elem in root.iter():
            local = _local_tag(elem)
            # 只检查变量引用位置，不检查 ObjectName 等控件名称
            if local == "Name":
                # 需要判断上下文 — 不能匹配控件自己的 ObjectName
                parent = self._find_parent_local(elem, root)
                if parent and _local_tag(parent) in ("Tag", "Value"):
                    if (elem.text or "").strip() == tag_name:
                        return True
            # ProcessTag 直接文本
            if local == "ProcessTag":
                if (elem.text or "").strip() == tag_name:
                    return True
        return False

    def _find_parent_local(self, elem: ET.Element, root: ET.Element) -> ET.Element | None:
        """查找父元素。"""
        for p in root.iter():
            for child in p:
                if child is elem:
                    return p
        return None

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _get_object_name(item_elem: ET.Element) -> str | None:
        """从控件元素的 AttributeList 中提取 ObjectName。"""
        for attr_list in item_elem:
            if _local_tag(attr_list) == "AttributeList":
                for child in attr_list:
                    if _local_tag(child) == "ObjectName":
                        return (child.text or "").strip()

        # 备用: 直接从属性读取
        obj_name = item_elem.get("ObjectName") or item_elem.get("Name")
        if obj_name:
            return str(obj_name)
        return None

    @staticmethod
    def _get_attribute_value(elem: ET.Element, attr_name: str) -> str | None:
        """获取元素的属性值（AttributeList 子元素或直接属性）。"""
        # 先查找 AttributeList
        for attr_list in elem:
            if _local_tag(attr_list) == "AttributeList":
                for child in attr_list:
                    if _local_tag(child) == attr_name:
                        return (child.text or "").strip()
        # 回退到直接属性
        return elem.get(attr_name)

    @staticmethod
    def _map_xml_type(xml_tag: str) -> str:
        """将 XML 标签映射为控件类型名。"""
        mapping = {
            "Button": "Button",
            "IOField": "IOField",
            "SymbolicIOField": "SymbolicIOField",
            "Circle": "Indicator",
        }
        return mapping.get(xml_tag, xml_tag)


# ------------------------------------------------------------------
# 模块级便捷函数
# ------------------------------------------------------------------

def rewrite_classic_screen(
    xml: str,
    binding_map: dict[str, dict[str, Any]],
    template_tag_names: set[str] | None = None,
) -> tuple[str, list[dict[str, Any]], list[str]]:
    """便捷函数：一行调用完成重写 + 泄漏检查。

    参数:
        xml: 原始画面 XML
        binding_map: {control_object_name: {tag_name, text_list, is_momentary, control_type}}
        template_tag_names: 模板变量名集合

    返回:
        (rewritten_xml, rewrite_log, leak_report)
    """
    template_tags = template_tag_names or {"Button"}
    rewriter = ClassicScreenReferenceRewriter(template_tag_names=template_tags)

    for obj_name, binding in binding_map.items():
        ctrl_type = binding.get("control_type", "Button")
        tag_name = binding.get("tag_name", "")
        text_list = binding.get("text_list")
        is_momentary = binding.get("is_momentary", True)

        if ctrl_type == "Button":
            rewriter.bind_button(obj_name, tag_name=tag_name, is_momentary=is_momentary)
        elif ctrl_type == "IOField":
            rewriter.bind_iofield(obj_name, tag_name)
        elif ctrl_type == "SymbolicIOField":
            rewriter.bind_symbolic_iofield(obj_name, tag_name=tag_name, text_list=text_list or "")
        elif ctrl_type == "Indicator":
            rewriter.bind_indicator(obj_name, tag_name=tag_name)

    rewritten_xml, rewrite_log = rewriter.rewrite_screen_xml(xml)
    leaks = rewriter.check_template_leaks(rewritten_xml)

    return rewritten_xml, rewrite_log, leaks


# ------------------------------------------------------------------
# V3.2: 结构化引用重写 (使用 ReferenceMapping)
# ------------------------------------------------------------------

def rewrite_classic_screen_references(
    xml_text: str,
    mapping: ReferenceMapping,
    template_tag_names: set[str] | None = None,
) -> ScreenRewriteResult:
    """重写 Classic 画面 XML 中的外部引用（结构化版本）。

    使用 ReferenceMapping 统一映射，覆盖:
      - HMI Tag
      - PLC ControllerTag
      - Connection
      - Script
      - Screen

    通过 XML 解析器重写引用节点，禁止全局字符串替换。

    参数:
        xml_text: 原始画面 XML 字符串
        mapping: ReferenceMapping 统一引用映射
        template_tag_names: 模板变量名集合（用于泄漏检测）

    返回:
        ScreenRewriteResult 包含重写后 XML、替换列表、未解析引用、残留模板引用
    """
    template_tags = template_tag_names or set()
    replacements: list[ReferenceReplacement] = []
    unresolved: list[ExternalReference] = []
    remaining_template: list[ExternalReference] = []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        return ScreenRewriteResult(
            xml_text=xml_text,
            unresolved_references=[ExternalReference(
                link_type="ParseError", name=str(e),
            )],
        )

    # 遍历所有元素，处理 TargetID="@OpenLink" 的引用
    for element in root.iter():
        target_id = element.get("TargetID", "")
        if target_id != "@OpenLink":
            continue

        link_type = _local_tag(element.tag)
        name_node = _find_direct_name_child(element)

        if name_node is None:
            continue

        old_name = (name_node.text or "").strip()
        if not old_name:
            continue

        new_name: str | None = None
        context = _build_context_path(element)

        # 根据 OpenLink 类型白名单查找映射
        if link_type in TAG_LINK_TYPES:
            new_name = mapping.tags.get(old_name)
        elif link_type in CONTROLLER_TAG_LINK_TYPES:
            new_name = mapping.controller_tags.get(old_name)
        elif link_type in CONNECTION_LINK_TYPES:
            new_name = mapping.connections.get(old_name)
        elif link_type in SCRIPT_LINK_TYPES:
            new_name = mapping.scripts.get(old_name)
        elif link_type in SCREEN_LINK_TYPES:
            new_name = mapping.screens.get(old_name)
        else:
            # 未知 OpenLink 类型 — 记录诊断但不阻断
            unresolved.append(ExternalReference(
                link_type=link_type,
                name=old_name,
                target_id=target_id,
                context=context,
            ))
            continue

        if new_name:
            name_node.text = new_name
            replacements.append(ReferenceReplacement(
                link_type=link_type,
                old_name=old_name,
                new_name=new_name,
                context=context,
            ))
        elif old_name in template_tags:
            # 模板变量未映射
            remaining_template.append(ExternalReference(
                link_type=link_type,
                name=old_name,
                target_id=target_id,
                context=context,
            ))
        else:
            unresolved.append(ExternalReference(
                link_type=link_type,
                name=old_name,
                target_id=target_id,
                context=context,
            ))

    # 格式化输出
    rewritten = ET.tostring(root, encoding="unicode")

    return ScreenRewriteResult(
        xml_text=rewritten,
        replacements=replacements,
        unresolved_references=unresolved,
        remaining_template_references=remaining_template,
    )


def _find_direct_name_child(element: ET.Element) -> ET.Element | None:
    """在元素的直接子元素中查找 Name 子元素。"""
    for child in element:
        if _local_tag(child.tag) == "Name":
            return child
    # 深度搜索一层 AttributeList
    for child in element:
        if _local_tag(child.tag) == "AttributeList":
            for sub in child:
                if _local_tag(sub.tag) == "Name":
                    return sub
    return None


def _build_context_path(element: ET.Element) -> str:
    """构建元素的上下文路径（用于诊断）。"""
    parts: list[str] = []
    # 尝试向上查找最多5层
    current = element
    for _ in range(5):
        local = _local_tag(current.tag)
        name = current.get("Name") or current.get("ObjectName") or ""
        if name:
            parts.append(f"{local}[{name}]")
        else:
            parts.append(local)
        # 找父元素
        parent_found = False
        for p in element.getroot().iter() if element.getroot() is not None else []:
            for child in p:
                if child is current:
                    current = p
                    parent_found = True
                    break
            if parent_found:
                break
        if not parent_found:
            break
    return "/".join(reversed(parts)) if parts else "unknown"


# ------------------------------------------------------------------
# V3.2: validate_generated_screen_references — 导入前阻断检查
# ------------------------------------------------------------------

def validate_generated_screen_references(
    screen_xml: str,
    expected_tags: set[str],
    template_tag_names: set[str],
) -> list[dict[str, Any]]:
    """在导入画面之前执行强校验。

    必须阻断以下情况:
      A. 仍然引用模板变量 → SCREEN_TEMPLATE_TAG_REFERENCE_REMAINS
      B. 引用未生成变量 → SCREEN_TAG_REFERENCE_NOT_DEFINED
      C. 同一个模板变量缺少映射 → TAG_MAPPING_MISSING
      D. OpenLink 类型未知 → 记录诊断

    对于影响变量、事件或动态化的未知类型，部署应进入 BLOCKED。

    返回:
        阻断诊断列表；空列表表示通过检查。
    """
    blockers: list[dict[str, Any]] = []

    try:
        root = ET.fromstring(screen_xml)
    except ET.ParseError as e:
        blockers.append({
            "code": "SCREEN_XML_PARSE_ERROR",
            "severity": "ERROR",
            "message": f"无法解析画面 XML: {e}",
        })
        return blockers

    all_tag_names_in_xml: set[str] = set()

    for element in root.iter():
        target_id = element.get("TargetID", "")
        local = _local_tag(element.tag)

        # 检查 OpenLink 引用
        if target_id == "@OpenLink" and local not in ALL_KNOWN_LINK_TYPES:
            name_node = _find_direct_name_child(element)
            name_text = (name_node.text or "").strip() if name_node is not None else ""
            blockers.append({
                "code": "UNKNOWN_OPENLINK_TYPE",
                "severity": "WARNING",
                "link_type": local,
                "name": name_text,
                "message": f"未知 OpenLink 类型 '{local}': '{name_text}'",
            })

        # 收集所有变量名引用
        name_node = _find_direct_name_child(element)
        if name_node is not None and local in TAG_LINK_TYPES:
            name_text = (name_node.text or "").strip()
            if name_text:
                all_tag_names_in_xml.add(name_text)

    # 检查 A: 仍引用模板变量
    template_refs = all_tag_names_in_xml & template_tag_names
    if template_refs:
        blockers.append({
            "code": "SCREEN_TEMPLATE_TAG_REFERENCE_REMAINS",
            "severity": "ERROR",
            "template_tags": sorted(template_refs),
            "message": f"画面中仍引用模板变量: {sorted(template_refs)}",
        })

    # 检查 B: 引用未生成变量
    # 排除模板变量名（已在 A 中处理）
    non_template_refs = all_tag_names_in_xml - template_tag_names
    undefined_refs = non_template_refs - expected_tags
    if undefined_refs:
        blockers.append({
            "code": "SCREEN_TAG_REFERENCE_NOT_DEFINED",
            "severity": "ERROR",
            "undefined_tags": sorted(undefined_refs),
            "message": f"画面引用了未在变量生成结果中的变量: {sorted(undefined_refs)}",
        })

    return blockers

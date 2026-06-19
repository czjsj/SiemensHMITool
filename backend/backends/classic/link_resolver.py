# -*- coding: utf-8 -*-
"""LinkResolver — XML 内变量/脚本/画面/文本列表引用重写。

方案文档 §13.2 对齐。
"""
from __future__ import annotations
import xml.etree.ElementTree as ET


def _local_tag(elem: ET.Element) -> str:
    tag = elem.tag
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    if "." in tag:
        return tag.rsplit(".", 1)[-1]
    return tag


class LinkResolver:
    """HMI XML 内部引用重写器。

    负责替换 ProcessTag/ControllerTag/Script/VBSFunction 等引用，
    确保导入后 TIA 可解析。
    """

    def __init__(self):
        self._tag_map: dict[str, str] = {}
        self._script_map: dict[str, str] = {}
        self._screen_map: dict[str, str] = {}
        self._text_list_map: dict[str, str] = {}

    def bind_tag(self, logical_name: str, actual_name: str):
        self._tag_map[logical_name] = actual_name

    def bind_script(self, logical_name: str, actual_name: str):
        self._script_map[logical_name] = actual_name

    def bind_screen(self, logical_name: str, actual_name: str):
        self._screen_map[logical_name] = actual_name

    def bind_text_list(self, logical_name: str, actual_name: str):
        self._text_list_map[logical_name] = actual_name

    def resolve_node(self, node: ET.Element) -> int:
        """遍历子树，替换所有已知引用。返回修改数量。"""
        count = 0

        tag_refs = {"ProcessTag", "ProcessValue", "TagName", "Variable", "HmiTag", "ControllerTag"}
        for elem in node.iter():
            ctag = _local_tag(elem)
            if ctag in tag_refs and elem.text:
                old = elem.text.strip()
                if old in self._tag_map:
                    elem.text = self._tag_map[old]
                    count += 1
            if ctag == "VBSFunction" and elem.text:
                old = elem.text.strip()
                if old in self._script_map:
                    elem.text = self._script_map[old]
                    count += 1
            if ctag == "ScreenName" and elem.text:
                old = elem.text.strip()
                if old in self._screen_map:
                    elem.text = self._screen_map[old]
                    count += 1

        # Event/FunctionList 中 Action 的参数
        for elem in node.iter():
            ctag = _local_tag(elem)
            if ctag in ("TagName", "TargetTag"):
                old = (elem.text or "").strip()
                if old in self._tag_map:
                    elem.text = self._tag_map[old]
                    count += 1

        return count

    def validate_links(self, root: ET.Element, symbol_table: dict[str, set[str]]) -> list[str]:
        """验证所有引用目标存在。返回错误列表。"""
        errors: list[str] = []
        tag_refs = symbol_table.get("tags", set())
        script_refs = symbol_table.get("scripts", set())
        screen_refs = symbol_table.get("screens", set())

        for elem in root.iter():
            ctag = _local_tag(elem)
            if ctag in ("ProcessTag", "ProcessValue", "TagName", "HmiTag") and elem.text:
                ref = elem.text.strip()
                if ref and ref not in tag_refs:
                    errors.append(f"变量引用 '{ref}' 目标不存在")
            if ctag == "VBSFunction" and elem.text:
                ref = elem.text.strip()
                if ref and ref not in script_refs:
                    errors.append(f"脚本引用 '{ref}' 目标不存在")
            if ctag == "ScreenName" and elem.text:
                ref = elem.text.strip()
                if ref and ref not in screen_refs:
                    errors.append(f"画面引用 '{ref}' 目标不存在")
        return errors

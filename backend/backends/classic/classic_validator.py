# -*- coding: utf-8 -*-
"""ClassicValidator — 导入前 XML 校验。

方案文档 §13.5 对齐。
"""
from __future__ import annotations
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


def _local_tag(elem: ET.Element) -> str:
    tag = elem.tag
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    if "." in tag:
        return tag.rsplit(".", 1)[-1]
    return tag


@dataclass
class ClassicValidationResult:
    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "stats": self.stats,
        }


class ClassicValidator:
    """导入前 Classic XML 全面校验。"""

    def __init__(self):
        pass

    def validate(
        self,
        xml_content: str,
        expected_namespace: str = "",
        expected_screen_width: int | None = None,
        expected_screen_height: int | None = None,
    ) -> ClassicValidationResult:
        result = ClassicValidationResult()

        # 1. XML 可解析
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            result.valid = False
            result.errors.append(f"XML 解析失败: {e}")
            return result

        # 2. 命名空间匹配
        if expected_namespace:
            ns = ""
            if "}" in root.tag:
                ns = root.tag.split("}")[0].lstrip("{")
            if ns and ns != expected_namespace:
                result.warnings.append(f"命名空间不匹配: 期望 {expected_namespace}, 实际 {ns}")

        # 3. Screen 元素存在
        screens = [e for e in root.iter() if _local_tag(e) == "Screen"]
        if not screens:
            result.errors.append("缺少 Screen 元素")
            result.valid = False
        else:
            screen = screens[0]
            # 画面尺寸
            w = h = None
            for attr_list in screen:
                if _local_tag(attr_list) != "AttributeList":
                    continue
                for child in attr_list:
                    ctag = _local_tag(child)
                    text = (child.text or "").strip()
                    if ctag == "Width" and text.isdigit():
                        w = int(text)
                    elif ctag == "Height" and text.isdigit():
                        h = int(text)
            if expected_screen_width and w and w != expected_screen_width:
                result.warnings.append(f"Width 不匹配: {w} vs {expected_screen_width}")
            if expected_screen_height and h and h != expected_screen_height:
                result.warnings.append(f"Height 不匹配: {h} vs {expected_screen_height}")

        # 4. ID 唯一性
        ids = set()
        for elem in root.iter():
            for attr in ("ID", "Id", "id"):
                if attr in elem.attrib:
                    v = elem.attrib[attr]
                    if v in ids:
                        result.errors.append(f"重复 ID: {v}")
                        result.valid = False
                    ids.add(v)

        # 5. 控件名称唯一性
        item_names = set()
        for elem in root.iter():
            if _local_tag(elem) not in ("ScreenItem", "IOField", "Button", "SymbolicIOField", "Circle", "TextField", "Ellipse", "Rectangle"):
                continue
            name = elem.get("Name") or ""
            if not name:
                for attr_list in elem:
                    if _local_tag(attr_list) != "AttributeList":
                        continue
                    for child in attr_list:
                        if _local_tag(child) == "ObjectName":
                            name = (child.text or "").strip()
            if name:
                if name in item_names:
                    result.errors.append(f"重复控件名: {name}")
                    result.valid = False
                item_names.add(name)

        result.stats = {"screen_count": len(screens), "id_count": len(ids), "item_count": len(item_names)}
        return result

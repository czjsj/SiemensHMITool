# -*- coding: utf-8 -*-
"""
MultilingualText Builder — TIA HMI XML 导入管线第二层
=========================================================

修复重点：
- TIA V16/Comfort 导出的 HMI XML 中，ID 是元素属性：
    <MultilingualText ID="1" CompositionName="Text">
  不能生成 <ID>...</ID> 子元素，否则 Openness 会把 <ID> 当作对象元素并报：
    Cannot find the required 'ID' attribute element for the 'ID' element
- 对既有 V16 结构只更新 AttributeList/Text 文本，保留 ObjectList、
  MultilingualTextItem、CompositionName 和所有 ID 属性。
"""
import xml.etree.ElementTree as ET
from .text_normalizer import TextNormalizer


class MultilingualTextBuilder:
    """TIA Portal MultilingualText DOM 构建器。"""

    SUPPORTED_LANGUAGES = {
        "zh-CN", "en-US", "de-DE", "fr-FR", "ja-JP", "ko-KR",
        "it-IT", "es-ES", "ru-RU", "pt-BR", "tr-TR",
    }

    # TIA V16/Comfort 中，画面可见文字属性通常不是纯文本，
    # 而是 <Text><body><p>...</p></body></Text> 这种富文本片段。
    # HelpText 等帮助文本仍保持纯文本。
    RICH_TEXT_COMPOSITIONS = {"Text", "TextOff", "TextOn", "Caption", "DisplayText"}

    def __init__(self, default_language: str = "zh-CN"):
        if default_language not in self.SUPPORTED_LANGUAGES:
            raise ValueError(
                f"不支持的语言 '{default_language}'。"
                f"支持的语言: {sorted(self.SUPPORTED_LANGUAGES)}"
            )
        self.default_language = default_language

    # ------------------------------------------------------------------
    # 新建通用 MultilingualText 片段（不生成 <ID> 子元素）
    # ------------------------------------------------------------------
    def build(self, text: str, language: str = None) -> ET.Element:
        """构建通用 MultilingualText 片段。

        注意：这里故意不创建 <ID> 子元素。TIA HMI 对象的 ID 应该是对象标签
        上的属性，例如 <MultilingualText ID="1" ...>，不是子节点。
        """
        lang = self._validate_language(language)
        safe_text = TextNormalizer.normalize(text)
        if not safe_text:
            safe_text = " "

        mt_elem = ET.Element("MultilingualText")
        mt_elem.text = "\n  "
        text_elem = ET.SubElement(mt_elem, "Text")
        text_elem.set("Language", lang)
        text_elem.text = safe_text
        text_elem.tail = "\n"
        return mt_elem

    def build_with_namespace(
        self, text: str, namespace_uri: str,
        language: str = None,
    ) -> ET.Element:
        """构建带命名空间的通用 MultilingualText 片段。"""
        lang = self._validate_language(language)
        safe_text = TextNormalizer.normalize(text)
        if not safe_text:
            safe_text = " "

        ns = f"{{{namespace_uri}}}" if namespace_uri else ""
        mt_elem = ET.Element(f"{ns}MultilingualText")
        mt_elem.text = "\n  "
        text_elem = ET.SubElement(mt_elem, f"{ns}Text")
        text_elem.set("Language", lang)
        text_elem.text = safe_text
        text_elem.tail = "\n"
        return mt_elem

    def build_v16(
        self,
        text: str,
        mt_id: str,
        item_id: str,
        composition_name: str = "Text",
        language: str = None,
    ) -> ET.Element:
        """构建 TIA V16/Comfort 导出风格的 MultilingualText 节点。"""
        lang = self._validate_language(language)
        safe_text = TextNormalizer.normalize(text)

        mt = ET.Element("MultilingualText", {
            "ID": str(mt_id),
            "CompositionName": str(composition_name or "Text"),
        })
        obj_list = ET.SubElement(mt, "ObjectList")
        item = ET.SubElement(obj_list, "MultilingualTextItem", {
            "ID": str(item_id),
            "CompositionName": "Items",
        })
        attr = ET.SubElement(item, "AttributeList")
        ET.SubElement(attr, "Culture").text = lang
        text_elem = ET.SubElement(attr, "Text")
        self._set_v16_text_value(
            text_elem,
            safe_text,
            rich=self._requires_rich_text(composition_name),
        )
        return mt

    # ------------------------------------------------------------------
    # 就地修复既有节点
    # ------------------------------------------------------------------
    def rebuild_element(self, mt_element: ET.Element) -> ET.Element:
        """对已有 MultilingualText 执行安全重建/清洗。

        - V16/Comfort 结构：只更新 ObjectList/MultilingualTextItem/AttributeList/Text；
          不删除 ObjectList，不添加 <ID> 子元素。
        - 通用结构：保证存在 <Text Language="...">。
        """
        text_content = self._extract_text(mt_element)
        safe_text = TextNormalizer.normalize(text_content)

        # 先删除以前错误版本可能插入的 <ID> 子元素。
        self._remove_direct_id_children(mt_element)

        # TIA V16/Comfort：<MultilingualText ID="..." CompositionName="...">
        #                 <ObjectList><MultilingualTextItem ...><AttributeList>...
        v16_text_nodes = self._find_v16_text_nodes(mt_element)
        if v16_text_nodes:
            rich = self._requires_rich_text(mt_element.get("CompositionName"))
            for text_node in v16_text_nodes:
                self._set_v16_text_value(text_node, safe_text, rich=rich)
            self._ensure_v16_culture(mt_element, self.default_language)
            return mt_element

        # 通用结构：<MultilingualText><Text Language="zh-CN">...</Text></MultilingualText>
        direct_text = self._find_direct_child(mt_element, "Text")
        if direct_text is not None:
            direct_text.set("Language", direct_text.get("Language") or self.default_language)
            self._clear_children(direct_text)
            direct_text.text = safe_text or " "
            # 移除其它非 Text 直接子元素，避免再次产生 <ID> 子元素。
            for child in list(mt_element):
                if child is not direct_text and self._local_tag(child) != "Text":
                    mt_element.remove(child)
            return mt_element

        # 兜底：如果这个节点本身带 TIA 对象属性，则按 V16 结构补 ObjectList；
        # 否则按通用结构补 Text。不要补 <ID> 子元素。
        if "ID" in mt_element.attrib or "CompositionName" in mt_element.attrib:
            self._rebuild_as_v16(mt_element, safe_text)
        else:
            mt_element.text = "\n  "
            text_elem = ET.SubElement(mt_element, self._qname_like(mt_element, "Text"))
            text_elem.set("Language", self.default_language)
            text_elem.text = safe_text or " "
            text_elem.tail = "\n"
        return mt_element

    # ------------------------------------------------------------------
    # 静态便捷方法
    # ------------------------------------------------------------------
    @staticmethod
    def build_string(text: str, language: str = "zh-CN") -> str:
        builder = MultilingualTextBuilder(default_language=language)
        return ET.tostring(builder.build(text, language), encoding="unicode")

    @staticmethod
    def validate_element(mt_element: ET.Element) -> list:
        """验证 MultilingualText，兼容通用结构和 TIA V16/Comfort 结构。"""
        errors = []

        for child in mt_element:
            if MultilingualTextBuilder._local_tag(child) == "ID":
                errors.append("MultilingualText 不允许包含 <ID> 子元素；ID 应为元素属性")

        # V16 结构：AttributeList/Culture + AttributeList/Text
        v16_texts = MultilingualTextBuilder._find_v16_text_nodes_static(mt_element)
        if v16_texts:
            rich = MultilingualTextBuilder._requires_rich_text_static(
                mt_element.get("CompositionName")
            )
            for text_node in v16_texts:
                child_text = "".join(text_node.itertext()).strip()
                if child_text and TextNormalizer.normalize(child_text) != child_text:
                    errors.append("V16 Text 内容未经清洗，包含 HTML 标签或非法字符")
                if rich and not MultilingualTextBuilder._has_rich_body_p(text_node):
                    errors.append("V16 可见文本需要 <body><p>...</p></body> 富文本结构")
            return errors

        # 通用结构：直接 Text 子节点 + Language
        direct_text = None
        for child in mt_element:
            if MultilingualTextBuilder._local_tag(child) == "Text":
                direct_text = child
                break
        if direct_text is not None:
            if "Language" not in direct_text.attrib:
                errors.append("Text 子节点缺少 Language 属性")
            child_text = (direct_text.text or "").strip()
            if not child_text:
                errors.append("Text 子节点内容为空")
            if child_text and TextNormalizer.normalize(child_text) != child_text:
                errors.append("Text 内容未经清洗，包含 HTML 标签或非法字符")
            return errors

        errors.append("MultilingualText 缺少可识别的 Text 结构")
        return errors

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _validate_language(self, language: str = None) -> str:
        lang = language or self.default_language
        if lang not in self.SUPPORTED_LANGUAGES:
            raise ValueError(f"不支持的语言 '{lang}'。支持: {sorted(self.SUPPORTED_LANGUAGES)}")
        return lang

    @staticmethod
    def _local_tag(elem: ET.Element) -> str:
        tag = elem.tag
        if "}" in tag:
            return tag.rsplit("}", 1)[-1]
        if "." in tag:
            return tag.rsplit(".", 1)[-1]
        return tag

    @staticmethod
    def _qname_like(elem: ET.Element, local_name: str) -> str:
        tag = elem.tag
        if tag.startswith("{") and "}" in tag:
            return tag.split("}", 1)[0] + "}" + local_name
        return local_name

    @staticmethod
    def _clear_children(elem: ET.Element):
        for child in list(elem):
            elem.remove(child)

    @classmethod
    def _find_direct_child(cls, parent: ET.Element, local_name: str):
        for child in parent:
            if cls._local_tag(child) == local_name:
                return child
        return None

    @classmethod
    def _find_v16_text_nodes_static(cls, mt_element: ET.Element) -> list:
        result = []
        for item in mt_element.iter():
            if cls._local_tag(item) != "MultilingualTextItem":
                continue
            for attr_list in item:
                if cls._local_tag(attr_list) != "AttributeList":
                    continue
                for child in attr_list:
                    if cls._local_tag(child) == "Text":
                        result.append(child)
        return result

    def _find_v16_text_nodes(self, mt_element: ET.Element) -> list:
        return self._find_v16_text_nodes_static(mt_element)

    def _extract_text(self, mt_element: ET.Element) -> str:
        # V16 Text 节点优先，避免把 Culture 也拼进文本。
        v16_text_nodes = self._find_v16_text_nodes(mt_element)
        if v16_text_nodes:
            return " ".join("".join(node.itertext()).strip() for node in v16_text_nodes).strip()

        direct_text = self._find_direct_child(mt_element, "Text")
        if direct_text is not None:
            return "".join(direct_text.itertext()).strip()

        # 兜底时排除错误的 ID 子元素，避免 UUID 被混入可见文本。
        parts = []
        for child in mt_element.iter():
            if child is mt_element or self._local_tag(child) == "ID":
                continue
            if child.text:
                parts.append(child.text)
        return " ".join(parts).strip()

    def _remove_direct_id_children(self, mt_element: ET.Element):
        for child in list(mt_element):
            if self._local_tag(child) == "ID":
                mt_element.remove(child)

    def _ensure_v16_culture(self, mt_element: ET.Element, language: str):
        for item in mt_element.iter():
            if self._local_tag(item) != "MultilingualTextItem":
                continue
            attr_list = None
            for child in item:
                if self._local_tag(child) == "AttributeList":
                    attr_list = child
                    break
            if attr_list is None:
                attr_list = ET.SubElement(item, self._qname_like(item, "AttributeList"))
            culture = None
            for child in attr_list:
                if self._local_tag(child) == "Culture":
                    culture = child
                    break
            if culture is None:
                culture = ET.SubElement(attr_list, self._qname_like(attr_list, "Culture"))
            culture.text = culture.text or language

    def _rebuild_as_v16(self, mt_element: ET.Element, safe_text: str):
        for child in list(mt_element):
            mt_element.remove(child)
        mt_element.text = "\n  "
        obj_list = ET.SubElement(mt_element, self._qname_like(mt_element, "ObjectList"))
        obj_list.text = "\n    "

        parent_id = mt_element.get("ID") or "1"
        item_id = self._derive_child_id(parent_id)
        item = ET.SubElement(obj_list, self._qname_like(mt_element, "MultilingualTextItem"), {
            "ID": item_id,
            "CompositionName": "Items",
        })
        item.text = "\n      "
        item.tail = "\n  "
        attr = ET.SubElement(item, self._qname_like(mt_element, "AttributeList"))
        attr.text = "\n        "
        attr.tail = "\n    "
        culture = ET.SubElement(attr, self._qname_like(mt_element, "Culture"))
        culture.text = self.default_language
        culture.tail = "\n        "
        text_elem = ET.SubElement(attr, self._qname_like(mt_element, "Text"))
        self._set_v16_text_value(
            text_elem,
            safe_text,
            rich=self._requires_rich_text(mt_element.get("CompositionName")),
        )
        text_elem.tail = "\n      "
        obj_list.tail = "\n"

    @classmethod
    def _requires_rich_text(cls, composition_name: str | None) -> bool:
        return cls._requires_rich_text_static(composition_name)

    @classmethod
    def _requires_rich_text_static(cls, composition_name: str | None) -> bool:
        return (composition_name or "") in cls.RICH_TEXT_COMPOSITIONS

    @classmethod
    def _has_rich_body_p(cls, text_elem: ET.Element) -> bool:
        has_body = False
        has_p = False
        for child in text_elem.iter():
            tag = cls._local_tag(child)
            if tag == "body":
                has_body = True
            elif tag == "p":
                has_p = True
        return has_body and has_p

    @classmethod
    def _set_v16_text_value(cls, text_elem: ET.Element, safe_text: str, rich: bool = False):
        """设置 TIA V16/Comfort 的 AttributeList/Text 值。

        对 Text/TextOff/TextOn 等可见文字，TIA V16/WinCC Advanced 导出的
        格式是 <Text><body><p>文字</p></body></Text>。如果写成
        <Text>文字</Text>，Openness 会报 argument 'text' invalid format。
        """
        cls._clear_children(text_elem)
        text_elem.text = None
        if rich:
            body = ET.SubElement(text_elem, "body")
            p = ET.SubElement(body, "p")
            p.text = safe_text or " "
        else:
            text_elem.text = safe_text or None

    @staticmethod
    def _derive_child_id(parent_id: str) -> str:
        try:
            return str(int(str(parent_id), 16) + 1)
        except Exception:
            return "1"

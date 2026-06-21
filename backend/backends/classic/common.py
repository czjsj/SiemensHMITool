# -*- coding: utf-8 -*-
"""Classic HMI Common — Basic/Comfort 共享基础设施。

V3.2: 集成 ClassicScreenReferenceRewriter。
"""
from __future__ import annotations
import uuid
from backend.domain.ir_v2 import HmiProjectSpec, ScreenSpec, TagSpec
from backend.domain.enums import HmiFamily
from .tag_xml_builder import TagXmlBuilder
from .screen_xml_builder import ScreenXmlBuilder
from .function_list_builder import FunctionListBuilder
from .dynamic_xml_builder import DynamicXmlBuilder
from .xml_id_registry import XmlIdRegistry
from .link_resolver import LinkResolver
from .classic_validator import ClassicValidator
from .classic_screen_reference_rewriter import ClassicScreenReferenceRewriter


class ClassicCommon:
    """Basic 和 Comfort 共享的 Classic XML 生成基础设施。"""

    # 模板变量名 — 在 catalog manifest 中记录
    TEMPLATE_TAG_NAMES: set[str] = {"Button", "Template_ProcessTag", "Template_TextList"}

    def __init__(self, target_family: str = "comfort"):
        self.target_family = target_family
        self.tag_builder = TagXmlBuilder()
        self.screen_builder = ScreenXmlBuilder()
        self.function_list_builder = FunctionListBuilder()
        self.dynamic_builder = DynamicXmlBuilder()
        self.id_registry = XmlIdRegistry(seed=uuid.uuid4().hex[:8])
        self.link_resolver = LinkResolver()
        self.validator = ClassicValidator()
        self._allow_vbs = target_family == "comfort"

        # V3.2: 画面引用重写器
        self.screen_reference_rewriter = ClassicScreenReferenceRewriter(
            template_tag_names=self.TEMPLATE_TAG_NAMES,
        )

    @property
    def allow_vbs(self) -> bool:
        return self._allow_vbs

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------

    def build_tags_xml(self, tags: list[TagSpec], table_name: str = "DefaultTagTable") -> str:
        """生成批量导出的 Tags XML（导入 DefaultTagTable）。"""
        return self.tag_builder.build_tags_batch_export_xml(tags, table_name, output_kind="plc_blocks")

    def build_single_tag_xml(self, tag: TagSpec) -> str:
        """生成单个变量的导出 XML。"""
        return self.tag_builder.build_single_tag_export_xml(tag)

    def build_text_list_xml(
        self, list_name: str, entries: list[tuple[int, str]],
        languages: list[str] | None = None,
    ) -> str:
        """生成文本列表 XML。"""
        return self.tag_builder.build_text_list_xml(list_name, entries, languages)

    # ------------------------------------------------------------------
    # Screens
    # ------------------------------------------------------------------

    def build_screen_xml(self, screen: ScreenSpec) -> str:
        """生成画面 XML（原始，未重写引用）。"""
        return self.screen_builder.build_screen(screen)

    # ------------------------------------------------------------------
    # 画面引用重写
    # ------------------------------------------------------------------

    def rewrite_screen_references(
        self, xml: str, binding_map: dict[str, dict],
    ) -> tuple[str, list[dict], list[str]]:
        """重写画面 XML 中的全部变量引用。

        参数:
            xml: 原始画面 XML
            binding_map: {control_object_name: {tag_name, text_list, control_type, is_momentary}}

        返回:
            (rewritten_xml, rewrite_log, leak_report)
        """
        from .classic_screen_reference_rewriter import rewrite_classic_screen
        return rewrite_classic_screen(
            xml, binding_map, template_tag_names=self.TEMPLATE_TAG_NAMES,
        )

    def check_template_leaks(self, xml: str) -> list[str]:
        """检查画面 XML 中是否残留模板变量引用。"""
        return self.screen_reference_rewriter.check_template_leaks(xml)

    # ------------------------------------------------------------------
    # 校验、ID 生成
    # ------------------------------------------------------------------

    def validate_xml(self, xml: str, **kw) -> "ClassicValidationResult":
        from .classic_validator import ClassicValidationResult
        return self.validator.validate(xml, **kw)

    def generate_screen_id(self, screen_name: str) -> str:
        return self.id_registry.allocate(f"screen:{screen_name}")

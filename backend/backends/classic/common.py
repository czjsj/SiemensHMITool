# -*- coding: utf-8 -*-
"""Classic HMI Common — Basic/Comfort 共享基础设施。"""
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


class ClassicCommon:
    """Basic 和 Comfort 共享的 Classic XML 生成基础设施。"""

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

    @property
    def allow_vbs(self) -> bool:
        return self._allow_vbs

    def build_tags_xml(self, tags: list[TagSpec], table_name: str = "AI_Generated") -> str:
        return self.tag_builder.build_tags_xml(tags, table_name)

    def build_screen_xml(self, screen: ScreenSpec) -> str:
        return self.screen_builder.build_screen(screen)

    def validate_xml(self, xml: str, **kw) -> "ClassicValidationResult":
        from .classic_validator import ClassicValidationResult
        return self.validator.validate(xml, **kw)

    def generate_screen_id(self, screen_name: str) -> str:
        return self.id_registry.allocate(f"screen:{screen_name}")

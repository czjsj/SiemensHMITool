# -*- coding: utf-8 -*-
"""Classic HMI (Basic/Comfort) XML 后端基础设施。"""
from .tag_xml_builder import TagXmlBuilder
from .screen_xml_builder import ScreenXmlBuilder
from .function_list_builder import FunctionListBuilder
from .dynamic_xml_builder import DynamicXmlBuilder
from .vbs_builder import VbsBuilder
from .xml_id_registry import XmlIdRegistry
from .link_resolver import LinkResolver
from .classic_validator import ClassicValidator, ClassicValidationResult
from .xml_fragment_catalog import XmlFragmentCatalog, CatalogManifest, ManifestEntry

__all__ = [
    "TagXmlBuilder",
    "ScreenXmlBuilder",
    "FunctionListBuilder",
    "DynamicXmlBuilder",
    "VbsBuilder",
    "XmlIdRegistry",
    "LinkResolver",
    "ClassicValidator",
    "ClassicValidationResult",
    "XmlFragmentCatalog",
    "CatalogManifest",
    "ManifestEntry",
]

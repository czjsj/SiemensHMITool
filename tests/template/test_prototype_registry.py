# -*- coding: utf-8 -*-
"""
测试 PrototypeRegistry — 验证原型匹配逻辑。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.template.prototype_extractor import analyze_template_screen
from backend.template.prototype_registry import PrototypeRegistry, PrototypeNotFoundError


def _load_fixture(filename: str) -> str:
    base = os.path.join(os.path.dirname(__file__), "..", "fixtures")
    with open(os.path.join(base, filename), "r", encoding="utf-8") as f:
        return f.read()


class TestPrototypeRegistry:
    """测试原型注册表匹配逻辑。"""

    @pytest.fixture
    def registry(self):
        xml = _load_fixture("template_button_indicator.xml")
        profile = analyze_template_screen(xml)
        return PrototypeRegistry(profile)

    def test_find_button_by_template_ref(self, registry):
        """根据 template_ref 精确匹配原型。"""
        item = {"id": "btn_test", "type": "button", "template_ref": "BTN_MOMENTARY_TEMPLATE"}
        proto = registry.find_for_item(item)
        assert proto.prototype_id == "BTN_MOMENTARY_TEMPLATE"
        assert proto.item_kind == "button"

    def test_find_button_by_behavior(self, registry):
        """根据 behavior 匹配原型。"""
        item = {"id": "btn_test", "type": "button", "behavior": "toggle"}
        proto = registry.find_for_item(item)
        assert proto.item_kind == "button"
        assert proto.behavior == "toggle"

    def test_find_indicator_by_template_ref(self, registry):
        """根据 template_ref 精确匹配指示灯原型。"""
        item = {"id": "lmp_test", "type": "indicator", "template_ref": "LMP_ALARM_TEMPLATE"}
        proto = registry.find_for_item(item)
        assert proto.prototype_id == "LMP_ALARM_TEMPLATE"
        assert proto.item_kind == "indicator"

    def test_find_button_by_name_prefix(self, registry):
        """根据名称前缀匹配原型。"""
        item = {"id": "BTN_SomeButton", "type": "button"}
        proto = registry.find_for_item(item)
        assert proto.item_kind == "button"

    def test_find_indicator_by_default(self, registry):
        """找不到精确匹配时返回默认同类型原型。"""
        item = {"id": "SomeIndicator", "type": "indicator"}
        proto = registry.find_for_item(item)
        assert proto.item_kind == "indicator"

    def test_not_found_raises_error(self, registry):
        """找不到原型时抛出可读错误。"""
        item = {"id": "unknown", "type": "nonexistent"}
        with pytest.raises(PrototypeNotFoundError) as exc_info:
            registry.find_for_item(item)
        assert "unknown" in str(exc_info.value)
        assert "找不到匹配的模板原型" in str(exc_info.value)

    def test_has_prototype_for(self, registry):
        """has_prototype_for 检查原型是否存在。"""
        assert registry.has_prototype_for("button") is True
        assert registry.has_prototype_for("indicator") is True
        assert registry.has_prototype_for("button", "momentary") is True
        assert registry.has_prototype_for("nonexistent") is False

# -*- coding: utf-8 -*-
"""测试 IR V2 模板绑定字段 — 验证新增字段的存在和默认值。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from backend.domain.ir_v2 import (
    ScreenItemSpec, BindingSpec, TagSpec, GeometrySpec,
)
from backend.domain.enums import (
    ScreenItemType, ButtonBehavior, IndicatorMode,
    TagDirection, TagScope,
)


class TestScreenItemSpecTemplateFields:
    """测试 ScreenItemSpec 的 V4.0 新增字段。"""

    def test_default_template_ref_is_none(self):
        item = ScreenItemSpec(id="test", name="test", type=ScreenItemType.BUTTON)
        assert item.template_ref is None

    def test_can_set_template_ref(self):
        item = ScreenItemSpec(id="test", name="test", type=ScreenItemType.BUTTON,
                              template_ref="BTN_MOMENTARY_TEMPLATE")
        assert item.template_ref == "BTN_MOMENTARY_TEMPLATE"

    def test_default_behavior_is_none(self):
        item = ScreenItemSpec(id="test", name="test", type=ScreenItemType.BUTTON)
        assert item.behavior is None

    def test_can_set_behavior(self):
        item = ScreenItemSpec(id="test", name="test", type=ScreenItemType.BUTTON,
                              behavior=ButtonBehavior.MOMENTARY)
        assert item.behavior == ButtonBehavior.MOMENTARY

    def test_default_indicator_mode_is_none(self):
        item = ScreenItemSpec(id="test", name="test", type=ScreenItemType.INDICATOR)
        assert item.indicator_mode is None

    def test_can_set_indicator_mode(self):
        item = ScreenItemSpec(id="test", name="test", type=ScreenItemType.INDICATOR,
                              indicator_mode=IndicatorMode.BOOL_COLOR)
        assert item.indicator_mode == IndicatorMode.BOOL_COLOR

    def test_default_metadata_is_empty(self):
        item = ScreenItemSpec(id="test", name="test", type=ScreenItemType.TEXT)
        assert item.metadata == {}

    def test_metadata_supports_pending_mapping(self):
        item = ScreenItemSpec(id="test", name="test", type=ScreenItemType.BUTTON,
                              metadata={"pending_mapping": True})
        assert item.metadata["pending_mapping"] is True


class TestBindingSpecTemplateFields:
    """测试 BindingSpec 的 V4.0 新增字段。"""

    def test_default_tag_is_none(self):
        b = BindingSpec(property="value")
        assert b.tag is None

    def test_can_set_tag(self):
        b = BindingSpec(property="value", tag="BTN_Start")
        assert b.tag == "BTN_Start"

    def test_default_direction_is_read_write(self):
        b = BindingSpec(property="value")
        assert b.direction == TagDirection.READ_WRITE

    def test_can_set_direction(self):
        b = BindingSpec(property="value", direction=TagDirection.WRITE)
        assert b.direction == TagDirection.WRITE

    def test_default_connection_is_none(self):
        b = BindingSpec(property="value")
        assert b.connection is None

    def test_can_set_plc_address(self):
        b = BindingSpec(property="value", plc_address="DB10.DBX0.0")
        assert b.plc_address == "DB10.DBX0.0"


class TestTagSpecTemplateFields:
    """测试 TagSpec 的 V4.0 新增字段。"""

    def test_default_direction_is_read_write(self):
        t = TagSpec(name="test")
        assert t.direction == TagDirection.READ_WRITE

    def test_can_set_direction(self):
        t = TagSpec(name="test", direction=TagDirection.READ)
        assert t.direction == TagDirection.READ

    def test_default_metadata_is_empty(self):
        t = TagSpec(name="test")
        assert t.metadata == {}

    def test_metadata_supports_pending_mapping(self):
        t = TagSpec(name="test", metadata={"pending_mapping": True})
        assert t.metadata["pending_mapping"] is True

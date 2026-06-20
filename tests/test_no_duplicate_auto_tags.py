# -*- coding: utf-8 -*-
"""测试已有绑定的对象不会生成重复自动变量。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


class TestNoDuplicateAutoTags:
    """VariableEngine._enrich_* 方法对已有绑定的对象不应生成新变量。"""

    def test_button_with_process_tag_does_not_generate_new(self):
        """Button 已有 process_tag 时不生成新的 BTN_ 变量。"""
        from backend.variable_engine import VariableEngine
        from backend.domain.ir_v2 import ScreenItemSpec, BindingSpec, ScreenItemType, EventSpec, ActionSpec, ScreenItemType
        from backend.domain.enums import BindingKind, SemanticEvent, SemanticActionType

        engine = VariableEngine()
        item = ScreenItemSpec(
            id="BTN_Start", name="BTN_Start", type=ScreenItemType.BUTTON,
            tag_binding="Motor_Start",
        )
        existing_tags = {"Motor_Start": "exists"}
        new_tags = []

        engine._enrich_button(item, "BTN_Start", existing_tags, new_tags)

        # 应使用已有绑定，不生成新变量
        assert item.tag_binding == "Motor_Start"
        # 不应有新的 BTN_ 变量（Motor_Start 已在 existing_tags 中）
        assert len(new_tags) == 0

    def test_indicator_with_tag_binding_does_not_generate_new(self):
        """Indicator 已有 tag_binding 时不生成 STS_/LMP_ 变量。"""
        from backend.variable_engine import VariableEngine
        from backend.domain.ir_v2 import ScreenItemSpec, BindingSpec, ScreenItemType

        engine = VariableEngine()
        item = ScreenItemSpec(
            id="IND_Run", name="IND_Run", type=ScreenItemType.INDICATOR,
            tag_binding="Run_Status",
        )
        existing_tags = {"Run_Status": "exists"}
        new_tags = []

        engine._enrich_indicator(item, "IND_Run", existing_tags, new_tags)

        assert item.tag_binding == "Run_Status"
        assert len(new_tags) == 0

    def test_iofield_with_binding_source_tag(self):
        """IOField 已有 binding.source_tag 时不生成新 IO_ 变量。"""
        from backend.variable_engine import VariableEngine
        from backend.domain.ir_v2 import ScreenItemSpec, BindingSpec, ScreenItemType
        from backend.domain.enums import BindingKind

        engine = VariableEngine()
        item = ScreenItemSpec(
            id="IO_Level", name="IO_Level", type=ScreenItemType.IO_FIELD,
            bindings=[
                BindingSpec(
                    property="value",
                    kind=BindingKind.DIRECT_TAG,
                    source_tag="Tank_Level",  # 已有 source_tag
                ),
            ],
        )
        existing_tags = {"Tank_Level": "exists"}
        new_tags = []

        engine._enrich_iofield(item, "IO_Level", existing_tags, new_tags)

        assert item.tag_binding == "Tank_Level"
        assert len(new_tags) == 0

    def test_button_with_event_tag_reference(self):
        """Button 已有事件引用 tag 时不重复生成。"""
        from backend.variable_engine import VariableEngine
        from backend.domain.ir_v2 import ScreenItemSpec, EventSpec, ActionSpec, ScreenItemType
        from backend.domain.enums import SemanticEvent, SemanticActionType

        engine = VariableEngine()
        item = ScreenItemSpec(
            id="BTN_Reset", name="BTN_Reset", type=ScreenItemType.BUTTON,
            events=[
                EventSpec(
                    event=SemanticEvent.CLICK,
                    actions=[
                        ActionSpec(
                            type=SemanticActionType.SET_BIT,
                            tag="Reset_Tag",  # 已有 tag 引用
                        ),
                    ],
                ),
            ],
        )
        existing_tags = {"Reset_Tag": "exists"}
        new_tags = []

        engine._enrich_button(item, "BTN_Reset", existing_tags, new_tags)

        # 应使用 Reset_Tag，不生成新的 BTN_Reset 变量
        assert item.tag_binding == "Reset_Tag"
        assert len(new_tags) == 0

    def test_mixed_scenario_bound_and_unbound(self):
        """混合场景：有绑定的对象不生成，无绑定的对象正常生成。"""
        from backend.variable_engine import VariableEngine
        from backend.domain.ir_v2 import ScreenItemSpec, BindingSpec, ScreenItemType
        from backend.domain.enums import BindingKind
        from backend.domain.ir_v2 import TagSpec, ScreenItemSpec, ScreenItemType

        engine = VariableEngine()

        # 有绑定的按钮
        bound_item = ScreenItemSpec(
            id="BTN_1", name="BTN_1", type=ScreenItemType.BUTTON,
            tag_binding="PLC_Start",
        )
        # 无绑定的按钮
        unbound_item = ScreenItemSpec(
            id="BTN_2", name="BTN_2", type=ScreenItemType.BUTTON,
        )

        existing_tags = {"PLC_Start": TagSpec(name="PLC_Start", table="DefaultTagTable", data_type="Bool")}
        new_tags = []

        engine._enrich_button(bound_item, "BTN_1", existing_tags, new_tags)
        assert bound_item.tag_binding == "PLC_Start"
        assert len(new_tags) == 0  # 没有新增

        engine._enrich_button(unbound_item, "BTN_2", existing_tags, new_tags)
        assert unbound_item.tag_binding is not None
        # 无绑定的按钮应生成新变量
        assert len(new_tags) == 1, f"Expected 1 new tag, got: {len(new_tags)}"
        assert new_tags[0].name == "BTN_2"

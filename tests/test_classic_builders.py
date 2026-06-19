# -*- coding: utf-8 -*-
"""测试 Classic XML Builders (PR-06+07): TagXmlBuilder, ScreenXmlBuilder, FunctionListBuilder, DynamicXmlBuilder, VbsBuilder."""
import sys, os, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.domain.ir_v2 import TagSpec, ScreenSpec, ScreenItemSpec, GeometrySpec, EventSpec, ActionSpec, BindingSpec, ScriptSpec
from backend.domain.enums import ScreenItemType, TagScope, BindingKind, SemanticEvent, SemanticActionType, HmiFamily
from backend.backends.classic.tag_xml_builder import TagXmlBuilder
from backend.backends.classic.screen_xml_builder import ScreenXmlBuilder
from backend.backends.classic.function_list_builder import FunctionListBuilder
from backend.backends.classic.dynamic_xml_builder import DynamicXmlBuilder
from backend.backends.classic.vbs_builder import VbsBuilder
from backend.backends.classic.common import ClassicCommon


class TestTagXmlBuilder:
    def test_build_internal_tag(self):
        tag = TagSpec(name="MyBool", data_type="Bool", scope=TagScope.INTERNAL)
        xml = TagXmlBuilder().build_internal_tag(tag)
        assert "MyBool" in xml
        assert "Bool" in xml

    def test_build_external_tag_with_controller(self):
        tag = TagSpec(name="Motor_Start", data_type="Bool", scope=TagScope.EXTERNAL, connection="PLC_1", controller_tag="DB1.Motor.Start")
        xml = TagXmlBuilder().build_external_tag(tag)
        assert "Motor_Start" in xml
        assert "DB1.Motor.Start" in xml

    def test_build_external_tag_with_address(self):
        tag = TagSpec(name="Speed", data_type="Real", scope=TagScope.EXTERNAL, address="DB1.Speed")
        xml = TagXmlBuilder().build_external_tag(tag)
        assert "Speed" in xml
        assert "DB1.Speed" in xml

    def test_build_tags_xml(self):
        tags = [
            TagSpec(name="T1", data_type="Bool", scope=TagScope.INTERNAL),
            TagSpec(name="T2", data_type="Real", scope=TagScope.EXTERNAL, address="M1.0"),
        ]
        xml = TagXmlBuilder().build_tags_xml(tags)
        assert "T1" in xml
        assert "T2" in xml


class TestScreenXmlBuilder:
    def test_build_screen_header(self):
        screen = ScreenSpec(name="MotorControl", width=800, height=480)
        xml = ScreenXmlBuilder().build_screen_header(screen)
        assert "MotorControl" in xml
        assert "800" in xml
        assert "480" in xml

    def test_build_button_item(self):
        item = ScreenItemSpec(id="BTN_Start", name="Start", type=ScreenItemType.BUTTON,
                              geometry=GeometrySpec(x=100, y=200, width=120, height=50),
                              tag_binding="Motor_Start", text={"zh-CN": "启动"})
        xml = ScreenXmlBuilder().build_screen_item(item)
        assert "BTN_Start" in xml
        assert "Button" in xml
        assert "Motor_Start" in xml

    def test_build_full_screen(self):
        screen = ScreenSpec(name="TestScreen", width=800, height=480, items=[
            ScreenItemSpec(id="TXT_Title", name="Title", type=ScreenItemType.TEXT,
                           geometry=GeometrySpec(x=100, y=20, width=200, height=40), text={"zh-CN": "标题"}),
        ])
        xml = ScreenXmlBuilder().build_screen(screen)
        assert "TestScreen" in xml
        assert "TXT_Title" in xml
        assert "标题" in xml


class TestFunctionListBuilder:
    def test_build_set_bit_event(self):
        event = EventSpec(event=SemanticEvent.PRESS, actions=[ActionSpec(type=SemanticActionType.SET_BIT, tag="Motor_Start", value=1)])
        xml = FunctionListBuilder().build(event)
        assert "OnPress" in xml
        assert "SetBit" in xml
        assert "Motor_Start" in xml

    def test_build_reset_bit_event(self):
        event = EventSpec(event=SemanticEvent.RELEASE, actions=[ActionSpec(type=SemanticActionType.RESET_BIT, tag="Motor_Start", value=0)])
        xml = FunctionListBuilder().build(event)
        assert "OnRelease" in xml
        assert "ResetBit" in xml

    def test_build_toggle_event(self):
        event = EventSpec(event=SemanticEvent.CLICK, actions=[ActionSpec(type=SemanticActionType.TOGGLE_BIT, tag="Motor_AutoMode")])
        xml = FunctionListBuilder().build(event)
        assert "OnClick" in xml
        assert "InvertBit" in xml

    def test_build_activate_screen(self):
        event = EventSpec(event=SemanticEvent.CLICK, actions=[ActionSpec(type=SemanticActionType.ACTIVATE_SCREEN, screen="AlarmScreen")])
        xml = FunctionListBuilder().build(event)
        assert "ActivateScreen" in xml
        assert "AlarmScreen" in xml

    def test_supports_action_basic(self):
        fb = FunctionListBuilder()
        assert fb.supports_action(ActionSpec(type=SemanticActionType.SET_BIT), "basic")
        assert not fb.supports_action(ActionSpec(type=SemanticActionType.CALL_SCRIPT), "basic")
        assert not fb.supports_action(ActionSpec(type=SemanticActionType.OPEN_POPUP), "basic")


class TestDynamicXmlBuilder:
    def test_direct_tag_binding(self):
        b = BindingSpec(property="visible", kind=BindingKind.DIRECT_TAG, source_tag="Screen_Enable")
        xml = DynamicXmlBuilder().build(b)
        assert "Tag" in xml
        assert "Screen_Enable" in xml

    def test_discrete_binding(self):
        b = BindingSpec(property="background_color", kind=BindingKind.DISCRETE, source_tag="Motor_State",
                        config={"states": [{"value": 0, "output": "#808080"}, {"value": 1, "output": "#00C853"}]})
        xml = DynamicXmlBuilder().build(b)
        assert "Discrete" in xml
        assert "808080" in xml
        assert "00C853" in xml

    def test_flashing_binding(self):
        b = BindingSpec(property="flashing", kind=BindingKind.FLASHING, source_tag="Motor_Fault")
        xml = DynamicXmlBuilder().build(b)
        assert "Flashing" in xml

    def test_range_binding(self):
        b = BindingSpec(property="width", kind=BindingKind.RANGE, source_tag="Speed",
                        config={"ranges": [{"low": 0, "high": 50, "output": "100"}, {"low": 51, "high": 100, "output": "200"}]})
        xml = DynamicXmlBuilder().build(b)
        assert "Range" in xml

    def test_supports_property(self):
        db = DynamicXmlBuilder()
        assert db.supports_property("visible")
        assert db.supports_property("background_color")
        assert not db.supports_property("unknown_prop")


class TestVbsBuilder:
    def test_build_toggle(self):
        code = VbsBuilder().build_toggle("Motor_AutoMode")
        assert "SmartTags" in code
        assert "Motor_AutoMode" in code
        assert "Not" in code

    def test_build_set_bit(self):
        code = VbsBuilder().build_set_bit("Motor_Start", 1)
        assert "SmartTags" in code
        assert "= 1" in code

    def test_build_reset_bit(self):
        code = VbsBuilder().build_reset_bit("Motor_Start")
        assert "= 0" in code

    def test_build_set_value(self):
        code = VbsBuilder().build_set_value("Motor_SpeedSP", 1500)
        assert "1500" in code

    def test_build_set_by_condition(self):
        code = VbsBuilder().build_set_by_condition("Motor_AutoMode", "Speed_Enable", 1, 0)
        assert "If" in code
        assert "Then" in code
        assert "End If" in code

    def test_security_scan_rejects_shell(self):
        scan = VbsBuilder().security_scan('Shell "cmd.exe"')
        assert not scan["ok"]
        assert len(scan["errors"]) > 0

    def test_security_scan_rejects_filesystem(self):
        scan = VbsBuilder().security_scan('CreateObject("Scripting.FileSystemObject")')
        assert not scan["ok"]

    def test_security_scan_passes_clean(self):
        scan = VbsBuilder().security_scan('SmartTags("X") = 1')
        assert scan["ok"]

    def test_quote_smarttag(self):
        assert VbsBuilder.quote_smarttag('Tag"Name') == 'Tag""Name'


class TestClassicCommon:
    def test_comfort_allows_vbs(self):
        common = ClassicCommon(target_family="comfort")
        assert common.allow_vbs

    def test_basic_denies_vbs(self):
        common = ClassicCommon(target_family="basic")
        assert not common.allow_vbs

    def test_build_tags(self):
        common = ClassicCommon(target_family="comfort")
        tags = [TagSpec(name="X", data_type="Bool", scope=TagScope.INTERNAL)]
        xml = common.build_tags_xml(tags)
        assert "X" in xml

    def test_build_screen(self):
        common = ClassicCommon(target_family="comfort")
        screen = ScreenSpec(name="S1", width=800, height=480, items=[
            ScreenItemSpec(id="TXT_A", name="A", type=ScreenItemType.TEXT,
                           geometry=GeometrySpec(x=10, y=10, width=200, height=40), text={"zh-CN": "Hello"})
        ])
        xml = common.build_screen_xml(screen)
        assert "S1" in xml
        assert "Hello" in xml

    def test_generate_screen_id(self):
        common = ClassicCommon(target_family="comfort")
        id1 = common.generate_screen_id("Screen1")
        id2 = common.generate_screen_id("Screen1")
        assert id1 == id2  # deterministic

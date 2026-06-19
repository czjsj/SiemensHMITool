# -*- coding: utf-8 -*-
"""测试 Unified Backend (PR-09+10): Reflection Adapter, Tag/Screen/Property/Binding/Event/JS Builders."""
import sys, os, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.domain.ir_v2 import HmiProjectSpec, TagSpec, ScreenSpec, ScreenItemSpec, GeometrySpec, BindingSpec, EventSpec, ActionSpec, ScriptSpec
from backend.domain.enums import TagScope, ScreenItemType, BindingKind, SemanticEvent, SemanticActionType, HmiFamily
from backend.backends.unified.reflection_adapter import UnifiedReflectionAdapter
from backend.backends.unified.tag_builder import UnifiedTagBuilder
from backend.backends.unified.screen_builder import UnifiedScreenBuilder
from backend.backends.unified.property_builder import UnifiedPropertyBuilder
from backend.backends.unified.binding_builder import UnifiedBindingBuilder
from backend.backends.unified.event_builder import UnifiedEventBuilder
from backend.backends.unified.js_builder import JsBuilder
from backend.backends.unified.unified_backend import UnifiedBackend
from backend.domain.ir_v2 import TargetSpec
from backend.domain.deployment_plan import DeploymentPlan
from backend.domain.deployment_result import DeploymentResult, VerificationResult


class TestUnifiedReflectionAdapter:
    def test_resolve_type_key(self):
        ra = UnifiedReflectionAdapter()
        assert "HmiButton" in ra.resolve_type_key("button")
        assert "HmiIOField" in ra.resolve_type_key("io_field")

    def test_resolve_property(self):
        ra = UnifiedReflectionAdapter()
        assert ra.resolve_property("background_color") == ["BackColor", "BackgroundColor"]
        assert ra.resolve_property("visible") == ["Visible"]

    def test_resolve_event(self):
        ra = UnifiedReflectionAdapter()
        assert "Pressed" in ra.resolve_event("press")
        assert "Clicked" in ra.resolve_event("click")

    def test_find_type_returns_none_for_unknown(self):
        ra = UnifiedReflectionAdapter()
        assert ra.find_type(["NonExistentType"]) is None


class TestUnifiedTagBuilder:
    def test_build_tag_spec_internal(self):
        tag = TagSpec(name="MyBool", data_type="Bool", scope=TagScope.INTERNAL)
        spec = UnifiedTagBuilder().build_tag_spec(tag)
        assert spec["Name"] == "MyBool"
        assert spec["DataType"] == "Bool"

    def test_build_tag_spec_external_with_controller(self):
        tag = TagSpec(name="Motor_Start", data_type="Bool", scope=TagScope.EXTERNAL, connection="PLC_1", controller_tag="DB1.Start")
        spec = UnifiedTagBuilder().build_tag_spec(tag)
        assert spec["ControllerTag"] == "DB1.Start"

    def test_build_wincc_ml(self):
        tags = [TagSpec(name="T1", data_type="Bool", scope=TagScope.INTERNAL), TagSpec(name="T2", data_type="Real", scope=TagScope.EXTERNAL, connection="PLC_1")]
        ml = UnifiedTagBuilder().build_wincc_ml(tags)
        assert "T1" in ml
        assert "T2" in ml
        assert "TagTable" in ml

    def test_build_tags(self):
        tags = [TagSpec(name="X", data_type="Int", scope=TagScope.INTERNAL)]
        result = UnifiedTagBuilder().build_tags(tags)
        assert len(result) == 1
        assert result[0]["Name"] == "X"


class TestUnifiedScreenBuilder:
    def test_create_screen_spec(self):
        screen = ScreenSpec(name="MainScreen", width=1920, height=1080, items=[
            ScreenItemSpec(id="TXT_A", name="A", type=ScreenItemType.TEXT, geometry=GeometrySpec(x=10, y=20, width=200, height=40))
        ])
        spec = UnifiedScreenBuilder().create_screen_spec(screen)
        assert spec["Name"] == "MainScreen"
        assert spec["Width"] == 1920
        assert spec["ItemCount"] == 1

    def test_create_item_spec(self):
        item = ScreenItemSpec(id="BTN_Start", name="Start", type=ScreenItemType.BUTTON,
                              geometry=GeometrySpec(x=100, y=200, width=120, height=50), tag_binding="Motor_Start")
        spec = UnifiedScreenBuilder().create_item_spec(item)
        assert spec["Name"] == "BTN_Start"
        assert spec["TagBinding"] == "Motor_Start"

    def test_apply_static_properties(self):
        item = ScreenItemSpec(id="BTN_X", name="X", type=ScreenItemType.BUTTON,
                              geometry=GeometrySpec(x=10, y=10, width=120, height=50),
                              properties={"background_color": "#2BB673"}, text={"zh-CN": "按钮"})
        props = UnifiedScreenBuilder().apply_static_properties(item)
        assert "background_color" in props
        assert props["Text"] == {"zh-CN": "按钮"}


class TestUnifiedPropertyBuilder:
    def test_map_properties(self):
        pb = UnifiedPropertyBuilder()
        mapped = pb.map_properties({"left": 100, "top": 200, "background_color": "#FF0000"})
        assert mapped["Left"] == 100
        assert mapped["Top"] == 200
        assert mapped["BackColor"] == "#FF0000"

    def test_hex_to_argb(self):
        pb = UnifiedPropertyBuilder()
        argb = pb.hex_to_argb("#FF0000")
        assert argb == 0xFFFF0000


class TestUnifiedBindingBuilder:
    def test_direct_tag_dynamization(self):
        b = BindingSpec(property="visible", kind=BindingKind.DIRECT_TAG, source_tag="Screen_Enable")
        spec = UnifiedBindingBuilder().create(b)
        assert spec["DynamizationType"] == "TagDynamization"

    def test_flashing_dynamization(self):
        b = BindingSpec(property="flashing", kind=BindingKind.FLASHING, source_tag="Motor_Fault")
        spec = UnifiedBindingBuilder().create(b)
        assert spec["DynamizationType"] == "FlashingDynamization"

    def test_validate_binding_target(self):
        bb = UnifiedBindingBuilder()
        b = BindingSpec(property="visible", kind=BindingKind.DIRECT_TAG, source_tag="X")
        assert bb.validate_binding_target(b, {"visible", "background_color"})
        assert not bb.validate_binding_target(b, {"enabled"})


class TestUnifiedEventBuilder:
    def test_build_event_handler(self):
        event = EventSpec(event=SemanticEvent.PRESS, actions=[ActionSpec(type=SemanticActionType.SET_BIT, tag="Motor_Start", value=1)])
        handler = UnifiedEventBuilder().build_event_handler(event)
        assert handler["HandlerType"] == "Press"

    def test_build_javascript_set_bit(self):
        js = UnifiedEventBuilder().build_javascript([ActionSpec(type=SemanticActionType.SET_BIT, tag="Motor_Start", value=1)])
        assert 'Tags("Motor_Start")' in js
        assert "Write(1)" in js

    def test_build_javascript_toggle(self):
        js = UnifiedEventBuilder().build_javascript([ActionSpec(type=SemanticActionType.TOGGLE_BIT, tag="Motor_AutoMode")])
        assert "!" in js

    def test_build_javascript_activate_screen(self):
        js = UnifiedEventBuilder().build_javascript([ActionSpec(type=SemanticActionType.ACTIVATE_SCREEN, screen="AlarmScreen")])
        assert "UI.ActivateScreen" in js
        assert "AlarmScreen" in js

    def test_build_javascript_increment(self):
        js = UnifiedEventBuilder().build_javascript([ActionSpec(type=SemanticActionType.INCREMENT, tag="Counter", value=1)])
        assert "+ 1" in js

    def test_resolve_event_enum(self):
        candidates = UnifiedEventBuilder().resolve_event_enum("press")
        assert "Pressed" in candidates


class TestJsBuilder:
    def test_security_scan_rejects_eval(self):
        scan = JsBuilder().security_scan('eval("alert(1)")')
        assert not scan["ok"]

    def test_security_scan_rejects_document(self):
        scan = JsBuilder().security_scan('document.cookie')
        assert not scan["ok"]

    def test_security_scan_passes_clean(self):
        scan = JsBuilder().security_scan('Tags("X").Write(1);')
        assert scan["ok"]

    def test_build_from_actions(self):
        js = JsBuilder().build_from_actions([ActionSpec(type=SemanticActionType.SET_BIT, tag="X", value=1)])
        assert "Tags" in js


class TestUnifiedBackend:
    def test_supports_unified(self):
        be = UnifiedBackend()
        assert be.supports(TargetSpec(family=HmiFamily.UNIFIED))

    def test_supports_rejects_comfort(self):
        be = UnifiedBackend()
        assert not be.supports(TargetSpec(family=HmiFamily.COMFORT))

    def test_build_plan(self):
        be = UnifiedBackend()
        spec = HmiProjectSpec(
            target=TargetSpec(family=HmiFamily.UNIFIED),
            tags=[TagSpec(name="X", data_type="Bool")],
            screens=[ScreenSpec(name="S1", width=1920, height=1080)],
        )
        plan = be.build_plan(spec)
        assert isinstance(plan, DeploymentPlan)

    def test_execute(self):
        be = UnifiedBackend()
        spec = HmiProjectSpec(target=TargetSpec(family=HmiFamily.UNIFIED), screens=[ScreenSpec(name="S1", width=800, height=480)])
        plan = be.build_plan(spec)
        result = be.execute(plan)
        assert isinstance(result, DeploymentResult)
        assert result.backend == "unified_direct"

    def test_verify(self):
        be = UnifiedBackend()
        spec = HmiProjectSpec(target=TargetSpec(family=HmiFamily.UNIFIED), tags=[TagSpec(name="X", data_type="Bool")], screens=[ScreenSpec(name="S1", width=800, height=480)])
        result = be.verify(spec)
        assert isinstance(result, VerificationResult)

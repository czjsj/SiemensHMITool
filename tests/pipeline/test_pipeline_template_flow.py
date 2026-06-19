# -*- coding: utf-8 -*-
"""测试 Pipeline V4.0 模板流程 — 模板分析、原型匹配、变量生成、导入前验证。"""
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest

from backend.template.prototype_extractor import analyze_template_screen
from backend.template.prototype_registry import PrototypeRegistry
from backend.template.template_binding_validator import validate_generated_screen_xml
from backend.variable_engine import VariableEngine


def _load_fixture(filename: str) -> str:
    base = os.path.join(os.path.dirname(__file__), "..", "fixtures")
    with open(os.path.join(base, filename), "r", encoding="utf-8") as f:
        return f.read()


class TestPipelineTemplateFlow:
    """测试 Pipeline 中的 V4.0 模板流程。"""

    @pytest.fixture
    def template_xml(self):
        return _load_fixture("template_button_indicator.xml")

    @pytest.fixture
    def ir(self):
        return json.loads(_load_fixture("ir_motor_control.json"))

    def test_pipeline_template_analyzed(self, template_xml):
        """模板分析成功返回 TemplateProfile。"""
        profile = analyze_template_screen(template_xml)
        assert profile is not None
        assert len(profile.buttons) >= 1
        assert len(profile.indicators) >= 1
        assert len(profile.all_prototypes()) >= 4

    def test_pipeline_prototype_matched(self, template_xml, ir):
        """所有 IR 控件成功匹配模板原型。"""
        engine = VariableEngine()
        project = engine.enrich(ir)

        profile = analyze_template_screen(template_xml)
        registry = PrototypeRegistry(profile)

        matched = 0
        for screen in project.screens:
            for item in screen.items:
                proto = registry.find_for_item(item)
                assert proto is not None, f"控件 '{item.id}' 找不到原型"
                matched += 1

        assert matched >= 1

    def test_pipeline_variables_generated(self, ir):
        """变量引擎成功生成变量。"""
        engine = VariableEngine()
        project = engine.enrich(ir)

        assert len(project.tags) >= 1
        tag_names = {t.name for t in project.tags}
        assert len(tag_names) == len(project.tags), "变量名重复"

    def test_pipeline_pre_import_validated(self, template_xml, ir):
        """导入前验证 — 正常 XML 通过。"""
        engine = VariableEngine()
        project = engine.enrich(ir)

        tags = [t.name for t in project.tags]

        # 构造模拟生成后的 XML
        xml = f"""<Document xmlns="http://www.siemens.com/automation/SimaticML">
          <SW.Screen><AttributeList><Name>Motor_Control</Name><Width>1280</Width><Height>800</Height></AttributeList>
            <ObjectList>
              <Hmi.Screen.Button ID="1"><AttributeList><ObjectName>BTN_Start</ObjectName><ProcessTag>{tags[0]}</ProcessTag></AttributeList></Hmi.Screen.Button>
              <Hmi.Screen.Button ID="2"><AttributeList><ObjectName>BTN_Stop</ObjectName><ProcessTag>{tags[1] if len(tags) > 1 else tags[0]}</ProcessTag></AttributeList></Hmi.Screen.Button>
            </ObjectList>
          </SW.Screen></Document>"""

        diags = validate_generated_screen_xml(
            xml, tags, ["Template_BTN_Tag", "Template_LMP_Tag"],
            ["BTN_Start", "BTN_Stop"],
        )
        errors = [d for d in diags if d["severity"] == "error"]
        assert len(errors) == 0, f"不应有错误: {[d['message'] for d in errors]}"

    def test_pipeline_template_missing_returns_error(self, ir):
        """模板不可用时系统不应崩溃。"""
        engine = VariableEngine()
        project = engine.enrich(ir)

        # 空模板应返回可处理的错误
        try:
            profile = analyze_template_screen("<root></root>")
            # 空 root 没有控件 — 应该在 diagnostics 中报告
            assert len(profile.all_prototypes()) == 0
        except Exception as e:
            # 允许抛出可读异常
            assert "parse" in str(e).lower() or "xml" in str(e).lower() or "root" in str(e).lower()

    def test_pipeline_button_no_prototype_error(self, template_xml, ir):
        """button 找不到指定 prototype 时回退到默认同类型原型。"""
        engine = VariableEngine()
        project = engine.enrich(ir)

        profile = analyze_template_screen(template_xml)
        registry = PrototypeRegistry(profile)

        from backend.domain.ir_v2 import ScreenItemSpec, GeometrySpec
        from backend.domain.enums import ScreenItemType, ButtonBehavior
        unknown_item = ScreenItemSpec(
            id="BTN_Unknown", name="未知", type=ScreenItemType.BUTTON,
            geometry=GeometrySpec(x=0, y=0),
            template_ref="NONEXISTENT_TEMPLATE",
            behavior=ButtonBehavior.MOMENTARY,
        )
        # 按优先级 5（默认同类型）应回退到第一个按钮原型
        proto = registry.find_for_item(unknown_item)
        assert proto is not None
        assert proto.item_kind == "button"

    def test_pipeline_indicator_no_prototype_error(self, template_xml, ir):
        """indicator 找不到指定 prototype 时回退到默认同类型原型。"""
        engine = VariableEngine()
        project = engine.enrich(ir)

        profile = analyze_template_screen(template_xml)
        registry = PrototypeRegistry(profile)

        from backend.domain.ir_v2 import ScreenItemSpec, GeometrySpec
        from backend.domain.enums import ScreenItemType, IndicatorMode
        unknown_item = ScreenItemSpec(
            id="LMP_Unknown", name="未知灯", type=ScreenItemType.INDICATOR,
            geometry=GeometrySpec(x=0, y=0),
            template_ref="NONEXISTENT_INDICATOR_TEMPLATE",
            indicator_mode=IndicatorMode.ALARM,
        )
        # 按优先级 5（默认同类型）应回退到第一个指示灯原型
        proto = registry.find_for_item(unknown_item)
        assert proto is not None
        assert proto.item_kind == "indicator"

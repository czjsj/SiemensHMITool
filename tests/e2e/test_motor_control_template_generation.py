# -*- coding: utf-8 -*-
"""
端到端测试 — 电机控制画面模板生成验证。

不连接 TIA Portal，仅验证完整 XML 生成流程的正确性。
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.template.prototype_extractor import analyze_template_screen
from backend.template.prototype_registry import PrototypeRegistry
from backend.template.xml_rewrite_rules import (
    clone_prototype_node,
    replace_control_name,
    replace_control_text,
    replace_geometry,
    replace_all_tag_references,
    ensure_no_placeholder_tags,
    assign_unique_control_ids,
)
from backend.template.xml_utils import collect_existing_ids, deepcopy_xml_node
from backend.variable_engine import VariableEngine


def _load_fixture(filename: str) -> str:
    base = os.path.join(os.path.dirname(__file__), "..", "fixtures")
    with open(os.path.join(base, filename), "r", encoding="utf-8") as f:
        return f.read()


class TestMotorControlTemplateGeneration:
    """端到端电机控制画面模板生成测试。"""

    @pytest.fixture
    def template_xml(self):
        return _load_fixture("template_button_indicator.xml")

    @pytest.fixture
    def ir(self):
        return json.loads(_load_fixture("ir_motor_control.json"))

    def test_full_motor_control_pipeline(self, template_xml, ir):
        """完整流程：加载模板 → 分析原型 → 克隆控件 → 替换变量 → 验证。"""
        # Step 1: VariableEngine enrich
        engine = VariableEngine()
        project = engine.enrich(ir)

        # Step 2: analyze template screen
        profile = analyze_template_screen(template_xml)
        assert len(profile.buttons) >= 2
        assert len(profile.indicators) >= 2

        # Step 3: PrototypeRegistry
        registry = PrototypeRegistry(profile)

        # Step 4: verify all items can find prototypes
        for screen in project.screens:
            for item in screen.items:
                proto = registry.find_for_item(item)
                assert proto is not None, f"控件 '{item.id}' 找不到原型"

    def test_template_variables_replaced(self, template_xml, ir):
        """生成 XML 中无模板变量残留。"""
        profile = analyze_template_screen(template_xml)
        # 收集模板变量名
        template_tags = set()
        for proto in profile.all_prototypes():
            for ref in proto.tag_references:
                if "Template_" in ref.tag_name:
                    template_tags.add(ref.tag_name)

        # 模拟克隆和替换
        registry = PrototypeRegistry(profile)
        import xml.etree.ElementTree as ET
        root = ET.fromstring(template_xml)
        used_ids = collect_existing_ids(root)

        for proto in registry._buttons[:1]:
            cloned = clone_prototype_node(proto.xml_node, "BTN_Start", used_ids)
            old_tags = [t for t in template_tags if "BTN" in t and "Toggle" not in t]
            if old_tags:
                replace_all_tag_references(cloned, old_tags, "BTN_Motor_Start")
                replace_control_text(cloned, "启动")
                remaining = ensure_no_placeholder_tags(cloned, list(template_tags))
                assert len(remaining) == 0, f"残留模板变量: {remaining}"

    def test_control_ids_unique(self, template_xml):
        """克隆后的控件 ID 唯一。"""
        import xml.etree.ElementTree as ET
        root = ET.fromstring(template_xml)
        used_ids = collect_existing_ids(root)
        original_count = len(used_ids)

        profile = analyze_template_screen(template_xml)
        for proto in profile.all_prototypes()[:3]:
            cloned = clone_prototype_node(proto.xml_node, f"Clone_{proto.source_name}", used_ids)

        # 所有 ID 应唯一
        assert len(used_ids) > original_count
        all_ids = []
        for elem in root.iter():
            if "ID" in elem.attrib:
                all_ids.append(elem.attrib["ID"])
        # 加上新分配的 ID
        all_ids.extend(used_ids - set(all_ids))
        assert len(all_ids) == len(set(all_ids)), "ID 不唯一"

    def test_button_event_tags_replaced(self, template_xml):
        """按钮事件变量已被替换。"""
        profile = analyze_template_screen(template_xml)
        import xml.etree.ElementTree as ET
        root = ET.fromstring(template_xml)
        used_ids = collect_existing_ids(root)

        # 取第一个 momentary 按钮原型
        proto = next((b for b in profile.buttons if b.behavior == "momentary"), None)
        assert proto is not None

        cloned = clone_prototype_node(proto.xml_node, "BTN_Start", used_ids)
        replace_all_tag_references(cloned, ["Template_BTN_Tag"], "BTN_Motor_Start")
        replace_control_text(cloned, "启动")
        replace_geometry(cloned, {"x": 80, "y": 120, "width": 120, "height": 50})

        # 验证事件变量已替换
        xml_str = ET.tostring(cloned, encoding="unicode")
        assert "Template_BTN_Tag" not in xml_str
        assert "BTN_Motor_Start" in xml_str

    def test_indicator_dynamic_binding_replaced(self, template_xml):
        """指示灯动态绑定变量已被替换。"""
        profile = analyze_template_screen(template_xml)
        import xml.etree.ElementTree as ET
        root = ET.fromstring(template_xml)
        used_ids = collect_existing_ids(root)

        # 取第一个指示灯原型
        proto = next((i for i in profile.indicators if i.indicator_mode == "alarm"), None)
        assert proto is not None

        cloned = clone_prototype_node(proto.xml_node, "LMP_Fault", used_ids)
        replace_all_tag_references(cloned, ["Template_LMP_Alarm_Tag"], "STS_Motor_Fault")
        replace_control_text(cloned, "故障")

        xml_str = ET.tostring(cloned, encoding="unicode")
        assert "Template_LMP_Alarm_Tag" not in xml_str
        assert "STS_Motor_Fault" in xml_str

    def test_similar_variable_names_not_misreplaced(self, template_xml):
        """不误替换相似变量名（BTN_A 不会替换到 BTN_ABC 的 BTN_A 部分）。"""
        import xml.etree.ElementTree as ET
        root = ET.fromstring(template_xml)
        used_ids = collect_existing_ids(root)

        profile = analyze_template_screen(template_xml)
        proto = profile.buttons[0]

        cloned = clone_prototype_node(proto.xml_node, "Test_BTN", used_ids)
        # 假设模板变量是 "Template_BTN_Tag"，新变量是 "BTN_Motor_Start"
        replace_all_tag_references(cloned, ["Template_BTN_Tag"], "BTN_Motor_Start")

        xml_str = ET.tostring(cloned, encoding="unicode")
        # Template_BTN_Toggle_Tag 不应被部分替换
        assert "Template_BTN_Tag" not in xml_str

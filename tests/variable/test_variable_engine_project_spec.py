# -*- coding: utf-8 -*-
"""测试 VariableEngine enrich_project_spec 功能。"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from backend.variable_engine import VariableEngine
from backend.domain.ir_v2 import HmiProjectSpec
from backend.domain.enums import ScreenItemType, TagDirection


def _load_fixture(filename: str) -> dict:
    base = os.path.join(os.path.dirname(__file__), "..", "fixtures")
    with open(os.path.join(base, filename), "r", encoding="utf-8") as f:
        return json.load(f)


class TestVariableEngineProjectSpec:
    """测试 VariableEngine 的 enrich 方法。"""

    def test_button_gets_bool_write_tag(self, tmp_path):
        """button 自动生成 Bool 写变量。"""
        ir = {
            "meta": {"screen_name": "Test", "hmi_type": "Comfort", "resolution": "1280x800"},
            "objects": [
                {"id": "BTN_Start", "type": "Button", "x": 10, "y": 10, "width": 120, "height": 50, "text": "启动", "tag_mode": "momentary"}
            ],
            "tags": [],
        }
        engine = VariableEngine()
        project = engine.enrich(ir)

        assert len(project.tags) >= 1
        btn_tag = next((t for t in project.tags if t.name == "BTN_Start"), None)
        assert btn_tag is not None
        assert btn_tag.data_type == "Bool"

    def test_indicator_gets_bool_read_tag(self, tmp_path):
        """indicator 自动生成 Bool 读变量。"""
        ir = {
            "meta": {"screen_name": "Test", "hmi_type": "Comfort", "resolution": "1280x800"},
            "objects": [
                {"id": "LMP_Run", "type": "Indicator", "x": 10, "y": 10, "width": 60, "height": 60, "text": "运行",
                 "color_on": "#27D17F", "color_off": "#3A4250"}
            ],
            "tags": [],
        }
        engine = VariableEngine()
        project = engine.enrich(ir)

        assert len(project.tags) >= 1
        ind_tag = next((t for t in project.tags if t.name == "LMP_Run"), None)
        assert ind_tag is not None
        assert ind_tag.data_type == "Bool"

    def test_binding_tag_auto_filled(self, tmp_path):
        """binding.tag 缺失时自动补。"""
        ir = {
            "meta": {"screen_name": "Test", "hmi_type": "Comfort", "resolution": "1280x800"},
            "objects": [
                {"id": "BTN_Test", "type": "Button", "x": 10, "y": 10, "width": 120, "height": 50, "text": "测试"}
            ],
            "tags": [],
        }
        engine = VariableEngine()
        project = engine.enrich(ir)

        btn = project.screens[0].items[0]
        assert btn.tag_binding is not None
        assert btn.tag_binding.strip() != ""

    def test_variable_name_normalized(self, tmp_path):
        """变量名非法字符被修复。"""
        ir = {
            "meta": {"screen_name": "Test", "hmi_type": "Comfort", "resolution": "1280x800"},
            "objects": [
                {"id": "BTN_Start/Stop", "type": "Button", "x": 10, "y": 10, "width": 120, "height": 50, "text": "测试"}
            ],
            "tags": [],
        }
        engine = VariableEngine()
        project = engine.enrich(ir)
        # 不应崩溃
        assert len(project.screens[0].items) >= 1

    def test_existing_tag_not_duplicated(self, tmp_path):
        """已有 tag 不重复生成。"""
        ir = {
            "meta": {"screen_name": "Test", "hmi_type": "Comfort", "resolution": "1280x800"},
            "objects": [
                {"id": "BTN_Start", "type": "Button", "x": 10, "y": 10, "width": 120, "height": 50, "text": "启动", "process_tag": "ExistingTag"}
            ],
            "tags": [{"name": "ExistingTag", "data_type": "Bool"}],
        }
        engine = VariableEngine()
        project = engine.enrich(ir)

        existing_count = sum(1 for t in project.tags if t.name == "ExistingTag")
        assert existing_count == 1

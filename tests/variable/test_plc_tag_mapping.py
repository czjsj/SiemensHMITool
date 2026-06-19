# -*- coding: utf-8 -*-
"""测试 PLC 地址映射功能 — 语义匹配四层策略。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from backend.variable_engine import VariableEngine
from backend.domain.enums import TagScope


class TestPlcTagMapping:
    """测试 plc_tag_mapping 语义匹配。"""

    def test_exact_match_fills_address(self):
        """精确变量名匹配 — 填充 PLC 地址。"""
        ir = {
            "meta": {"screen_name": "Test", "hmi_type": "Comfort", "resolution": "1280x800"},
            "objects": [
                {"id": "BTN_Start", "type": "Button", "x": 10, "y": 10, "width": 120, "height": 50,
                 "text": "启动", "tag_mode": "momentary"}
            ],
            "tags": [{"name": "BTN_Motor_Start", "data_type": "Bool"}],
        }
        plc_mapping = {"BTN_Motor_Start": "DB10.DBX0.0"}
        engine = VariableEngine()
        project = engine.enrich(ir, plc_tag_mapping=plc_mapping)

        tag = next((t for t in project.tags if t.name == "BTN_Motor_Start"), None)
        assert tag is not None
        assert tag.address == "DB10.DBX0.0"
        assert tag.scope == TagScope.EXTERNAL

    def test_stripped_prefix_match_fills_address(self):
        """去掉前缀后匹配 — 填充 PLC 地址。"""
        ir = {
            "meta": {"screen_name": "Test", "hmi_type": "Comfort", "resolution": "1280x800"},
            "objects": [
                {"id": "BTN_MotorStart", "type": "Button", "x": 10, "y": 10, "width": 120, "height": 50,
                 "text": "启动", "tag_mode": "momentary"}
            ],
            "tags": [],
        }
        # 生成的 tag 名: BTN_MotorStart, 去前缀后: MotorStart → 匹配
        plc_mapping = {"MotorStart": "DB10.DBX0.0"}
        engine = VariableEngine()
        project = engine.enrich(ir, plc_tag_mapping=plc_mapping)

        tag = next((t for t in project.tags if "MotorStart" in t.name), None)
        assert tag is not None
        assert tag.address == "DB10.DBX0.0"

    def test_item_id_match_fills_address(self):
        """按 item id 匹配 — 填充 PLC 地址。"""
        ir = {
            "meta": {"screen_name": "Test", "hmi_type": "Comfort", "resolution": "1280x800"},
            "objects": [
                {"id": "BTN_Start", "type": "Button", "x": 10, "y": 10, "width": 120, "height": 50,
                 "text": "启动", "tag_mode": "momentary"}
            ],
            "tags": [],
        }
        plc_mapping = {"BTN_Start": "DB10.DBX0.0"}
        engine = VariableEngine()
        project = engine.enrich(ir, plc_tag_mapping=plc_mapping)

        tag = next((t for t in project.tags if "Start" in t.name), None)
        assert tag is not None
        assert tag.address == "DB10.DBX0.0"

    def test_chinese_text_match_fills_address(self):
        """按中文文本匹配 — 填充 PLC 地址。"""
        ir = {
            "meta": {"screen_name": "Test", "hmi_type": "Comfort", "resolution": "1280x800"},
            "objects": [
                {"id": "BTN_Start", "type": "Button", "x": 10, "y": 10, "width": 120, "height": 50,
                 "text": "启动", "tag_mode": "momentary"}
            ],
            "tags": [],
        }
        plc_mapping = {"启动": "DB10.DBX0.0"}
        engine = VariableEngine()
        project = engine.enrich(ir, plc_tag_mapping=plc_mapping)

        tag = next((t for t in project.tags if "Start" in t.name), None)
        assert tag is not None
        assert tag.address == "DB10.DBX0.0"

    def test_unmatched_keeps_pending_mapping(self):
        """未匹配地址 — 保留 pending_mapping=true。"""
        ir = {
            "meta": {"screen_name": "Test", "hmi_type": "Comfort", "resolution": "1280x800"},
            "objects": [
                {"id": "BTN_Test", "type": "Button", "x": 10, "y": 10, "width": 120, "height": 50,
                 "text": "测试", "tag_mode": "momentary"}
            ],
            "tags": [],
        }
        plc_mapping = {"Something_Else": "DB10.DBX5.0"}
        engine = VariableEngine()
        project = engine.enrich(ir, plc_tag_mapping=plc_mapping)

        tag = next((t for t in project.tags if "Test" in t.name), None)
        assert tag is not None
        assert tag.address is None or tag.address == ""
        assert tag.metadata.get("pending_mapping") is True

    def test_variable_conflict_different_type_errors(self):
        """同名不同类型变量报错 — 冲突记录在 project.diagnostics 中。"""
        ir = {
            "meta": {"screen_name": "Test", "hmi_type": "Comfort", "resolution": "1280x800"},
            "objects": [
                {"id": "BTN_Start", "type": "Button", "x": 10, "y": 10, "width": 120, "height": 50,
                 "text": "启动", "tag_mode": "momentary"}
            ],
            "tags": [
                {"name": "BTN_Motor_Start", "data_type": "Bool"},
                {"name": "BTN_Motor_Start", "data_type": "Real"},
            ],
        }
        engine = VariableEngine()
        project = engine.enrich(ir)

        errors = [d for d in project.diagnostics if d.severity.value == "error"]
        assert len(errors) >= 1, \
            f"未检测到变量冲突。Diagnostics: {[(d.code, d.message[:80]) for d in project.diagnostics]}"

    def test_same_name_same_type_no_error(self):
        """同名同类型变量不报错（允许复用）。"""
        ir = {
            "meta": {"screen_name": "Test", "hmi_type": "Comfort", "resolution": "1280x800"},
            "objects": [
                {"id": "BTN_Start", "type": "Button", "x": 10, "y": 10, "width": 120, "height": 50,
                 "text": "启动", "tag_mode": "momentary"}
            ],
            "tags": [
                {"name": "BTN_Motor_Start", "data_type": "Bool"},
                {"name": "BTN_Motor_Start", "data_type": "Bool"},
            ],
        }
        engine = VariableEngine()
        project = engine.enrich(ir)

        conflicts = [d for d in project.diagnostics
                     if "冲突" in d.message]
        assert len(conflicts) == 0

    def test_no_mapping_does_not_crash(self):
        """无 plc_tag_mapping 时正常运行。"""
        ir = {
            "meta": {"screen_name": "Test", "hmi_type": "Comfort", "resolution": "1280x800"},
            "objects": [
                {"id": "BTN_Test", "type": "Button", "x": 10, "y": 10, "width": 120, "height": 50,
                 "text": "测试", "tag_mode": "momentary"}
            ],
            "tags": [],
        }
        engine = VariableEngine()
        project = engine.enrich(ir)
        assert len(project.tags) >= 1

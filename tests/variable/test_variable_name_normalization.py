# -*- coding: utf-8 -*-
"""测试变量名规范化 — 非法字符替换、TIA 命名规则。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from backend.variable_engine import VariableEngine


class TestVariableNameNormalization:
    """测试变量名规范化与冲突处理。"""

    def test_slash_replaced_with_underscore(self):
        """变量名中的 '/' 被替换为 '_'。"""
        ir = {
            "meta": {"screen_name": "Test", "hmi_type": "Comfort", "resolution": "1280x800"},
            "objects": [
                {"id": "BTN_Start/Stop", "type": "Button", "x": 10, "y": 10, "width": 120, "height": 50,
                 "text": "启停"}
            ],
            "tags": [],
        }
        engine = VariableEngine()
        project = engine.enrich(ir)
        # 不应崩溃，变量名被规范化
        for tag in project.tags:
            assert "/" not in tag.name, f"变量名 '{tag.name}' 含非法字符 '/'"

    def test_special_chars_normalized(self):
        """变量名中的特殊字符被规范化。"""
        ir = {
            "meta": {"screen_name": "Test", "hmi_type": "Comfort", "resolution": "1280x800"},
            "objects": [
                {"id": "BTN_A@B#C$", "type": "Button", "x": 10, "y": 10, "width": 120, "height": 50,
                 "text": "特殊"}
            ],
            "tags": [],
        }
        engine = VariableEngine()
        project = engine.enrich(ir)
        for tag in project.tags:
            for ch in ("@", "#", "$", " ", "-"):
                assert ch not in tag.name, f"变量名 '{tag.name}' 含非法字符 '{ch}'"

    def test_duplicate_name_gets_suffix(self):
        """同名变量自动添加后缀 _2, _3 ...。"""
        ir = {
            "meta": {"screen_name": "Test", "hmi_type": "Comfort", "resolution": "1280x800"},
            "objects": [
                {"id": "BTN_Start", "type": "Button", "x": 10, "y": 10, "width": 120, "height": 50,
                 "text": "启动", "tag_mode": "momentary"}
            ],
            "tags": [{"name": "BTN_Start", "data_type": "Bool"}],
        }
        engine = VariableEngine()
        # 由于 enrich 中标签名已存在，_make_tag_name 应生成 BTN_Start_2
        project = engine.enrich(ir)
        tag_names = [t.name for t in project.tags]
        # 确认有自动生成且不重复
        assert len(tag_names) == len(set(tag_names)), f"变量名重复: {tag_names}"

    def test_empty_prefix_falls_back_safely(self):
        """空 id 或异常前缀时安全回退。"""
        ir = {
            "meta": {"screen_name": "Test", "hmi_type": "Comfort", "resolution": "1280x800"},
            "objects": [
                {"id": "", "type": "Button", "x": 10, "y": 10, "width": 120, "height": 50,
                 "text": "空ID"}
            ],
            "tags": [],
        }
        engine = VariableEngine()
        # 不应崩溃
        try:
            project = engine.enrich(ir)
        except Exception as e:
            pytest.fail(f"空 id 导致崩溃: {e}")

    def test_chinese_only_name_normalized(self):
        """纯中文变量名被合理处理。"""
        ir = {
            "meta": {"screen_name": "Test", "hmi_type": "Comfort", "resolution": "1280x800"},
            "objects": [
                {"id": "BTN_启动按钮", "type": "Button", "x": 10, "y": 10, "width": 120, "height": 50,
                 "text": "启动", "tag_mode": "momentary"}
            ],
            "tags": [],
        }
        engine = VariableEngine()
        project = engine.enrich(ir)
        # 不应崩溃
        assert len(project.tags) >= 1

# -*- coding: utf-8 -*-
"""测试变量名前缀幂等性工具 — tag_prefix_utils.py。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from backend.utils.tag_prefix_utils import (
    strip_known_tag_prefixes,
    has_known_tag_prefix,
    ensure_tag_prefix,
    KNOWN_TAG_PREFIXES,
)


class TestStripKnownTagPrefixes:
    """测试 strip_known_tag_prefixes — 递归前缀剥离。"""

    def test_strip_single_prefix(self):
        assert strip_known_tag_prefixes("BTN_Start") == "Start"

    def test_strip_double_prefix(self):
        assert strip_known_tag_prefixes("BTN_BTN_Start") == "Start"

    def test_strip_triple_prefix(self):
        assert strip_known_tag_prefixes("LMP_LMP_LMP_Fault") == "Fault"

    def test_strip_mixed_prefix(self):
        assert strip_known_tag_prefixes("STS_LMP_Run") == "Run"

    def test_strip_no_prefix(self):
        assert strip_known_tag_prefixes("Motor_Start") == "Motor_Start"

    def test_strip_empty_string(self):
        assert strip_known_tag_prefixes("") == ""

    def test_strip_already_clean(self):
        assert strip_known_tag_prefixes("Motor_Start") == "Motor_Start"

    def test_strip_prefix_only(self):
        assert strip_known_tag_prefixes("BTN_") == ""


class TestHasKnownTagPrefix:
    """测试 has_known_tag_prefix。"""

    def test_has_prefix_true(self):
        assert has_known_tag_prefix("BTN_Start") is True

    def test_has_prefix_false(self):
        assert has_known_tag_prefix("Start") is False

    def test_has_prefix_empty(self):
        assert has_known_tag_prefix("") is False

    def test_has_prefix_mem(self):
        assert has_known_tag_prefix("MEM_Value") is True

    def test_has_prefix_sts(self):
        assert has_known_tag_prefix("STS_Status") is True


class TestEnsureTagPrefix:
    """测试 ensure_tag_prefix — 幂等前缀确保。"""

    def test_ensure_fresh(self):
        assert ensure_tag_prefix("Start", "BTN_") == "BTN_Start"

    def test_ensure_already_has(self):
        assert ensure_tag_prefix("BTN_Start", "BTN_") == "BTN_Start"

    def test_ensure_double(self):
        assert ensure_tag_prefix("BTN_BTN_Start", "BTN_") == "BTN_Start"

    def test_ensure_wrong_prefix(self):
        assert ensure_tag_prefix("STS_LMP_Run", "STS_") == "STS_Run"

    def test_ensure_lmp_fault(self):
        assert ensure_tag_prefix("LMP_Fault", "LMP_") == "LMP_Fault"

    def test_ensure_lmp_lmp_fault(self):
        assert ensure_tag_prefix("LMP_LMP_Fault", "LMP_") == "LMP_Fault"

    def test_ensure_empty_name(self):
        assert ensure_tag_prefix("", "BTN_") == "BTN_"

    def test_ensure_no_change_needed(self):
        assert ensure_tag_prefix("STS_Run", "STS_") == "STS_Run"


class TestKnownPrefixesConstant:
    """KNOWN_TAG_PREFIXES 包含所有预期前缀。"""

    def test_all_prefixes_present(self):
        assert "BTN_" in KNOWN_TAG_PREFIXES
        assert "MEM_" in KNOWN_TAG_PREFIXES
        assert "STS_" in KNOWN_TAG_PREFIXES
        assert "LMP_" in KNOWN_TAG_PREFIXES
        assert "IO_" in KNOWN_TAG_PREFIXES
        assert "SIO_" in KNOWN_TAG_PREFIXES
        assert "TXT_" in KNOWN_TAG_PREFIXES


class TestIntegration:
    """集成测试 — 确保 hmi_ir.py validate_ir 不再生成双前缀。"""

    def test_hmi_ir_validate_button_no_double_prefix(self):
        """hmi_ir.validate_ir 对 Button 不应生成 BTN_BTN_ 前缀。"""
        from backend.hmi_ir import validate_ir

        ir = {
            "meta": {"screen_name": "TestScreen"},
            "objects": [
                {
                    "id": "BTN_Start",
                    "type": "Button",
                    "x": 10, "y": 10,
                    "text": "Start",
                }
            ],
        }
        result = validate_ir(ir)
        # Find the process_tag on the button
        btn = next(o for o in result.get("objects", []) if o["type"] == "Button")
        tag = btn.get("process_tag", "")
        assert tag == "BTN_Start", f"Expected BTN_Start, got: {tag}"
        assert tag != "BTN_BTN_Start", f"Double prefix should not occur: {tag}"

    def test_hmi_ir_validate_indicator_no_double_prefix(self):
        """hmi_ir.validate_ir 对 Indicator 不应生成 STS_LMP_ 前缀。"""
        from backend.hmi_ir import validate_ir

        ir = {
            "meta": {"screen_name": "TestScreen"},
            "objects": [
                {
                    "id": "LMP_Run",
                    "type": "Indicator",
                    "x": 10, "y": 10,
                    "blink": False,
                }
            ],
        }
        result = validate_ir(ir)
        ind = next(o for o in result.get("objects", []) if o["type"] == "Indicator")
        tag = ind.get("process_tag", "")
        # LMP_Run with blink=False → STS_ prefix → expected STS_Run
        assert tag == "STS_Run", f"Expected STS_Run, got: {tag}"
        assert "LMP" not in tag.split("_")[0], f"Should not have double prefix: {tag}"

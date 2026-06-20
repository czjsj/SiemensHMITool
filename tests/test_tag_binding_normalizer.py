# -*- coding: utf-8 -*-
"""
Tests for tag_binding_normalizer.py — V4.1 FIX

测试:
  1. LLM 没有输出 tags → 自动补齐
  2. 对象有 binding.tag，但 tags 为空 → 补齐
  3. 对象有 process_tag，但 binding.tag 为空 → 补齐
  4. 变量字段冲突必须失败
  5. assert_legacy_tags_complete 正常/异常
"""

import pytest
from backend.tag_binding_normalizer import (
    normalize_legacy_tag_bindings,
    assert_legacy_tags_complete,
    infer_tag_name_from_object,
    infer_legacy_tag_spec,
    validate_legacy_ir_tag_bindings,
    CONTROL_TYPES_REQUIRING_TAG,
)


class TestNormalizeLegacyTagBindings:
    """核心测试：legacy IR 变量规范化。"""

    # ------------------------------------------------------------------
    # Test 1: LLM 没有输出 tags — 自动补齐
    # ------------------------------------------------------------------

    def test_auto_generate_tags_when_empty(self):
        """LLM 输出 objects 但 tags 为空，应自动生成 3+ 个变量。"""
        ir = {
            "meta": {"screen_name": "Test"},
            "objects": [
                {"id": "btn_start", "type": "Button", "text": "启动"},
                {"id": "lamp_run", "type": "Indicator", "text": "运行"},
                {"id": "io_speed", "type": "IOField", "text": "速度"},
            ],
            "tags": [],
        }

        result = normalize_legacy_tag_bindings(ir)

        # tags 至少 3 个
        assert len(result["tags"]) >= 3, f"Expected >=3 tags, got {len(result['tags'])}"

        # btn_start 有完整绑定
        btn = next(o for o in result["objects"] if o["id"] == "btn_start")
        assert btn.get("process_tag"), "btn_start missing process_tag"
        assert btn.get("tag_binding"), "btn_start missing tag_binding"
        assert btn.get("binding", {}).get("tag"), "btn_start missing binding.tag"
        assert btn["process_tag"] == btn["tag_binding"] == btn["binding"]["tag"]

        # lamp_run 有完整绑定
        lamp = next(o for o in result["objects"] if o["id"] == "lamp_run")
        assert lamp.get("process_tag"), "lamp_run missing process_tag"
        assert lamp.get("tag_binding"), "lamp_run missing tag_binding"
        assert lamp.get("binding", {}).get("tag"), "lamp_run missing binding.tag"
        assert lamp["process_tag"] == lamp["tag_binding"] == lamp["binding"]["tag"]

        # io_speed 有完整绑定
        io = next(o for o in result["objects"] if o["id"] == "io_speed")
        assert io.get("process_tag"), "io_speed missing process_tag"
        assert io.get("tag_binding"), "io_speed missing tag_binding"
        assert io.get("binding", {}).get("tag"), "io_speed missing binding.tag"
        assert io["process_tag"] == io["tag_binding"] == io["binding"]["tag"]

        # 所有 binding.tag 都存在于 tags
        tag_names = {t["name"] for t in result["tags"]}
        for obj in result["objects"]:
            if obj["type"] in CONTROL_TYPES_REQUIRING_TAG:
                bt = obj.get("binding", {}).get("tag", "")
                assert bt in tag_names, f"{obj['id']} binding.tag '{bt}' not in tags"

    # ------------------------------------------------------------------
    # Test 2: 对象有 binding.tag，但 tags 为空 — 自动补
    # ------------------------------------------------------------------

    def test_object_has_binding_tag_but_tags_empty(self):
        """对象有 binding.tag，tags 应自动补齐。"""
        ir = {
            "objects": [
                {
                    "id": "btn_open",
                    "type": "Button",
                    "binding": {"tag": "BTN_Door_Open"},
                }
            ],
            "tags": [],
        }

        result = normalize_legacy_tag_bindings(ir)

        obj = result["objects"][0]
        assert obj["process_tag"] == "BTN_Door_Open"
        assert obj["tag_binding"] == "BTN_Door_Open"
        assert obj["binding"]["tag"] == "BTN_Door_Open"

        tag_names = {t["name"] for t in result["tags"]}
        assert "BTN_Door_Open" in tag_names

    # ------------------------------------------------------------------
    # Test 3: 对象有 process_tag，但 binding.tag 为空 — 自动补
    # ------------------------------------------------------------------

    def test_object_has_process_tag_but_binding_empty(self):
        """对象有 process_tag，binding.tag 应自动补齐。"""
        ir = {
            "objects": [
                {
                    "id": "btn_close",
                    "type": "Button",
                    "process_tag": "BTN_Door_Close",
                }
            ],
            "tags": [],
        }

        result = normalize_legacy_tag_bindings(ir)

        obj = result["objects"][0]
        assert obj["binding"]["tag"] == "BTN_Door_Close"
        assert obj["tag_binding"] == "BTN_Door_Close"
        assert obj["process_tag"] == "BTN_Door_Close"

        tag_names = {t["name"] for t in result["tags"]}
        assert "BTN_Door_Close" in tag_names

    # ------------------------------------------------------------------
    # Test 4: 变量字段冲突必须失败
    # ------------------------------------------------------------------

    def test_conflicting_fields_raises_error(self):
        """process_tag, tag_binding, binding.tag 不一致时必须抛出错误。"""
        ir = {
            "objects": [
                {
                    "id": "btn_conflict",
                    "type": "Button",
                    "process_tag": "BTN_A",
                    "tag_binding": "BTN_B",
                    "binding": {"tag": "BTN_C"},
                }
            ],
            "tags": [],
        }

        with pytest.raises(ValueError, match=r"conflict|不一致|BTN_A|BTN_B|BTN_C"):
            normalize_legacy_tag_bindings(ir)

    # ------------------------------------------------------------------
    # Test: assert_legacy_tags_complete passes when complete
    # ------------------------------------------------------------------

    def test_assert_complete_passes(self):
        """所有变量绑定完整时应通过断言。"""
        ir = {
            "objects": [
                {
                    "id": "btn_ok",
                    "type": "Button",
                    "process_tag": "BTN_OK",
                    "tag_binding": "BTN_OK",
                    "binding": {"tag": "BTN_OK"},
                }
            ],
            "tags": [{"name": "BTN_OK", "data_type": "Bool"}],
        }

        # should not raise
        assert_legacy_tags_complete(ir)

    # ------------------------------------------------------------------
    # Test: assert_legacy_tags_complete fails when tag missing
    # ------------------------------------------------------------------

    def test_assert_complete_fails_on_missing_tag(self):
        """变量在 tags 中缺失时应抛出错误。"""
        ir = {
            "objects": [
                {
                    "id": "btn_missing",
                    "type": "Button",
                    "process_tag": "BTN_Missing",
                    "tag_binding": "BTN_Missing",
                    "binding": {"tag": "BTN_Missing"},
                }
            ],
            "tags": [],
        }

        with pytest.raises(ValueError, match=r"BTN_Missing|not found"):
            assert_legacy_tags_complete(ir)

    # ------------------------------------------------------------------
    # Test: assert_legacy_tags_complete fails on inconsistent bindings
    # ------------------------------------------------------------------

    def test_assert_complete_fails_on_inconsistent(self):
        """不一致的绑定时应抛出错误。"""
        ir = {
            "objects": [
                {
                    "id": "btn_bad",
                    "type": "Button",
                    "process_tag": "BTN_X",
                    "tag_binding": "BTN_Y",
                    "binding": {"tag": "BTN_X"},
                }
            ],
            "tags": [
                {"name": "BTN_X", "data_type": "Bool"},
                {"name": "BTN_Y", "data_type": "Bool"},
            ],
        }

        with pytest.raises(ValueError, match=r"inconsistent|不一致"):
            assert_legacy_tags_complete(ir)


class TestInferTagNameFromObject:
    """变量名推断测试。"""

    def test_button_momentary_prefix(self):
        obj = {"id": "btn_start", "type": "Button", "text": "启动"}
        name = infer_tag_name_from_object(obj)
        assert name.startswith("BTN_")

    def test_button_toggle_prefix(self):
        obj = {"id": "btn_mode", "type": "Button", "text": "切换"}
        name = infer_tag_name_from_object(obj)
        assert name.startswith("MEM_")

    def test_indicator_status_prefix(self):
        obj = {"id": "lamp_run", "type": "Indicator", "text": "运行"}
        name = infer_tag_name_from_object(obj)
        assert name.startswith("STS_")

    def test_indicator_alarm_prefix(self):
        obj = {"id": "lamp_fault", "type": "Indicator", "text": "故障"}
        name = infer_tag_name_from_object(obj)
        assert name.startswith("LMP_")

    def test_iofield_prefix(self):
        obj = {"id": "io_speed", "type": "IOField", "text": "速度"}
        name = infer_tag_name_from_object(obj)
        assert name.startswith("IO_")

    def test_symbolic_iofield_prefix(self):
        obj = {"id": "sio_mode", "type": "SymbolicIOField", "text": "模式"}
        name = infer_tag_name_from_object(obj)
        assert name.startswith("SIO_")

    def test_no_empty_name(self):
        obj = {"id": "", "type": "Button", "text": ""}
        name = infer_tag_name_from_object(obj)
        assert name and name.strip(), "should not be empty"

    def test_no_special_chars(self):
        obj = {"id": "btn test@#$", "type": "Button", "text": "test"}
        name = infer_tag_name_from_object(obj)
        assert "@" not in name
        assert "#" not in name
        assert "$" not in name
        assert " " not in name


class TestInferLegacyTagSpec:
    """Tag spec 推断测试。"""

    def test_button_defaults_to_bool(self):
        obj = {"id": "btn_x", "type": "Button"}
        spec = infer_legacy_tag_spec(obj, "BTN_X")
        assert spec["data_type"] == "Bool"

    def test_indicator_defaults_to_bool(self):
        obj = {"id": "lamp_x", "type": "Indicator"}
        spec = infer_legacy_tag_spec(obj, "STS_X")
        assert spec["data_type"] == "Bool"

    def test_iofield_defaults_to_real(self):
        obj = {"id": "io_x", "type": "IOField"}
        spec = infer_legacy_tag_spec(obj, "IO_X")
        assert spec["data_type"] == "Real"

    def test_symbolic_iofield_defaults_to_int(self):
        obj = {"id": "sio_x", "type": "SymbolicIOField"}
        spec = infer_legacy_tag_spec(obj, "SIO_X")
        assert spec["data_type"] == "Int"

    def test_spec_has_required_fields(self):
        obj = {"id": "btn_x", "type": "Button", "text": "测试"}
        spec = infer_legacy_tag_spec(obj, "BTN_X")
        assert "name" in spec
        assert "data_type" in spec
        assert "address" in spec
        assert "comment" in spec

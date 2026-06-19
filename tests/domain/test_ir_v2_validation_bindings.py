# -*- coding: utf-8 -*-
"""测试 IR V2 模板绑定校验 — 按钮/指示灯绑定要求。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from backend.domain.ir_v2 import (
    HmiProjectSpec, ScreenItemSpec, ScreenSpec,
    BindingSpec, TagSpec, GeometrySpec,
)
from backend.domain.enums import (
    ScreenItemType, ButtonBehavior, IndicatorMode,
    TagDirection, TagScope,
)
from backend.domain.validation import validate_template_binding_requirements
from backend.domain.diagnostics import DiagnosticCodes


def _make_project(items: list[ScreenItemSpec], tags: list[TagSpec] | None = None):
    return HmiProjectSpec(
        schema_version="2.0",
        tags=tags or [],
        screens=[ScreenSpec(name="Test", items=items)],
    )


class TestTemplateBindingValidation:
    """测试模板绑定校验规则。"""

    def test_button_no_binding_tag_fails(self):
        """button 无 binding.tag 时校验失败。"""
        item = ScreenItemSpec(
            id="btn_test", name="btn_test",
            type=ScreenItemType.BUTTON,
            behavior=ButtonBehavior.MOMENTARY,
        )
        project = _make_project([item])
        diags = validate_template_binding_requirements(project)
        errors = [d for d in diags if d.severity == "error"]
        assert len(errors) >= 1
        assert any("binding.tag" in d.message.lower() or "缺少" in d.message for d in errors)

    def test_indicator_no_binding_tag_fails(self):
        """indicator 无 binding.tag 时校验失败。"""
        item = ScreenItemSpec(
            id="lmp_test", name="lmp_test",
            type=ScreenItemType.INDICATOR,
            indicator_mode=IndicatorMode.BOOL_COLOR,
        )
        project = _make_project([item])
        diags = validate_template_binding_requirements(project)
        errors = [d for d in diags if d.severity == "error"]
        assert len(errors) >= 1

    def test_binding_tag_not_in_tags_fails(self):
        """binding.tag 不存在时校验失败。"""
        item = ScreenItemSpec(
            id="btn_test", name="btn_test",
            type=ScreenItemType.BUTTON,
            tag_binding="NonexistentTag",
            behavior=ButtonBehavior.MOMENTARY,
        )
        project = _make_project([item], tags=[TagSpec(name="OtherTag")])
        diags = validate_template_binding_requirements(project)
        errors = [d for d in diags if d.severity == "error"]
        assert len(errors) >= 1

    def test_button_with_valid_binding_passes(self):
        """button 有合法 binding.tag 和 tags 声明时通过。"""
        item = ScreenItemSpec(
            id="btn_test", name="btn_test",
            type=ScreenItemType.BUTTON,
            tag_binding="BTN_Test",
            behavior=ButtonBehavior.MOMENTARY,
        )
        project = _make_project(
            [item],
            tags=[TagSpec(name="BTN_Test", data_type="Bool")]
        )
        diags = validate_template_binding_requirements(project)
        errors = [d for d in diags if d.severity == "error"]
        assert len(errors) == 0, f"Unexpected errors: {[(d.code, d.message) for d in errors]}"

    def test_navigate_button_no_binding_ok(self):
        """navigate 按钮不需要 binding.tag。"""
        item = ScreenItemSpec(
            id="btn_nav", name="btn_nav",
            type=ScreenItemType.BUTTON,
            behavior=ButtonBehavior.NAVIGATE,
        )
        project = _make_project([item])
        diags = validate_template_binding_requirements(project)
        errors = [d for d in diags if d.severity == "error"]
        assert len(errors) == 0

    def test_indicator_with_valid_binding_passes(self):
        """indicator 有合法 binding 时通过。"""
        item = ScreenItemSpec(
            id="lmp_test", name="lmp_test",
            type=ScreenItemType.INDICATOR,
            tag_binding="STS_Test",
            indicator_mode=IndicatorMode.BOOL_COLOR,
        )
        project = _make_project(
            [item],
            tags=[TagSpec(name="STS_Test", data_type="Bool")]
        )
        diags = validate_template_binding_requirements(project)
        errors = [d for d in diags if d.severity == "error"]
        assert len(errors) == 0

# -*- coding: utf-8 -*-
"""Tests for template tag leak detection in xml_rewrite_rules.

Covers assert_no_template_tag_leak, ensure_no_placeholder_tags,
and replace_all_tag_references (FunctionList coverage).
"""

import xml.etree.ElementTree as ET

import pytest

from backend.template.xml_rewrite_rules import (
    assert_no_template_tag_leak,
    ensure_no_placeholder_tags,
    replace_all_tag_references,
)


class TestAssertNoTemplateTagLeak:
    """Tests for assert_no_template_tag_leak — the hard block gate."""

    def test_xml_with_template_tag_raises_value_error(self):
        """XML containing a template tag name raises ValueError."""
        xml_str = "<root><ProcessTag>Template_Motor_Speed</ProcessTag></root>"
        root = ET.fromstring(xml_str)
        with pytest.raises(ValueError, match="Template tag leaked"):
            assert_no_template_tag_leak(root, {"Template_Motor_Speed"})

    def test_xml_without_template_tags_passes(self):
        """XML without any template tag names should not raise."""
        xml_str = "<root><ProcessTag>Motor_Speed</ProcessTag></root>"
        root = ET.fromstring(xml_str)
        assert_no_template_tag_leak(root, {"Template_Not_Present"})

    def test_empty_template_tag_set_never_raises(self):
        """Empty set of template tags should never raise even if XML contains
        text that looks like a template tag."""
        xml_str = "<root><ProcessTag>Template_Motor_Speed</ProcessTag></root>"
        root = ET.fromstring(xml_str)
        assert_no_template_tag_leak(root, set())


class TestEnsureNoPlaceholderTags:
    """Tests for ensure_no_placeholder_tags — structural tag inspection."""

    def test_detects_remaining_placeholder_tags(self):
        """Returns list of template tag names still present in known tag elements."""
        xml_str = (
            "<root>"
            "<IOField>"
            "<ProcessTag>Template_Motor_Speed</ProcessTag>"
            "</IOField>"
            "</root>"
        )
        root = ET.fromstring(xml_str)
        remaining = ensure_no_placeholder_tags(root, ["Template_Motor_Speed"])
        assert remaining == ["Template_Motor_Speed"]

    def test_returns_empty_when_no_tags_remain(self):
        """Returns empty list when no placeholder tags are found."""
        xml_str = (
            "<root>"
            "<IOField>"
            "<ProcessTag>Motor_Speed</ProcessTag>"
            "</IOField>"
            "</root>"
        )
        root = ET.fromstring(xml_str)
        remaining = ensure_no_placeholder_tags(root, ["Template_Motor_Speed"])
        assert remaining == []


class TestReplaceAllTagReferences:
    """Tests for replace_all_tag_references — tag reference rewriting."""

    def test_replaces_functionlist_tagname_references(self):
        """TagName inside a FunctionList element should be replaced."""
        xml_str = (
            "<Button>"
            "<Events>"
            "<Event Name='Press'>"
            "<FunctionList>"
            "<TagName>Template_Motor_Start</TagName>"
            "</FunctionList>"
            "</Event>"
            "</Events>"
            "</Button>"
        )
        root = ET.fromstring(xml_str)
        old_tags = ["Template_Motor_Start"]
        new_tag = "Motor_Start"

        count = replace_all_tag_references(root, old_tags, new_tag)

        assert count == 1
        serialized = ET.tostring(root, encoding="unicode")
        assert "Template_Motor_Start" not in serialized
        assert "Motor_Start" in serialized

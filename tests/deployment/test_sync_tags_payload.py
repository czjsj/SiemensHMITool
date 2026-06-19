# -*- coding: utf-8 -*-
"""测试 sync_tags 负载 — 变量创建、更新、跳过、失败。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from backend.domain.ir_v2 import TagSpec
from backend.domain.enums import TagScope
from backend.openness_manager import OpennessManager


class TestSyncTagsPayload:
    """测试变量同步负载生成。"""

    def test_tag_payload_contains_required_fields(self):
        """变量负载包含必要字段。"""
        tag = TagSpec(
            name="BTN_Start",
            data_type="Bool",
            scope=TagScope.INTERNAL,
            table="DefaultTagTable",
        )
        payload = tag.model_dump()

        assert "name" in payload
        assert "data_type" in payload
        assert payload["name"] == "BTN_Start"
        assert payload["data_type"] == "Bool"

    def test_external_tag_payload_with_address(self):
        """外部变量负载含 PLC 地址。"""
        tag = TagSpec(
            name="BTN_Motor_Start",
            data_type="Bool",
            scope=TagScope.EXTERNAL,
            address="DB10.DBX0.0",
            connection="HMI_Connection_1",
        )
        payload = tag.model_dump()

        assert payload["address"] == "DB10.DBX0.0"
        assert payload["connection"] == "HMI_Connection_1"
        assert payload["scope"] == "external"

    def test_tag_with_metadata_pending_mapping(self):
        """待映射变量带有 pending_mapping 标记。"""
        tag = TagSpec(
            name="BTN_Unknown",
            data_type="Bool",
            scope=TagScope.INTERNAL,
            metadata={"pending_mapping": True},
        )
        payload = tag.model_dump()

        assert payload["metadata"]["pending_mapping"] is True

    def test_tag_with_comment_includes_language(self):
        """变量注释含多语言。"""
        tag = TagSpec(
            name="BTN_Start",
            data_type="Bool",
            scope=TagScope.INTERNAL,
            comment={"zh-CN": "启动按钮"},
        )
        payload = tag.model_dump()

        assert "zh-CN" in payload["comment"]
        assert payload["comment"]["zh-CN"] == "启动按钮"

    def test_multiple_tags_unique_payloads(self):
        """多个变量的负载不重复。"""
        tag1 = TagSpec(name="Tag_A", data_type="Bool", scope=TagScope.INTERNAL)
        tag2 = TagSpec(name="Tag_B", data_type="Real", scope=TagScope.EXTERNAL, address="DB10.DBD4")

        p1 = tag1.model_dump()
        p2 = tag2.model_dump()

        assert p1["name"] != p2["name"]
        assert p1["data_type"] != p2["data_type"]

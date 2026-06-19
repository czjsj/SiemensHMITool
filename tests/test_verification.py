# -*- coding: utf-8 -*-
"""测试 Verification Service (PR-11) 和 Catalog Service."""
import sys, os, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.domain.ir_v2 import HmiProjectSpec, TagSpec, ScreenSpec, ScreenItemSpec, GeometrySpec, EventSpec, ActionSpec, BindingSpec, ScriptSpec
from backend.domain.enums import TagScope, ScreenItemType, BindingKind, SemanticEvent, SemanticActionType
from backend.services.verification_service import VerificationService
from backend.references.catalog_service import CatalogService


class TestVerificationService:
    def test_verify_tags_all_found(self):
        svc = VerificationService()
        result = svc.verify_tags(["Tag1", "Tag2"], ["Tag1", "Tag2"])
        assert result.failed == []

    def test_verify_tags_missing(self):
        svc = VerificationService()
        result = svc.verify_tags(["Tag1", "Tag2"], ["Tag1"])
        assert "Tag2" in result.failed

    def test_verify_screens(self):
        svc = VerificationService()
        result = svc.verify_screens(["Screen1", "Screen2"], ["Screen1", "Screen2", "Screen3"])
        assert result.failed == []
        assert result.found == 3

    def test_verify_screens_missing(self):
        svc = VerificationService()
        result = svc.verify_screens(["Screen1"], [])
        assert result.failed == ["Screen1"]

    def test_verify_events(self):
        svc = VerificationService()
        expected = [("BTN_Start", "press", 1), ("BTN_Start", "release", 1)]
        found = [("BTN_Start", "press", 1)]
        result = svc.verify_events(expected, found)
        assert len(result.failed) == 1

    def test_verify_bindings(self):
        svc = VerificationService()
        expected = [("STS_Run", "background_color", "discrete")]
        found = [("STS_Run", "background_color", "discrete")]
        result = svc.verify_bindings(expected, found)
        assert result.failed == []

    def test_verify_scripts(self):
        svc = VerificationService()
        result = svc.verify_scripts(["Sub_Toggle", "Sub_Complex"], ["Sub_Toggle"])
        assert "Sub_Complex" in result.failed

    def test_verify_compile_ok(self):
        svc = VerificationService()
        result = svc.verify_compile(0, 0)
        assert result.errors == 0

    def test_verify_full_success(self):
        svc = VerificationService()
        spec = HmiProjectSpec(
            tags=[TagSpec(name="Motor_Start", data_type="Bool", scope=TagScope.EXTERNAL)],
            screens=[ScreenSpec(name="MainScreen", width=800, height=480, items=[
                ScreenItemSpec(id="BTN_Start", name="Start", type=ScreenItemType.BUTTON,
                               geometry=GeometrySpec(x=10, y=10, width=120, height=50), tag_binding="Motor_Start",
                               events=[EventSpec(event=SemanticEvent.PRESS, actions=[ActionSpec(type=SemanticActionType.SET_BIT, tag="Motor_Start")])],
                               bindings=[BindingSpec(property="value", kind=BindingKind.DIRECT_TAG, source_tag="Motor_Start")]),
            ])],
        )
        object_query = {
            "tags": ["Motor_Start"],
            "screens": ["MainScreen"],
            "events": [("BTN_Start", "press", 1)],
            "bindings": [("BTN_Start", "value", "direct_tag")],
            "scripts": [],
            "compile": {"errors": 0, "warnings": 0},
        }
        result = svc.verify_full(spec, object_query)
        assert isinstance(result, str) or hasattr(result, 'success')
        assert result.tags.failed == []
        assert result.screens.failed == []

    def test_verify_full_with_missing_tags(self):
        svc = VerificationService()
        spec = HmiProjectSpec(
            tags=[TagSpec(name="MissingTag", data_type="Bool")],
            screens=[ScreenSpec(name="S1", width=800, height=480)],
        )
        object_query = {"tags": [], "screens": ["S1"], "events": [], "bindings": [], "scripts": [], "compile": {"errors": 0}}
        result = svc.verify_full(spec, object_query)
        assert result.tags.failed == ["MissingTag"]


class TestCatalogService:
    def test_load_manifests(self):
        svc = CatalogService()
        manifests = svc.load_all()
        # 至少加载了测试用的 2 个 manifest
        assert len(manifests) >= 2

    def test_find_manifest(self):
        svc = CatalogService()
        m = svc.find("V20", "comfort", "TP1200 Comfort")
        assert m is not None
        assert m.key["family"] == "comfort"

    def test_find_basic_manifest(self):
        svc = CatalogService()
        m = svc.find("V20", "basic")
        assert m is not None
        assert m.key["family"] == "basic"

    def test_validate_all(self):
        svc = CatalogService()
        svc.load_all()
        results = svc.validate_all()
        assert isinstance(results, dict)
        # 缺少 fragment 文件有错误（黄金 XML 示例尚未创建）
        # 但服务本身不应崩溃

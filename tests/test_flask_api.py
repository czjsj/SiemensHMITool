# -*- coding: utf-8 -*-
"""测试 Flask API 端点（使用 Flask test client）。"""
import pytest
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app


@pytest.fixture
def client():
    """Flask 测试客户端。"""
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestConfigApi:
    """配置相关 API。"""

    def test_get_config(self, client):
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "config" in data
        assert "raw" in data

    def test_get_config_has_generation_mode(self, client):
        """配置中应包含 generation_mode 字段。"""
        resp = client.get("/api/config")
        data = json.loads(resp.data)
        cfg = data["config"]
        assert "generation_mode" in cfg.get("openness", {})
        assert "classic_template" in cfg.get("openness", {})
        assert "unified_direct" in cfg.get("openness", {})


class TestOpennessApi:
    """Openness 相关 API。"""

    def test_capabilities_endpoint_returns_json(self, client):
        """GET /api/openness/capabilities 返回 JSON。"""
        resp = client.get("/api/openness/capabilities")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "connected" in data
        assert "hmi_software_type" in data
        assert "recommended_mode" in data

    def test_diagnose_endpoint(self, client):
        resp = client.get("/api/openness/diagnose")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "os" in data
        assert "ready" in data

    def test_export_template_endpoint_no_screen_name(self, client):
        """不带 screen_name 时应能处理（导出第一个画面或返回错误）。"""
        resp = client.post("/api/openness/export-template",
                          data=json.dumps({"screen_name": "", "overwrite": True}),
                          content_type="application/json")
        # 未连接 TIA 时返回 400/500，关键是不要 500 崩溃且返回 JSON
        assert resp.status_code in (200, 400, 500)
        data = json.loads(resp.data)
        assert "ok" in data
        if not data["ok"]:
            assert "message" in data

    def test_export_reference_endpoint_returns_json(self, client):
        """export-reference 端点应返回 JSON 格式错误。"""
        resp = client.post("/api/openness/export-reference",
                          data=json.dumps({}),
                          content_type="application/json")
        assert resp.status_code in (200, 400, 500)
        data = json.loads(resp.data)
        assert "ok" in data

    def test_status_endpoint(self, client):
        """兼容旧 /api/openness/status 端点。"""
        resp = client.get("/api/openness/status")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "connected" in data

    def test_tia_status_endpoint(self, client):
        """兼容旧 /api/tia/status 端点。"""
        resp = client.get("/api/tia/status")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "connected" in data


class TestBuildApi:
    """生成相关 API。"""

    def test_build_template_xml_requires_ir(self, client):
        """无 ir 数据时应返回 400。"""
        resp = client.post("/api/build/template-xml",
                          data=json.dumps({}),
                          content_type="application/json")
        assert resp.status_code == 400

    def test_build_template_xml_invalid_template_path(self, client):
        """无效的模板路径应返回 400。"""
        ir = {
            "meta": {"screen_name": "Test"},
            "objects": [{"id": "TXT_A", "type": "Text", "x": 0, "y": 0, "text": "A"}],
        }
        resp = client.post("/api/build/template-xml",
                          data=json.dumps({"ir": ir, "template_xml_path": "/nonexistent/path.xml"}),
                          content_type="application/json")
        assert resp.status_code == 400

    def test_build_endpoint_with_valid_ir(self, client):
        """旧 /api/build 端点仍正常工作。"""
        ir = {
            "meta": {"screen_name": "Test_Screen"},
            "objects": [{"id": "TXT_Hello", "type": "Text", "x": 10, "y": 20, "text": "你好"}],
        }
        resp = client.post("/api/build",
                          data=json.dumps({"raw_output": json.dumps(ir)}),
                          content_type="application/json")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data.get("ok") is True
        assert "ir" in data
        assert "xml" in data
        assert "xml_path" in data

    def test_import_endpoint_with_ir_and_mode(self, client):
        """/api/openness/import 接受 IR + mode 请求格式。"""
        ir = {
            "meta": {"screen_name": "Test_Import"},
            "objects": [{"id": "TXT_A", "type": "Text", "x": 0, "y": 0, "text": "A"}],
        }
        resp = client.post("/api/openness/import",
                          data=json.dumps({"ir": ir, "mode": "auto"}),
                          content_type="application/json")
        # 会返回错误（因为没连 TIA），但不应 500 崩溃
        assert resp.status_code in (200, 400)
        data = json.loads(resp.data)
        # 新模式返回包含 mode 字段
        assert "mode" in data or "imported" in data

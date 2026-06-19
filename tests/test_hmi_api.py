# -*- coding: utf-8 -*-
"""测试 PR-03 新增的 /api/hmi/* 端点。"""
import sys
import os
import pytest
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestHmiPlanApi:
    """/api/hmi/plan 端点测试。"""

    def test_plan_requires_project(self, client):
        """缺少 project 字段时返回 400。"""
        resp = client.post("/api/hmi/plan",
                          data=json.dumps({"options": {"dry_run": True}}),
                          content_type="application/json")
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert "ok" in data
        assert not data["ok"]

    def test_plan_minimal_project(self, client):
        """最小 project 可生成 plan。"""
        project = {
            "schema_version": "2.0",
            "target": {"family": "comfort", "tia_version": "V18"},
            "tags": [
                {"name": "Tag_A", "data_type": "Bool", "scope": "internal"},
            ],
            "screens": [
                {
                    "name": "MainScreen",
                    "width": 800,
                    "height": 480,
                    "items": [
                        {
                            "id": "TXT_Hello",
                            "name": "TXT_Hello",
                            "type": "text",
                            "geometry": {"x": 10, "y": 20, "width": 200, "height": 40},
                            "text": {"zh-CN": "Hello"},
                        },
                    ],
                },
            ],
        }
        resp = client.post("/api/hmi/plan",
                          data=json.dumps({"project": project, "options": {"dry_run": True}}),
                          content_type="application/json")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["ok"] is True
        assert "plan" in data
        plan = data["plan"]
        assert plan["dry_run"] is True
        assert len(plan["steps"]) > 0

    def test_plan_motor_control(self, client):
        """完整电机控制画面生成 plan。"""
        project = {
            "schema_version": "2.0",
            "target": {"family": "comfort", "tia_version": "V18"},
            "tags": [
                {"name": "Motor_Start", "data_type": "Bool", "scope": "external"},
                {"name": "Motor_Running", "data_type": "Bool", "scope": "external"},
                {"name": "Motor_Speed", "data_type": "Real", "scope": "external"},
            ],
            "screens": [
                {
                    "name": "MotorControl",
                    "width": 800,
                    "height": 480,
                    "items": [
                        {
                            "id": "BTN_Start",
                            "name": "StartBtn",
                            "type": "button",
                            "geometry": {"x": 50, "y": 80, "width": 100, "height": 50},
                            "tag_binding": "Motor_Start",
                            "events": [
                                {"event": "press", "actions": [{"type": "set_bit", "tag": "Motor_Start", "value": 1}]},
                                {"event": "release", "actions": [{"type": "reset_bit", "tag": "Motor_Start", "value": 0}]},
                            ],
                        },
                        {
                            "id": "STS_Run",
                            "name": "RunIndicator",
                            "type": "indicator",
                            "geometry": {"x": 80, "y": 200, "width": 44, "height": 44, "radius": 22},
                            "tag_binding": "Motor_Running",
                            "bindings": [
                                {
                                    "property": "background_color",
                                    "kind": "discrete",
                                    "source_tag": "Motor_Running",
                                    "config": {"states": [{"value": 0, "output": "#3A4250"}, {"value": 1, "output": "#27D17F"}]},
                                },
                            ],
                        },
                    ],
                },
            ],
        }
        resp = client.post("/api/hmi/plan",
                          data=json.dumps({"project": project, "options": {"dry_run": True}}),
                          content_type="application/json")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["ok"] is True

    def test_plan_invalid_json(self, client):
        """无效 JSON 返回 400。"""
        resp = client.post("/api/hmi/plan",
                          data="not json",
                          content_type="application/json")
        assert resp.status_code == 400


class TestHmiCapabilitiesApi:
    """/api/hmi/capabilities 端点测试。"""

    def test_capabilities_default(self, client):
        resp = client.get("/api/hmi/capabilities")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["ok"] is True
        assert "capabilities" in data
        assert "family" in data

    def test_capabilities_with_family(self, client):
        resp = client.get("/api/hmi/capabilities?family=basic&tia_version=V16")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["family"] == "basic"
        caps = data["capabilities"]
        assert caps.get("VBS") == "no"


class TestHmiRuntimeMetadataApi:
    """/api/hmi/runtime-metadata 端点测试。"""

    def test_runtime_metadata(self, client):
        resp = client.get("/api/hmi/runtime-metadata")
        # 未连接 TIA 时也能正常返回 JSON（含 diagnose）
        assert resp.status_code in (200, 500)
        data = json.loads(resp.data)
        assert "ok" in data

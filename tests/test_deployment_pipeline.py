# -*- coding: utf-8 -*-
"""E2E 测试: V3 统一部署流水线 + 新 API 端点。

测试内容:
  - Part 2: /api/hmi/validate, /api/hmi/deploy, /api/hmi/verify, /api/hmi/compile
  - Part 3: DRY_RUN vs NOT_CONNECTED vs 真实执行边界
  - Part 4: CATALOG_INCOMPLETE 阻断
  - Part 5: Unified RuntimeContract
  - Part 6: VerificationService 语义验证
  - BackendFactory 路由到三个后端
"""
import sys, os, json, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from backend.domain.ir_v2 import (
    HmiProjectSpec, TargetSpec, ScreenSpec, ScreenItemSpec, GeometrySpec,
    TagSpec, EventSpec, ActionSpec, BindingSpec, ScriptSpec,
)
from backend.domain.enums import (
    HmiFamily, TagScope, ScreenItemType, BindingKind,
    SemanticEvent, SemanticActionType, ScriptLanguage, DiagnosticSeverity,
    DeploymentStatus,
)
from backend.services.deployment_service import (
    DeploymentService, BackendFactory, RuntimeContext, StepLog,
)
from backend.backends.classic.comfort_backend import ComfortBackend
from backend.backends.classic.basic_backend import BasicBackend
from backend.backends.unified.unified_backend import UnifiedBackend
from backend.openness.runtime_contract import RuntimeContract, RuntimeProber
from backend.services.verification_service import VerificationService


# ── fixtures ──────────────────────────────────────────────────────────

def make_motor_control_project(family=HmiFamily.COMFORT):
    return HmiProjectSpec(
        target=TargetSpec(family=family, tia_version="V18"),
        tags=[
            TagSpec(name="Motor_Start", data_type="Bool", scope=TagScope.EXTERNAL),
            TagSpec(name="Motor_Running", data_type="Bool", scope=TagScope.EXTERNAL),
            TagSpec(name="Motor_Speed", data_type="Real", scope=TagScope.EXTERNAL),
        ],
        screens=[ScreenSpec(name="MotorControl", width=800, height=480, items=[
            ScreenItemSpec(id="BTN_Start", name="Start", type=ScreenItemType.BUTTON,
                           geometry=GeometrySpec(x=50, y=80, width=100, height=50),
                           tag_binding="Motor_Start",
                           events=[
                               EventSpec(event=SemanticEvent.PRESS, actions=[
                                   ActionSpec(type=SemanticActionType.SET_BIT, tag="Motor_Start", value=1)]),
                               EventSpec(event=SemanticEvent.RELEASE, actions=[
                                   ActionSpec(type=SemanticActionType.RESET_BIT, tag="Motor_Start", value=0)]),
                           ]),
            ScreenItemSpec(id="STS_Run", name="Run", type=ScreenItemType.INDICATOR,
                           geometry=GeometrySpec(x=80, y=200, width=44, height=44, radius=22),
                           tag_binding="Motor_Running",
                           bindings=[
                               BindingSpec(property="background_color", kind=BindingKind.DISCRETE,
                                           source_tag="Motor_Running",
                                           config={"states": [
                                               {"value": 0, "output": "#3A4250"},
                                               {"value": 1, "output": "#27D17F"},
                                           ]}),
                           ]),
        ])],
    )


# ── Part 2: BackendFactory ──────────────────────────────────────────────

class TestBackendFactory:
    def test_routes_to_basic(self):
        be, name = BackendFactory.create(TargetSpec(family=HmiFamily.BASIC))
        assert isinstance(be, BasicBackend)
        assert name == "basic_classic"

    def test_routes_to_comfort(self):
        be, name = BackendFactory.create(TargetSpec(family=HmiFamily.COMFORT))
        assert isinstance(be, ComfortBackend)
        assert name == "comfort_classic"

    def test_routes_to_unified(self):
        be, name = BackendFactory.create(TargetSpec(family=HmiFamily.UNIFIED))
        assert isinstance(be, UnifiedBackend)
        assert name == "unified_direct"

    def test_auto_falls_back_to_comfort(self):
        be, name = BackendFactory.create(TargetSpec(family=HmiFamily.AUTO))
        # V4.2: AUTO 无连接时返回 (None, "unknown") 以阻断部署
        assert be is None
        assert name == "unknown"


# ── Part 3: execute() 边界 ──────────────────────────────────────────────

class TestExecuteBoundary:
    """V3.2 区分 DRY_RUN vs NOT_CONNECTED vs 真实执行。

    状态机规则:
      - dry_run=true: 不需要连接，计划验证通过 → DRY_RUN, success=True
      - dry_run=false + 无连接: NOT_CONNECTED, success=False
      - dry_run=false + 有连接 + 无 hmi_sw: FAILED, success=False
      - 只有真实 TIA 修改完成 + 编译 Error=0: DEPLOYED
    """

    def test_comfort_dry_run_returns_dry_run_status(self):
        """dry_run=true 不要求 TIA 连接，计划成功则 success=True。"""
        be = ComfortBackend()
        from backend.domain.deployment_plan import DeploymentPlan
        plan = DeploymentPlan(plan_id="test-1", target=TargetSpec(family=HmiFamily.COMFORT), dry_run=True)
        result = be.execute(plan)
        assert result.success is True, "dry_run should succeed without connection"
        assert result.status == DeploymentStatus.DRY_RUN

    def test_basic_dry_run_returns_dry_run_status(self):
        be = BasicBackend()
        from backend.domain.deployment_plan import DeploymentPlan
        plan = DeploymentPlan(plan_id="test-2", target=TargetSpec(family=HmiFamily.BASIC), dry_run=True)
        result = be.execute(plan)
        assert result.success is True
        assert result.status == DeploymentStatus.DRY_RUN

    def test_unified_dry_run_returns_dry_run_status(self):
        be = UnifiedBackend()
        from backend.domain.deployment_plan import DeploymentPlan
        plan = DeploymentPlan(plan_id="test-3", target=TargetSpec(family=HmiFamily.UNIFIED), dry_run=True)
        result = be.execute(plan)
        assert result.success is True
        assert result.status == DeploymentStatus.DRY_RUN

    def test_comfort_not_connected_without_dry_run(self):
        """dry_run=false 且未连接时返回 NOT_CONNECTED。"""
        be = ComfortBackend()
        from backend.domain.deployment_plan import DeploymentPlan
        plan = DeploymentPlan(plan_id="test-nc", target=TargetSpec(family=HmiFamily.COMFORT), dry_run=False)
        result = be.execute(plan)  # no context → NOT_CONNECTED
        assert result.success is False
        assert result.status == DeploymentStatus.NOT_CONNECTED
        assert any(d.code == "NOT_CONNECTED" for d in result.diagnostics)

    def test_execute_with_connection_but_no_hmi_sw_returns_failed(self):
        """connected=True 但无 hmi_software 时无法定位目标设备 → FAILED。"""
        be = ComfortBackend()
        from backend.domain.deployment_plan import DeploymentPlan, DeploymentStep
        plan = DeploymentPlan(plan_id="test-fail", target=TargetSpec(family=HmiFamily.COMFORT), dry_run=False,
                              steps=[DeploymentStep(id="s1", phase="P30", operation="create_or_update", target_type="tag", target_name="X")])
        result = be.execute(plan, context={"connected": True, "openness_manager": object()})
        assert result.success is False
        assert result.status == DeploymentStatus.FAILED
        assert any(d.code == "TIA_NOT_CONNECTED" for d in result.diagnostics)

    def test_verify_no_connection_all_backends(self):
        """所有三个后端在无连接时 verify 返回 success=False。"""
        for be in [ComfortBackend(), BasicBackend(), UnifiedBackend()]:
            result = be.verify(HmiProjectSpec(target=TargetSpec(family=HmiFamily.COMFORT)))
            assert result.success is False, f"{type(be).__name__} should fail when not connected"

    def test_verify_with_connection_but_no_hmi_sw_fails(self):
        """connected=True 但无 hmi_sw 时 verify 返回失败。"""
        be = ComfortBackend()
        spec = HmiProjectSpec(
            target=TargetSpec(family=HmiFamily.COMFORT),
            tags=[TagSpec(name="X", data_type="Bool")],
            screens=[ScreenSpec(name="S1", width=800, height=480)],
        )
        result = be.verify(spec, context={"connected": True})
        assert result.success is False  # no hmi_sw → can't query TIA objects


# ── Part 2+3: DeploymentService 流水线 ──────────────────────────────────

class TestDeploymentServicePipeline:
    def test_validate_passes_clean_project(self):
        spec = make_motor_control_project(HmiFamily.COMFORT)
        svc = DeploymentService()
        result = svc.validate(spec)
        assert result["ok"] is True
        assert result["error_count"] == 0

    def test_deploy_dry_run_returns_dry_run_mode(self):
        """Unified 不需要 catalog，可正常完成 dry-run。"""
        spec = make_motor_control_project(HmiFamily.UNIFIED)
        ctx = RuntimeContext(connected=False)
        svc = DeploymentService(ctx)
        result = svc.deploy(spec)
        assert result["ok"] is True
        assert result.get("mode") == "DRY_RUN"
        assert "计划验证通过" in result.get("message", "")

    def test_deploy_not_connected_returns_error(self):
        """Comfort 缺 catalog 时 deploy 返回失败。"""
        spec = make_motor_control_project(HmiFamily.COMFORT)
        ctx = RuntimeContext(connected=False)
        svc = DeploymentService(ctx)
        result = svc.deploy(spec)
        # catalog 不完整 → deploy 被阻断
        assert not result["ok"]
        assert any(d.get("code", "").startswith("CATALOG_") for d in result.get("diagnostics", []))

    def test_deploy_all_three_families(self):
        """验证 BackendFactory 正确路由。"""
        for family, expected_backend in [
            (HmiFamily.COMFORT, "comfort_classic"),
            (HmiFamily.BASIC, "basic_classic"),
            (HmiFamily.UNIFIED, "unified_direct"),
        ]:
            spec = make_motor_control_project(family)
            ctx = RuntimeContext(connected=False)
            svc = DeploymentService(ctx)
            result = svc.deploy(spec)
            assert result["backend"] == expected_backend, f"{family}: expected {expected_backend}, got {result['backend']}"

    def test_deploy_returns_step_count_for_unified(self):
        """Unified family 的 deploy summary 包含计数。"""
        spec = make_motor_control_project(HmiFamily.UNIFIED)
        ctx = RuntimeContext(connected=False)
        svc = DeploymentService(ctx)
        result = svc.deploy(spec)
        assert result.get("summary", {}).get("tags", 0) > 0


# ── Part 4: Catalog 阻断 ────────────────────────────────────────────────

class TestCatalogBlocking:
    def test_deploy_blocks_on_catalog_incomplete(self):
        """Classic family 的 catalog 未验证 → deploy 返回失败 + CATALOG 诊断。"""
        spec = make_motor_control_project(HmiFamily.COMFORT)
        ctx = RuntimeContext(connected=False)
        svc = DeploymentService(ctx)
        result = svc.deploy(spec)
        # catalog 文件缺失且未验证 → 应有 CATALOG_INCOMPLETE 错误
        diags = result.get("diagnostics", [])
        catalog_errors = [d for d in diags if d.get("code", "").startswith("CATALOG_")]
        assert not result["ok"]
        assert len(catalog_errors) > 0, f"Expected catalog blocking errors, got diags={diags}"

    def test_unified_family_skips_catalog_check(self):
        """Unified 不走 Classic catalog，不产生 CATALOG 阻断。"""
        spec = make_motor_control_project(HmiFamily.UNIFIED)
        ctx = RuntimeContext(connected=False)
        svc = DeploymentService(ctx)
        result = svc.deploy(spec)
        diags = result.get("diagnostics", [])
        catalog_errors = [d for d in diags if d.get("code", "").startswith("CATALOG_")]
        assert len(catalog_errors) == 0, f"Unified should not have catalog errors: {catalog_errors}"


# ── Part 5: Unified RuntimeContract ─────────────────────────────────────

class TestRuntimeContract:
    def test_no_pythonnet_returns_errors(self):
        """无 pythonnet 时 probe 返回带 errors 的 contract。"""
        prober = RuntimeProber()
        contract = prober.probe(tia_version="V20", dll_path=r"C:\nonexistent.dll")
        assert len(contract.errors) > 0

    def test_contract_serialization(self):
        contract = RuntimeContract(
            tia_version="V20",
            assembly_hash="abc123",
            types=["HmiButton", "HmiIOField"],
            create_methods=["HmiButton.Create"],
            properties={"HmiButton": ["Left", "Top", "Width", "Height"]},
            event_enums={"Press": ["Pressed", "PointerDown"]},
        )
        d = contract.to_dict()
        assert d["tia_version"] == "V20"
        assert len(d["types"]) == 2

    def test_contract_is_empty(self):
        assert RuntimeContract().is_empty


# ── Part 6: VerificationService 语义验证 ───────────────────────────────

class TestVerificationServiceSemantic:
    def test_verify_without_connection_fails(self):
        svc = VerificationService()
        spec = make_motor_control_project()
        result = svc.verify_full(spec, {}, connected=False)
        assert result.success is False
        assert "NOT_CONNECTED" in result.compile.messages[0]

    def test_verify_tags_semantic_type_mismatch(self):
        svc = VerificationService()
        specs = [TagSpec(name="X", data_type="Real", scope=TagScope.EXTERNAL)]
        found = [{"name": "X", "data_type": "Bool", "connection": "PLC_1"}]
        result = svc._verify_tags_semantic(specs, found)
        assert len(result.failed) == 1
        assert "type mismatch" in result.failed[0]

    def test_verify_tags_semantic_ok(self):
        svc = VerificationService()
        specs = [TagSpec(name="X", data_type="Real", scope=TagScope.INTERNAL)]
        found = [{"name": "X", "data_type": "Real"}]
        result = svc._verify_tags_semantic(specs, found)
        assert result.failed == []

    def test_verify_events_semantic(self):
        svc = VerificationService()
        spec = make_motor_control_project()
        found = [{"item_id": "BTN_Start", "event": "press", "action_type": "set_bit"}]
        result = svc._verify_events_semantic(spec, found)
        # should catch that release event is missing
        assert len(result.failed) > 0

    def test_verify_bindings_semantic(self):
        svc = VerificationService()
        spec = make_motor_control_project()
        found = [{"item_id": "STS_Run", "property": "background_color", "kind": "discrete", "source_tag": "Motor_Running"}]
        result = svc._verify_bindings_semantic(spec, found)
        assert result.failed == []


# ── 新 API 端点测试 ─────────────────────────────────────────────────────

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestNewDeploymentEndpoints:
    def test_validate_endpoint(self, client):
        resp = client.post("/api/hmi/validate",
                          data=json.dumps({"project": make_motor_control_project().model_dump()}),
                          content_type="application/json")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "ok" in data
        assert "diagnostics" in data

    def test_deploy_endpoint_legacy_ir(self, client):
        legacy = {
            "meta": {"screen_name": "Test", "hmi_type": "Comfort"},
            "objects": [{"id": "TXT_A", "type": "Text", "x": 10, "y": 20, "text": "A"}],
        }
        resp = client.post("/api/hmi/deploy",
                          data=json.dumps({"legacy_ir": legacy, "mode": "auto"}),
                          content_type="application/json")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "backend" in data

    def test_deploy_endpoint_v2_project(self, client):
        project = make_motor_control_project(HmiFamily.COMFORT)
        resp = client.post("/api/hmi/deploy",
                          data=json.dumps({"project": project.model_dump(), "mode": "v2"}),
                          content_type="application/json")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "backend" in data
        assert data["backend"] == "comfort_classic"

    def test_deploy_endpoint_missing_project(self, client):
        resp = client.post("/api/hmi/deploy",
                          data=json.dumps({}),
                          content_type="application/json")
        assert resp.status_code == 400

    def test_verify_endpoint(self, client):
        project = make_motor_control_project()
        resp = client.post("/api/hmi/verify",
                          data=json.dumps({"project": project.model_dump()}),
                          content_type="application/json")
        assert resp.status_code in (200, 500)
        data = json.loads(resp.data)
        assert "ok" in data
        assert "verification" in data

    def test_compile_endpoint(self, client):
        resp = client.post("/api/hmi/compile",
                          data=json.dumps({}),
                          content_type="application/json")
        assert resp.status_code in (200, 500)
        data = json.loads(resp.data)
        assert "ok" in data

    def test_deploy_all_three_families_via_api(self, client):
        """通过 API 验证三个 family 路由到正确 backend。"""
        for family, expected in [
            ("comfort", "comfort_classic"),
            ("basic", "basic_classic"),
            ("unified", "unified_direct"),
        ]:
            project = make_motor_control_project(HmiFamily(family))
            resp = client.post("/api/hmi/deploy",
                              data=json.dumps({"project": project.model_dump(), "mode": "v2"}),
                              content_type="application/json")
            assert resp.status_code == 200
            data = json.loads(resp.data)
            assert data["backend"] == expected, f"Family {family}: expected {expected}, got {data['backend']}"

    def test_validate_rejects_duplicate_tags(self, client):
        project = HmiProjectSpec(
            target=TargetSpec(family=HmiFamily.COMFORT),
            tags=[TagSpec(name="Same", data_type="Bool"), TagSpec(name="Same", data_type="Real")],
            screens=[ScreenSpec(name="S1", width=800, height=480)],
        )
        resp = client.post("/api/hmi/validate",
                          data=json.dumps({"project": project.model_dump()}),
                          content_type="application/json")
        data = json.loads(resp.data)
        assert data["ok"] is False
        assert data["error_count"] > 0

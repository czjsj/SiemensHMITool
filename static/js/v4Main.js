/**
 * V4.0 前端主控制器 — 集成 HMI 自动生成与部署工作台
 *
 * 与现有 app.js 协同工作，不删除旧功能。
 * 向全局暴露 V4 API 供 app.js 中的按钮调用。
 */
import * as GenStore from './stores/hmiGenerationStore.js';
import * as DepStore from './stores/deploymentStore.js';
import * as TmplStore from './stores/templateStore.js';
import * as OpenStore from './stores/opennessStore.js';
import { validateHmiSpec, getDeploymentPlan, deployHmi, verifyHmi, compileHmi, getHmiCapabilities, getGenerationSummary } from './api/hmi.js';
import { getOpennessStatus, diagnoseOpenness, connectOpenness, disconnectOpenness } from './api/openness.js';
import { extractTagsFromSpecOrIr, extractBindingsFromSpecOrIr, extractPreviewImage } from './adapters/hmiAdapter.js';
import { normalizeDiagnostics } from './adapters/diagnosticAdapter.js';
import { normalizeDeploymentStatus, getStatusLabel, isSuccessStatus } from './adapters/deploymentAdapter.js';
import { renderDiagnosticsPanel } from './components/DiagnosticsPanel.js';
import { renderVariableTable } from './components/VariableTable.js';
import { renderBindingTable } from './components/BindingTable.js';
import { renderDeploymentPlanTimeline } from './components/DeploymentPlanTimeline.js';
import { renderDeploymentStatusPanel } from './components/DeploymentStatusPanel.js';
import { renderCompileResultPanel } from './components/CompileResultPanel.js';
import { renderVerificationResultPanel } from './components/VerificationResultPanel.js';
import { renderTemplateUploader } from './components/TemplateUploader.js';
import { renderTemplatePrototypePanel } from './components/TemplatePrototypePanel.js';
import { renderCapabilityPanel } from './components/CapabilityPanel.js';
import { normalizeHmiType } from './types/hmi.js';

// ============================================================
// V4 DOM 容器引用
// ============================================================
function $(s) { return document.querySelector(s); }

const V4_CONTAINERS = {
  variableTable: '#v4VariableTable',
  bindingTable: '#v4BindingTable',
  deploymentTimeline: '#v4DeploymentTimeline',
  deploymentStatus: '#v4DeploymentStatus',
  compileResult: '#v4CompileResult',
  verificationResult: '#v4VerificationResult',
  diagnosticsPanel: '#v4DiagnosticsPanel',
  templateUploader: '#v4TemplateUploader',
  templatePrototypePanel: '#v4TemplatePrototypePanel',
  capabilityPanel: '#v4CapabilityPanel',
  targetFamily: '#v4TargetFamily',
  targetTiaVersion: '#v4TargetTiaVersion',
  targetDevice: '#v4TargetDevice',
  dryRunToggle: '#v4DryRunToggle',
  btnValidate: '#v4BtnValidate',
  btnPlan: '#v4BtnPlan',
  btnDeploy: '#v4BtnDeploy',
  btnCompile: '#v4BtnCompile',
  btnVerify: '#v4BtnVerify',
  btnResetDeploy: '#v4BtnReset',
};

// ============================================================
// UI 刷新
// ============================================================
function refreshVariableTable() {
  const el = $(V4_CONTAINERS.variableTable);
  if (!el) return;
  const state = GenStore.getState();
  const tags = extractTagsFromSpecOrIr(state.ir || state.projectSpec || {});
  el.innerHTML = renderVariableTable({ tags });
}

function refreshBindingTable() {
  const el = $(V4_CONTAINERS.bindingTable);
  if (!el) return;
  const state = GenStore.getState();
  const bindings = extractBindingsFromSpecOrIr(state.ir || state.projectSpec || {});
  el.innerHTML = renderBindingTable({ bindings });
}

function refreshDeploymentTimeline() {
  const el = $(V4_CONTAINERS.deploymentTimeline);
  if (!el) return;
  const state = DepStore.getState();
  el.innerHTML = renderDeploymentPlanTimeline({
    plan: state.plan,
    currentPhase: state.status,
  });
}

function refreshDeploymentStatus() {
  const el = $(V4_CONTAINERS.deploymentStatus);
  if (!el) return;
  const state = DepStore.getState();
  el.innerHTML = renderDeploymentStatusPanel({
    status: state.status,
    result: state.deploymentResult,
    diagnostics: state.diagnostics,
  });
}

function refreshCompileResult() {
  const el = $(V4_CONTAINERS.compileResult);
  if (!el) return;
  const state = DepStore.getState();
  el.innerHTML = renderCompileResultPanel({ compileResult: state.compileResult });
}

function refreshVerificationResult() {
  const el = $(V4_CONTAINERS.verificationResult);
  if (!el) return;
  const state = DepStore.getState();
  const openState = OpenStore.getState();
  el.innerHTML = renderVerificationResultPanel({
    verificationResult: state.verificationResult,
    tiaConnected: openState.connected,
  });
}

function refreshDiagnosticsPanel() {
  const el = $(V4_CONTAINERS.diagnosticsPanel);
  if (!el) return;
  const all = [
    ...GenStore.getState().diagnostics,
    ...DepStore.getState().diagnostics,
  ];
  el.innerHTML = renderDiagnosticsPanel({ diagnostics: normalizeDiagnostics(all), title: '全部诊断' });
}

function refreshTemplateUploader() {
  const el = $(V4_CONTAINERS.templateUploader);
  if (!el) return;
  const state = TmplStore.getState();
  el.innerHTML = renderTemplateUploader({ templateXml: state.templateXml, templateSource: state.templateSource });
}

function refreshTemplatePrototypePanel() {
  const el = $(V4_CONTAINERS.templatePrototypePanel);
  if (!el) return;
  const state = TmplStore.getState();
  el.innerHTML = renderTemplatePrototypePanel({
    buttonPrototypes: state.buttonPrototypes,
    indicatorPrototypes: state.indicatorPrototypes,
    diagnostics: state.diagnostics,
  });
}

function refreshCapabilityPanel() {
  const el = $(V4_CONTAINERS.capabilityPanel);
  if (!el) return;
  const openState = OpenStore.getState();
  el.innerHTML = renderCapabilityPanel({
    capabilities: openState.capabilities,
    runtimeMetadata: openState.runtimeMetadata,
  });
}

function refreshAll() {
  refreshTemplateUploader();
  refreshTemplatePrototypePanel();
  refreshCapabilityPanel();
  refreshVariableTable();
  refreshBindingTable();
  refreshDeploymentTimeline();
  refreshDeploymentStatus();
  refreshCompileResult();
  refreshVerificationResult();
  refreshDiagnosticsPanel();
}

// ============================================================
// V4 Actions
// ============================================================

/** 校验 */
export async function v4Validate() {
  const genState = GenStore.getState();
  const depState = DepStore.getState();

  if (!genState.ir && !genState.projectSpec) {
    DepStore.addDiagnostics([{ severity: 'error', phase: 'validate', message: '先生成 IR 或项目规格' }]);
    refreshDiagnosticsPanel();
    return;
  }

  DepStore.startDeploying(); // reuse status flow
  DepStore.setStatus('VALIDATING');
  refreshAll();

  try {
    const result = await validateHmiSpec({
      ir: genState.ir,
      spec: genState.projectSpec,
      target: depState.target,
    });

    if (result.ok || result.valid) {
      DepStore.setStatus('VALIDATED');
      DepStore.addDiagnostics(normalizeDiagnostics(result.diagnostics || result.warnings || []));
    } else {
      const diags = normalizeDiagnostics(result.diagnostics || result.errors || [result]);
      DepStore.setStatus('BLOCKED');
      DepStore.addDiagnostics(diags);
    }
  } catch (e) {
    DepStore.setStatus('FAILED');
    DepStore.addDiagnostics([{ severity: 'error', phase: 'validate', message: e.message || String(e) }]);
  }

  DepStore.finishDeploying();
  refreshAll();
}

/** 生成部署计划 */
export async function v4Plan() {
  const genState = GenStore.getState();
  const depState = DepStore.getState();

  if (!genState.ir && !genState.projectSpec) {
    DepStore.addDiagnostics([{ severity: 'error', phase: 'plan', message: '先生成 IR 或项目规格' }]);
    refreshDiagnosticsPanel();
    return;
  }

  DepStore.startPlanning();
  refreshAll();

  try {
    const plan = await getDeploymentPlan({
      ir: genState.ir,
      spec: genState.projectSpec,
      target: depState.target,
      dry_run: depState.dryRun,
    });

    DepStore.setPlan(plan);
  } catch (e) {
    DepStore.setStatus('FAILED');
    DepStore.addDiagnostics([{ severity: 'error', phase: 'plan', message: e.message || String(e) }]);
  }

  DepStore.finishPlanning();
  refreshAll();
}

/** 部署（Dry-Run 或真实部署） */
export async function v4Deploy() {
  const genState = GenStore.getState();
  const depState = DepStore.getState();
  const openState = OpenStore.getState();
  const tmplState = TmplStore.getState();

  if (!genState.ir && !genState.projectSpec) {
    DepStore.addDiagnostics([{ severity: 'error', phase: 'deploy', message: '先生成 IR 或项目规格' }]);
    refreshDiagnosticsPanel();
    return;
  }

  if (!depState.target || !depState.target.family) {
    DepStore.addDiagnostics([{ severity: 'error', phase: 'deploy', message: '请先选择目标设备' }]);
    refreshDiagnosticsPanel();
    return;
  }

  // 真实部署前检查连接
  if (!depState.dryRun && !openState.connected) {
    DepStore.setStatus('NOT_CONNECTED');
    DepStore.addDiagnostics([{ severity: 'error', phase: 'deploy', message: '未连接 TIA Portal，无法真实部署。请先连接 TIA 或使用 Dry-Run。' }]);
    refreshAll();
    return;
  }

  DepStore.startDeploying();
  refreshAll();

  try {
    const result = await deployHmi({
      ir: genState.ir,
      spec: genState.projectSpec,
      target: depState.target,
      dry_run: depState.dryRun,
      template_xml: tmplState.templateXml || undefined,
    });

    const status = normalizeDeploymentStatus(result);
    DepStore.setDeploymentResult({ ...result, status });
  } catch (e) {
    DepStore.setStatus('FAILED');
    DepStore.addDiagnostics([{ severity: 'error', phase: 'deploy', message: e.message || String(e) }]);
  }

  DepStore.finishDeploying();
  refreshAll();
}

/** 编译 */
export async function v4Compile() {
  const depState = DepStore.getState();

  DepStore.startCompiling();
  refreshAll();

  try {
    const result = await compileHmi({
      target: depState.target,
    });

    DepStore.setCompileResult(result);
  } catch (e) {
    DepStore.setStatus('FAILED');
    DepStore.addDiagnostics([{ severity: 'error', phase: 'compile', message: e.message || String(e) }]);
  }

  DepStore.finishCompiling();
  refreshAll();
}

/** 验证 */
export async function v4Verify() {
  const genState = GenStore.getState();
  const depState = DepStore.getState();
  const openState = OpenStore.getState();

  if (!openState.connected) {
    DepStore.addDiagnostics([{ severity: 'error', phase: 'verify', message: '未连接 TIA Portal，无法验证' }]);
    refreshDiagnosticsPanel();
    return;
  }

  DepStore.startVerifying();
  refreshAll();

  try {
    const result = await verifyHmi({
      ir: genState.ir,
      spec: genState.projectSpec,
      target: depState.target,
    });

    DepStore.setVerificationResult(result);
  } catch (e) {
    DepStore.setStatus('FAILED');
    DepStore.addDiagnostics([{ severity: 'error', phase: 'verify', message: e.message || String(e) }]);
  }

  DepStore.finishVerifying();
  refreshAll();
}

/** 重置部署状态 */
export function v4Reset() {
  DepStore.resetDeployment();
  refreshAll();
}

// ============================================================
// 同步目标设备变化
// ============================================================
export function syncTargetFromUi() {
  const familyEl = $(V4_CONTAINERS.targetFamily);
  const tiaVerEl = $(V4_CONTAINERS.targetTiaVersion);
  const deviceEl = $(V4_CONTAINERS.targetDevice);
  const dryRunEl = $(V4_CONTAINERS.dryRunToggle);

  if (familyEl) familyEl.addEventListener('change', () => {
    DepStore.setTarget({ family: familyEl.value });
    refreshAll();
  });
  if (tiaVerEl) tiaVerEl.addEventListener('change', () => {
    DepStore.setTarget({ tia_version: tiaVerEl.value });
  });
  if (deviceEl) deviceEl.addEventListener('change', () => {
    DepStore.setTarget({ device_name: deviceEl.value });
  });
  if (dryRunEl) dryRunEl.addEventListener('change', () => {
    DepStore.setDryRun(dryRunEl.checked);
    refreshAll();
  });
}

// ============================================================
// 绑定按钮
// ============================================================
export function bindV4Buttons() {
  const btnValidate = $(V4_CONTAINERS.btnValidate);
  const btnPlan = $(V4_CONTAINERS.btnPlan);
  const btnDeploy = $(V4_CONTAINERS.btnDeploy);
  const btnCompile = $(V4_CONTAINERS.btnCompile);
  const btnVerify = $(V4_CONTAINERS.btnVerify);
  const btnReset = $(V4_CONTAINERS.btnResetDeploy);

  if (btnValidate) btnValidate.addEventListener('click', v4Validate);
  if (btnPlan) btnPlan.addEventListener('click', v4Plan);
  if (btnDeploy) btnDeploy.addEventListener('click', () => {
    const state = DepStore.getState();
    if (!state.dryRun) {
      if (!confirm('即将把变量、画面、事件和动态绑定导入当前 TIA Portal 项目。\n请确认已经备份项目。')) {
        return;
      }
    }
    v4Deploy();
  });
  if (btnCompile) btnCompile.addEventListener('click', v4Compile);
  if (btnVerify) btnVerify.addEventListener('click', v4Verify);
  if (btnReset) btnReset.addEventListener('click', v4Reset);
}

// ============================================================
// 接收来自 app.js 的生成结果
// ============================================================
export function onGenerationResult(irOrSpec) {
  if (!irOrSpec) return;

  GenStore.setIr(irOrSpec);

  // 尝试作为 summary 格式处理
  if (irOrSpec.tags) GenStore.setVariables(irOrSpec.tags);
  if (irOrSpec.bindings) GenStore.setBindings(irOrSpec.bindings);

  // 请求 generation summary
  getGenerationSummary({ ir: irOrSpec }).then((summary) => {
    if (summary) {
      if (summary.tags) GenStore.setVariables(summary.tags);
      if (summary.bindings) GenStore.setBindings(summary.bindings);
      if (summary.understanding) {
        // 把 understanding 里的设备类型同步到部署 store
        if (summary.understanding.hmi_family) {
          DepStore.setTarget({ family: normalizeHmiType(summary.understanding.hmi_family) });
        }
      }
    }
    refreshAll();
  }).catch(() => {
    // summary 接口可能不存在，直接用 ir 数据
    refreshAll();
  });
}

// ============================================================
// 初始化
// ============================================================
export function initV4() {
  syncTargetFromUi();
  bindV4Buttons();
  refreshAll();

  // 暴露给全局，供 app.js 调用
  window.V4 = {
    onGenerationResult,
    v4Validate,
    v4Plan,
    v4Deploy,
    v4Compile,
    v4Verify,
    v4Reset,
    refreshAll,
    stores: { GenStore, DepStore, TmplStore, OpenStore },
  };

  console.log('[V4] 前端工作台初始化完成');
}

/**
 * 部署状态管理 Store
 *
 * 负责：目标设备、部署计划、部署状态、Dry-Run 开关、部署/编译/验证结果
 */

/**
 * @typedef {Object} DeploymentState
 * @property {import('../types/hmi').HmiTarget} target
 * @property {boolean} dryRun
 * @property {import('../types/deployment').DeploymentPlan|null} plan
 * @property {import('../types/deployment').DeploymentResult|null} deploymentResult
 * @property {Object|null} verificationResult
 * @property {Object|null} compileResult
 * @property {import('../types/deployment').DeploymentStatus} status
 * @property {import('../types/diagnostics').Diagnostic[]} diagnostics
 * @property {boolean} isPlanning
 * @property {boolean} isDeploying
 * @property {boolean} isVerifying
 * @property {boolean} isCompiling
 */

const state = {
  target: {
    family: 'comfort',
    tia_version: 'V20',
    device_name: '',
  },
  dryRun: true,
  plan: null,
  deploymentResult: null,
  verificationResult: null,
  compileResult: null,
  status: 'IDLE',
  diagnostics: [],
  isPlanning: false,
  isDeploying: false,
  isVerifying: false,
  isCompiling: false,
};

/** @type {Array<(s: DeploymentState) => void>} */
let listeners = [];

function notify() {
  const snap = getState();
  listeners.forEach((fn) => { try { fn(snap); } catch (e) { /* ignore */ } });
}

/** @returns {DeploymentState} */
export function getState() {
  return { ...state };
}

/** @param {(s: DeploymentState) => void} fn @returns {() => void} */
export function subscribe(fn) {
  listeners.push(fn);
  return () => { listeners = listeners.filter((l) => l !== fn); };
}

/** @param {import('../types/hmi').HmiTarget} target */
export function setTarget(target) {
  state.target = { ...state.target, ...target };
  notify();
}

/** @param {boolean} value */
export function setDryRun(value) {
  state.dryRun = value;
  notify();
}

/** @param {import('../types/deployment').DeploymentPlan} plan */
export function setPlan(plan) {
  state.plan = plan;
  if (plan && plan.diagnostics && plan.diagnostics.length > 0) {
    const errors = plan.diagnostics.filter((d) => d.severity === 'error');
    if (errors.length > 0) {
      state.status = 'BLOCKED';
    }
  }
  notify();
}

/** @param {import('../types/deployment').DeploymentStatus} status */
export function setStatus(status) {
  state.status = status;
  notify();
}

/** @param {import('../types/deployment').DeploymentResult} result */
export function setDeploymentResult(result) {
  state.deploymentResult = result;
  state.status = result.status || 'FAILED';
  if (result.diagnostics) {
    state.diagnostics = result.diagnostics;
  }
  notify();
}

/** @param {Object} result */
export function setVerificationResult(result) {
  state.verificationResult = result;
  if (result) {
    state.status = result.success ? 'VERIFIED' : 'FAILED';
    if (result.diagnostics) {
      state.diagnostics = result.diagnostics;
    }
  }
  notify();
}

/** @param {Object} result */
export function setCompileResult(result) {
  state.compileResult = result;
  if (result) {
    const errors = result.errors || result.error_count || 0;
    state.status = errors === 0 ? 'COMPILED' : 'FAILED';
    if (result.diagnostics) {
      state.diagnostics = result.diagnostics;
    }
  }
  notify();
}

/** @param {import('../types/diagnostics').Diagnostic[]} diagnostics */
export function addDiagnostics(diagnostics) {
  state.diagnostics = [...state.diagnostics, ...diagnostics];
  notify();
}

export function resetDeployment() {
  state.plan = null;
  state.deploymentResult = null;
  state.verificationResult = null;
  state.compileResult = null;
  state.status = 'IDLE';
  state.diagnostics = [];
  state.isPlanning = false;
  state.isDeploying = false;
  state.isVerifying = false;
  state.isCompiling = false;
  notify();
}

export function startPlanning() { state.isPlanning = true; state.status = 'PLANNING'; notify(); }
export function finishPlanning() { state.isPlanning = false; notify(); }
export function startDeploying() { state.isDeploying = true; state.status = 'DEPLOYING'; notify(); }
export function finishDeploying() { state.isDeploying = false; notify(); }
export function startVerifying() { state.isVerifying = true; state.status = 'VERIFYING'; notify(); }
export function finishVerifying() { state.isVerifying = false; notify(); }
export function startCompiling() { state.isCompiling = true; state.status = 'COMPILING'; notify(); }
export function finishCompiling() { state.isCompiling = false; notify(); }

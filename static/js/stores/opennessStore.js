/**
 * Openness/TIA 连接状态管理 Store
 *
 * 负责：TIA 连接状态、诊断结果、runtime metadata、capabilities
 */

/**
 * @typedef {Object} OpennessState
 * @property {boolean} connected
 * @property {Object|null} status
 * @property {import('../types/diagnostics').Diagnostic[]} diagnostics
 * @property {Object|null} capabilities
 * @property {Object|null} runtimeMetadata
 * @property {boolean} isConnecting
 */

const state = {
  connected: false,
  status: null,
  diagnostics: [],
  capabilities: null,
  runtimeMetadata: null,
  isConnecting: false,
};

let listeners = [];

function notify() {
  const snap = getState();
  listeners.forEach((fn) => { try { fn(snap); } catch (e) { /* ignore */ } });
}

/** @returns {OpennessState} */
export function getState() {
  return { ...state };
}

/** @param {(s: OpennessState) => void} fn @returns {() => void} */
export function subscribe(fn) {
  listeners.push(fn);
  return () => { listeners = listeners.filter((l) => l !== fn); };
}

/** @param {boolean} connected */
export function setConnected(connected) {
  state.connected = connected;
  notify();
}

/** @param {Object} status */
export function setStatus(status) {
  state.status = status;
  state.connected = !!(status && status.connected);
  if (status && status.diagnostics) {
    state.diagnostics = status.diagnostics;
  }
  notify();
}

/** @param {import('../types/diagnostics').Diagnostic[]} diagnostics */
export function setDiagnostics(diagnostics) {
  state.diagnostics = diagnostics;
  notify();
}

/** @param {Object} capabilities */
export function setCapabilities(capabilities) {
  state.capabilities = capabilities;
  notify();
}

/** @param {Object} metadata */
export function setRuntimeMetadata(metadata) {
  state.runtimeMetadata = metadata;
  notify();
}

export function startConnecting() { state.isConnecting = true; notify(); }
export function finishConnecting() { state.isConnecting = false; notify(); }

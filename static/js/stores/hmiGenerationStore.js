/**
 * 生成状态管理 Store
 *
 * 负责：用户自然语言、SSE 事件日志、生成出的 IR/HmiProjectSpec、
 * 预览图、变量表、控件绑定表、诊断信息、生成状态
 */
import { normalizeGenerationEvent } from '../utils/generationEvents.js';

/**
 * @typedef {Object} GenerationState
 * @property {string} prompt
 * @property {Object|null} ir
 * @property {Object|null} projectSpec
 * @property {Object[]} streamEvents
 * @property {string|null} previewImageUrl
 * @property {import('../types/hmi').HmiTag[]} variables
 * @property {import('../types/hmi').HmiBindingSummary[]} bindings
 * @property {import('../types/diagnostics').Diagnostic[]} diagnostics
 * @property {boolean} isGenerating
 * @property {string|null} generationError
 */

const state = {
  prompt: '',
  ir: null,
  projectSpec: null,
  streamEvents: [],
  previewImageUrl: null,
  variables: [],
  bindings: [],
  diagnostics: [],
  isGenerating: false,
  generationError: null,
};

/** @type {Array<(s: GenerationState) => void>} */
let listeners = [];

function notify() {
  const snap = getState();
  listeners.forEach((fn) => { try { fn(snap); } catch (e) { /* ignore */ } });
}

/** @returns {GenerationState} */
export function getState() {
  return { ...state };
}

/** @param {(s: GenerationState) => void} fn @returns {() => void} */
export function subscribe(fn) {
  listeners.push(fn);
  return () => { listeners = listeners.filter((l) => l !== fn); };
}

export function setPrompt(prompt) {
  state.prompt = prompt;
  notify();
}

export function startGeneration() {
  state.isGenerating = true;
  state.generationError = null;
  state.streamEvents = [];
  state.diagnostics = [];
  notify();
}

/** @param {string} eventName @param {any} data */
export function appendStreamEvent(eventName, data) {
  const normalized = normalizeGenerationEvent(eventName, data);
  state.streamEvents.push(normalized);

  // 自动提取 IR
  if (eventName === 'pipeline_done' || eventName === 'review_pass') {
    if (data && data.ir) {
      state.ir = data.ir;
    }
  }
  if (eventName === 'done' && data && data.ir) {
    state.ir = data.ir;
  }

  // 提取错误
  if (eventName === 'error') {
    state.diagnostics.push({
      severity: 'error',
      phase: 'generation',
      message: typeof data === 'string' ? data : (data.message || 'SSE 错误'),
    });
  }

  notify();
}

/** @param {Object} ir */
export function setIr(ir) {
  state.ir = ir;
  notify();
}

/** @param {Object} spec */
export function setProjectSpec(spec) {
  state.projectSpec = spec;
  if (spec && spec.tags) {
    setVariables(spec.tags);
  }
  notify();
}

/** @param {import('../types/hmi').HmiTag[]} tags */
export function setVariables(tags) {
  state.variables = tags;
  notify();
}

/** @param {import('../types/hmi').HmiBindingSummary[]} bindings */
export function setBindings(bindings) {
  state.bindings = bindings;
  notify();
}

/** @param {import('../types/diagnostics').Diagnostic[]} diagnostics */
export function setDiagnostics(diagnostics) {
  state.diagnostics = diagnostics;
  notify();
}

export function resetGeneration() {
  state.prompt = '';
  state.ir = null;
  state.projectSpec = null;
  state.streamEvents = [];
  state.previewImageUrl = null;
  state.variables = [];
  state.bindings = [];
  state.diagnostics = [];
  state.isGenerating = false;
  state.generationError = null;
  notify();
}

/** @param {string} url */
export function setPreviewImageUrl(url) {
  state.previewImageUrl = url;
  notify();
}

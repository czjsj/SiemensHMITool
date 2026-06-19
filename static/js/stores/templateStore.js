/**
 * 模板状态管理 Store
 *
 * 负责：模板 XML、模板来源、模板分析结果、模板原型
 */

/**
 * @typedef {Object} TemplateState
 * @property {string} templateXml
 * @property {'none'|'uploaded'|'exported'|'default'} templateSource
 * @property {import('../types/template').TemplateProfile|null} templateProfile
 * @property {import('../types/template').TemplatePrototype[]} buttonPrototypes
 * @property {import('../types/template').TemplatePrototype[]} indicatorPrototypes
 * @property {string[]} placeholderTags
 * @property {import('../types/diagnostics').Diagnostic[]} diagnostics
 */

const state = {
  templateXml: '',
  templateSource: 'none',
  templateProfile: null,
  buttonPrototypes: [],
  indicatorPrototypes: [],
  placeholderTags: [],
  diagnostics: [],
};

let listeners = [];

function notify() {
  const snap = getState();
  listeners.forEach((fn) => { try { fn(snap); } catch (e) { /* ignore */ } });
}

/** @returns {TemplateState} */
export function getState() {
  return { ...state };
}

/** @param {(s: TemplateState) => void} fn @returns {() => void} */
export function subscribe(fn) {
  listeners.push(fn);
  return () => { listeners = listeners.filter((l) => l !== fn); };
}

/** @param {string} xml */
export function setTemplateXml(xml) {
  state.templateXml = xml;
  if (xml) {
    state.templateSource = state.templateSource === 'none' ? 'uploaded' : state.templateSource;
  }
  notify();
}

/** @param {'none'|'uploaded'|'exported'|'default'} source */
export function setTemplateSource(source) {
  state.templateSource = source;
  notify();
}

export function clearTemplate() {
  state.templateXml = '';
  state.templateSource = 'none';
  state.templateProfile = null;
  state.buttonPrototypes = [];
  state.indicatorPrototypes = [];
  state.placeholderTags = [];
  state.diagnostics = [];
  notify();
}

/** @param {import('../types/template').TemplateProfile} profile */
export function setTemplateProfile(profile) {
  state.templateProfile = profile;
  state.buttonPrototypes = profile.buttons || [];
  state.indicatorPrototypes = profile.indicators || [];
  if (profile.diagnostics) {
    state.diagnostics = profile.diagnostics;
  }
  notify();
}

/** @param {import('../types/diagnostics').Diagnostic[]} diagnostics */
export function setDiagnostics(diagnostics) {
  state.diagnostics = diagnostics;
  notify();
}

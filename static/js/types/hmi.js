/**
 * HMI 类型定义
 *
 * @typedef {Object} HmiTarget
 * @property {'basic'|'comfort'|'unified'} family
 * @property {string} [tia_version]
 * @property {string} [device_name]
 * @property {string} [panel_name]
 * @property {{width:number,height:number}} [resolution]
 *
 * @typedef {Object} HmiTag
 * @property {string} name
 * @property {string} [data_type]
 * @property {'read'|'write'|'read_write'} [direction]
 * @property {'hmi_internal'|'plc_external'|'derived'} [scope]
 * @property {string|null} [connection]
 * @property {string|null} [address]
 * @property {string|null} [comment]
 * @property {Object<string,any>} [metadata]
 *
 * @typedef {Object} HmiBindingSummary
 * @property {string} [item_id]
 * @property {string} item_name
 * @property {string} item_type
 * @property {string} [text]
 * @property {string} [template_ref]
 * @property {string} [prototype_id]
 * @property {string} [tag]
 * @property {string} [behavior]
 * @property {string} [indicator_mode]
 * @property {string} [event_summary]
 * @property {string} [binding_summary]
 * @property {import('./diagnostics').Diagnostic[]} [diagnostics]
 *
 * @typedef {Object} HmiProjectSpec
 * @property {string} [schema_version]
 * @property {Object} [project]
 * @property {HmiTarget} [target]
 * @property {HmiTag[]} [tags]
 * @property {Object[]} [screens]
 * @property {Object<string,any>} [metadata]
 */

/** @type {Object<string,string>} */
export const HMI_FAMILY_LABELS = {
  basic: 'Basic Panel (精简面板)',
  comfort: 'Comfort Panel (精智面板)',
  unified: 'Unified Panel (统一面板)',
};

/** @type {Object<string,string[]>} */
export const HMI_FAMILY_DEVICES = {
  basic: ['KTP400', 'KTP700', 'KTP900', 'KTP1200'],
  comfort: ['TP700', 'TP900', 'TP1200', 'TP1500', 'TP1900', 'TP2200'],
  unified: ['MTP700', 'MTP1000', 'MTP1200', 'MTP1500', 'MTP1900', 'MTP2200'],
};

/** @type {string[]} */
export const TIA_VERSIONS = ['V16', 'V17', 'V18', 'V19', 'V20'];

/**
 * 规范化 HMI 类型字符串
 * @param {string} value
 * @returns {'basic'|'comfort'|'unified'}
 */
export function normalizeHmiType(value) {
  const s = String(value || '').toLowerCase();
  if (s.includes('basic') || s.includes('ktp')) return 'basic';
  if (s.includes('unified')) return 'unified';
  if (s.includes('comfort') || s.includes('classic')) return 'comfort';
  return 'comfort';
}

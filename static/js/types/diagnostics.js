/**
 * Diagnostic 类型定义 — 统一诊断消息结构
 *
 * @typedef {Object} Diagnostic
 * @property {string} [code] - 诊断码 (如 "TEMPLATE_XML_PARSE_FAILED")
 * @property {'info'|'warning'|'error'|'critical'} [severity]
 * @property {string} [phase] - 阶段标识
 * @property {string} message - 诊断消息
 * @property {string} [suggestion] - 修复建议
 * @property {string} [item_name] - 关联控件名
 * @property {string} [tag_name] - 关联变量名
 * @property {Object<string,any>} [details] - 附加详情
 */

/** @type {Object<string,string>} */
export const SEVERITY_LABELS = {
  info: '信息',
  warning: '警告',
  error: '错误',
  critical: '严重',
};

/** @type {Object<string,string>} */
export const SEVERITY_COLORS = {
  info: 'var(--text-muted)',
  warning: 'var(--warning)',
  error: 'var(--danger)',
  critical: 'var(--danger)',
};

/**
 * 标准化诊断对象，补全缺失字段
 * @param {Object} raw
 * @returns {import('./diagnostics').Diagnostic}
 */
export function normalizeDiagnostic(raw) {
  return {
    code: raw.code || null,
    severity: raw.severity || 'error',
    phase: raw.phase || null,
    message: raw.message || String(raw),
    suggestion: raw.suggestion || null,
    item_name: raw.item_name || null,
    tag_name: raw.tag_name || null,
    details: raw.details || {},
  };
}

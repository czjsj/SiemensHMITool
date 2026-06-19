/**
 * Diagnostic 适配器 — 标准化各种错误格式
 */
import { normalizeDiagnostic } from '../types/diagnostics.js';

/**
 * 标准化诊断信息数组
 * @param {any} input
 * @returns {import('../types/diagnostics').Diagnostic[]}
 */
export function normalizeDiagnostics(input) {
  if (!input) return [];

  // 已经是数组
  if (Array.isArray(input)) {
    return input.map(normalizeDiagnostic);
  }

  // input.diagnostics
  if (Array.isArray(input.diagnostics)) {
    return input.diagnostics.map(normalizeDiagnostic);
  }

  // input.errors
  if (Array.isArray(input.errors)) {
    return input.errors.map((e) => normalizeDiagnostic({
      severity: 'error',
      message: typeof e === 'string' ? e : (e.message || JSON.stringify(e)),
      ...(typeof e === 'object' ? e : {}),
    }));
  }

  // input.warnings
  if (Array.isArray(input.warnings)) {
    return input.warnings.map((w) => normalizeDiagnostic({
      severity: 'warning',
      message: typeof w === 'string' ? w : (w.message || JSON.stringify(w)),
      ...(typeof w === 'object' ? w : {}),
    }));
  }

  // 字符串 error
  if (typeof input === 'string') {
    return [normalizeDiagnostic({ severity: 'error', message: input })];
  }

  // error 对象
  if (input.message || input.error) {
    return [normalizeDiagnostic({
      severity: input.severity || 'error',
      message: input.message || input.error || String(input),
      code: input.code,
      phase: input.phase,
      suggestion: input.suggestion,
      item_name: input.item_name,
      tag_name: input.tag_name,
      details: input.details,
    })];
  }

  return [];
}

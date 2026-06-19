/**
 * Deployment 适配器 — 标准化部署状态
 */
import { STATUS_LABELS } from '../types/deployment.js';
import { normalizeDiagnostics } from './diagnosticAdapter.js';

/**
 * 标准化部署状态
 * @param {Object} result
 * @returns {string}
 */
export function normalizeDeploymentStatus(result) {
  if (!result) return 'IDLE';

  const status = result.status || '';
  const success = result.success;
  const mode = result.mode || '';
  const diagnostics = normalizeDiagnostics(result.diagnostics || result);

  // NOT_CONNECTED
  if (status === 'NOT_CONNECTED' || result.code === 'NOT_CONNECTED') {
    return 'NOT_CONNECTED';
  }

  // DRY_RUN
  if (mode === 'DRY_RUN' || status === 'DRY_RUN') {
    return 'DRY_RUN';
  }

  // BLOCKED (有 error diagnostics)
  if (status === 'BLOCKED') return 'BLOCKED';
  if (diagnostics.some((d) => d.severity === 'error' && d.phase === 'validate')) {
    return 'BLOCKED';
  }

  // FAILED
  if (status === 'FAILED' || success === false) {
    // 如果是因为 NOT_CONNECTED 而失败
    if (result.code === 'NOT_CONNECTED') return 'NOT_CONNECTED';
    return 'FAILED';
  }

  // 编译失败
  if (result.compile && result.compile.errors > 0) return 'FAILED';
  if (result.compile && result.compile.success === false) return 'FAILED';

  // DEPLOYED
  if (status === 'DEPLOYED' || success === true) return 'DEPLOYED';

  // COMPILED
  if (status === 'COMPILED') return 'COMPILED';

  // VERIFIED
  if (status === 'VERIFIED') return 'VERIFIED';

  // 如果 mode 是 DRY_RUN 就返回 DRY_RUN
  if (mode === 'DRY_RUN') return 'DRY_RUN';

  return status || 'IDLE';
}

/**
 * 获取部署状态标签
 * @param {string} status
 * @returns {string}
 */
export function getStatusLabel(status) {
  return STATUS_LABELS[status] || status || '未知';
}

/**
 * 判断是否是成功状态
 * @param {string} status
 * @returns {boolean}
 */
export function isSuccessStatus(status) {
  return ['DEPLOYED', 'VERIFIED', 'COMPILED', 'VALIDATED'].includes(status);
}

/**
 * 判断是否是错误状态
 * @param {string} status
 * @returns {boolean}
 */
export function isErrorStatus(status) {
  return ['FAILED', 'BLOCKED', 'NOT_CONNECTED'].includes(status);
}

/**
 * 判断是否是进行中状态
 * @param {string} status
 * @returns {boolean}
 */
export function isActiveStatus(status) {
  return ['VALIDATING', 'PLANNING', 'DEPLOYING', 'VERIFYING', 'COMPILING'].includes(status);
}

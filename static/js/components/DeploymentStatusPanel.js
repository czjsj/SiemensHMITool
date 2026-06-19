/**
 * DeploymentStatusPanel 渲染器 — 部署状态面板
 */
import { STATUS_LABELS, STATUS_COLORS } from '../types/deployment.js';
import { renderDiagnosticsPanel } from './DiagnosticsPanel.js';
import { normalizeDiagnostics } from '../adapters/diagnosticAdapter.js';

/**
 * @param {Object} props
 * @param {string} props.status
 * @param {import('../types/deployment').DeploymentResult|null} [props.result]
 * @param {import('../types/diagnostics').Diagnostic[]} [props.diagnostics]
 * @returns {string} HTML string
 */
export function renderDeploymentStatusPanel(props) {
  const { status = 'IDLE', result, diagnostics: diags } = props;

  const label = STATUS_LABELS[status] || status;
  const color = STATUS_COLORS[status] || 'var(--text-muted)';

  // 关键规则
  const isSuccess = ['DEPLOYED', 'VERIFIED', 'COMPILED', 'VALIDATED'].includes(status);
  const isWarning = ['DRY_RUN', 'NOT_CONNECTED'].includes(status);
  const isError = ['FAILED', 'BLOCKED'].includes(status);
  const isActive = ['VALIDATING', 'PLANNING', 'DEPLOYING', 'VERIFYING', 'COMPILING'].includes(status);

  let statusClass = 'dep-status--info';
  let statusIcon = 'ℹ';
  if (isSuccess) { statusClass = 'dep-status--success'; statusIcon = '✓'; }
  else if (isWarning) { statusClass = 'dep-status--warning'; statusIcon = '⚠'; }
  else if (isError) { statusClass = 'dep-status--error'; statusIcon = '✕'; }
  else if (isActive) { statusClass = 'dep-status--active'; statusIcon = '⟳'; }

  let summaryHtml = '';
  if (result) {
    const tagsOk = result.tags ? (result.tags.created || result.tags.imported || 0) : 0;
    const screensOk = result.screens ? (result.screens.created || result.screens.imported || 0) : 0;
    const compileOk = result.compile ? (result.compile.errors === 0) : null;
    const verifyOk = result.verification ? result.verification.success : null;

    summaryHtml = '<div class="dep-summary">';
    summaryHtml += `<span>变量: ${tagsOk} 个已导入</span>`;
    summaryHtml += `<span>画面: ${screensOk} 个已导入</span>`;
    if (compileOk !== null) {
      summaryHtml += `<span>编译: ${compileOk ? '✓ 通过' : '✕ 失败 (错误 ' + (result.compile.errors || 0) + ')'}</span>`;
    }
    if (verifyOk !== null) {
      summaryHtml += `<span>验证: ${verifyOk ? '✓ 通过' : '✕ 未通过'}</span>`;
    }
    if (result.mode) {
      summaryHtml += `<span>模式: ${escHtml(result.mode)}</span>`;
    }
    summaryHtml += '</div>';

    // 重要：DRY_RUN 时不能显示"导入成功"
    if (status === 'DRY_RUN') {
      summaryHtml += '<div class="dep-notice dep-notice--warn">⚠ 预演模式 — 未实际导入到 TIA Portal</div>';
    }
    if (status === 'NOT_CONNECTED') {
      summaryHtml += '<div class="dep-notice dep-notice--err">✕ 未连接 TIA Portal，无法进行真实部署</div>';
    }
  }

  // 诊断
  const allDiags = diags || [];
  if (result && result.diagnostics) {
    allDiags.push(...normalizeDiagnostics(result.diagnostics));
  }

  const diagHtml = allDiags.length > 0 ? renderDiagnosticsPanel({ diagnostics: allDiags, title: '部署诊断' }) : '';

  return `<div class="v4-panel-box">
    <div class="v4-panel-head">部署状态</div>
    <div class="dep-status ${statusClass}">
      <span class="dep-status-icon">${statusIcon}</span>
      <span class="dep-status-label" style="color:${color}">${escHtml(label)}</span>
      ${isActive ? '<span class="dep-spin"></span>' : ''}
    </div>
    ${summaryHtml}
    ${diagHtml}
  </div>`;
}

function escHtml(s) {
  return String(s == null ? '' : s).replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]));
}

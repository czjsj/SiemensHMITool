/**
 * DeploymentPlanTimeline 渲染器 — 部署计划时间线展示
 */
import { DEPLOYMENT_PHASES } from '../types/deployment.js';

/**
 * @param {Object} props
 * @param {import('../types/deployment').DeploymentPlan|null} props.plan
 * @param {string} [props.currentPhase]
 * @returns {string} HTML string
 */
export function renderDeploymentPlanTimeline(props) {
  const { plan, currentPhase } = props;

  if (!plan || !plan.steps || !plan.steps.length) {
    return `<div class="v4-panel-box">
      <div class="v4-panel-head">部署计划</div>
      <div class="diag-empty">尚未生成部署计划</div>
    </div>`;
  }

  const phaseOrder = [
    'P00_PRECHECK', 'P10_CONNECTIONS', 'P20_TAGS', 'P30_TEXT_LISTS',
    'P40_SCRIPTS', 'P50_SCREENS', 'P60_COMPILE', 'P70_VERIFY',
    'P80_REPORT', 'P90_ROLLBACK',
  ];

  const stepMap = {};
  (plan.steps || []).forEach((s) => { stepMap[s.phase] = s; });

  const steps = phaseOrder.map((phaseKey) => {
    const step = stepMap[phaseKey];
    const label = DEPLOYMENT_PHASES[phaseKey] || phaseKey;
    const isCurrent = currentPhase && phaseKey === currentPhase;
    const status = step ? (step.status || 'pending') : 'not_planned';

    return { phase: phaseKey, label, step, status, isCurrent };
  });

  const items = steps.map((s) => {
    let dotClass = 'tl-dot-pending';
    if (s.status === 'completed') dotClass = 'tl-dot-done';
    else if (s.status === 'failed') dotClass = 'tl-dot-fail';
    else if (s.status === 'active' || s.isCurrent) dotClass = 'tl-dot-active';
    else if (s.status === 'skipped') dotClass = 'tl-dot-skip';

    const deps = (s.step && s.step.depends_on && s.step.depends_on.length)
      ? `<span class="tl-deps">依赖: ${s.step.depends_on.join(', ')}</span>`
      : '';

    const diags = (s.step && s.step.diagnostics && s.step.diagnostics.length)
      ? `<span class="tl-diag-count">${s.step.diagnostics.length} 诊断</span>`
      : '';

    return `<div class="tl-item ${s.isCurrent ? 'tl-item-current' : ''}">
      <div class="tl-dot ${dotClass}"></div>
      <div class="tl-info">
        <span class="tl-phase">${escHtml(s.phase)}</span>
        <span class="tl-label">${escHtml(s.label)}</span>
        ${deps}
        ${diags}
      </div>
    </div>`;
  }).join('');

  return `<div class="v4-panel-box">
    <div class="v4-panel-head">部署计划${plan.summary ? ' · ' + escHtml(String(plan.summary.tags_created || '')) + ' 变量 / ' + escHtml(String(plan.summary.screens_created || '')) + ' 画面' : ''}</div>
    <div class="tl-container">${items}</div>
  </div>`;
}

function escHtml(s) {
  return String(s == null ? '' : s).replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]));
}

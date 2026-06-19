/**
 * CompileResultPanel 渲染器 — 编译结果展示
 */

/**
 * @param {Object} props
 * @param {Object|null} props.compileResult
 * @returns {string} HTML string
 */
export function renderCompileResultPanel(props) {
  const { compileResult } = props;

  if (!compileResult) {
    return `<div class="v4-panel-box">
      <div class="v4-panel-head">编译结果</div>
      <div class="diag-empty">尚未编译</div>
    </div>`;
  }

  const success = compileResult.success !== false && (compileResult.errors || compileResult.error_count || 0) === 0;
  const errors = compileResult.errors || compileResult.error_count || 0;
  const warnings = compileResult.warnings || compileResult.warning_count || 0;
  const duration = compileResult.duration || compileResult.time_elapsed || null;

  const bannerHtml = success
    ? `<div class="dep-status dep-status--success"><span class="dep-status-icon">✓</span><span>编译完成</span></div>`
    : `<div class="dep-status dep-status--error"><span class="dep-status-icon">✕</span><span>编译失败</span></div>`;

  let statsHtml = '<div class="dep-summary">';
  statsHtml += `<span>错误: ${errors}</span>`;
  statsHtml += `<span>警告: ${warnings}</span>`;
  if (duration !== null) statsHtml += `<span>耗时: ${duration}s</span>`;
  statsHtml += '</div>';

  return `<div class="v4-panel-box">
    <div class="v4-panel-head">编译结果</div>
    ${bannerHtml}
    ${statsHtml}
  </div>`;
}

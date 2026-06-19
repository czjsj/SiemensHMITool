/**
 * DiagnosticsPanel 渲染器 — 统一展示所有诊断信息
 *
 * @param {Object} props
 * @param {import('../types/diagnostics').Diagnostic[]} props.diagnostics
 * @param {string} [props.title]
 * @returns {string} HTML string
 */
export function renderDiagnosticsPanel(props) {
  const { diagnostics = [], title = '诊断信息' } = props;

  if (!diagnostics.length) {
    return `<div class="diag-panel">
      <div class="diag-panel-head">${escHtml(title)}</div>
      <div class="diag-empty">暂无诊断</div>
    </div>`;
  }

  // 按 severity 分组
  const groups = { error: [], warning: [], info: [], critical: [] };
  diagnostics.forEach((d) => {
    const sev = d.severity || 'info';
    (groups[sev] = groups[sev] || []).push(d);
  });

  const sections = [];
  const order = ['critical', 'error', 'warning', 'info'];
  const labels = { critical: '严重', error: '错误', warning: '警告', info: '信息' };

  for (const sev of order) {
    const items = groups[sev];
    if (!items || !items.length) continue;

    let html = `<div class="diag-group diag-group--${sev}">
      <div class="diag-group-head">
        <span class="diag-group-icon">${sev === 'critical' || sev === 'error' ? '✕' : sev === 'warning' ? '⚠' : 'ℹ'}</span>
        <span>${labels[sev]} (${items.length})</span>
      </div>`;

    for (const d of items) {
      html += `<div class="diag-item diag-item--${sev}">`;
      if (d.code) html += `<span class="diag-code">[${escHtml(d.code)}]</span>`;
      if (d.phase) html += `<span class="diag-phase">${escHtml(d.phase)}</span>`;
      html += `<span class="diag-msg">${escHtml(d.message)}</span>`;
      if (d.item_name) html += `<span class="diag-meta">控件: ${escHtml(d.item_name)}</span>`;
      if (d.tag_name) html += `<span class="diag-meta">变量: ${escHtml(d.tag_name)}</span>`;
      if (d.suggestion) html += `<div class="diag-suggestion">💡 ${escHtml(d.suggestion)}</div>`;
      html += `</div>`;
    }
    html += `</div>`;
    sections.push(html);
  }

  return `<div class="diag-panel">
    <div class="diag-panel-head">
      <span>${escHtml(title)}</span>
      <button class="diag-copy-btn" onclick="navigator.clipboard.writeText(this.closest('.diag-panel').innerText)">复制</button>
    </div>
    ${sections.join('')}
  </div>`;
}

function escHtml(s) {
  return String(s == null ? '' : s).replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]));
}

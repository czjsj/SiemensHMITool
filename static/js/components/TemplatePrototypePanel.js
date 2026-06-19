/**
 * TemplatePrototypePanel 渲染器 — 模板原型展示
 */

/**
 * @param {Object} props
 * @param {import('../types/template').TemplatePrototype[]} props.buttonPrototypes
 * @param {import('../types/template').TemplatePrototype[]} props.indicatorPrototypes
 * @param {import('../types/diagnostics').Diagnostic[]} [props.diagnostics]
 * @returns {string} HTML string
 */
export function renderTemplatePrototypePanel(props) {
  const { buttonPrototypes = [], indicatorPrototypes = [], diagnostics = [] } = props;

  if (!buttonPrototypes.length && !indicatorPrototypes.length) {
    const warnMsg = diagnostics.length
      ? diagnostics.map((d) => escHtml(d.message)).join('; ')
      : '模板未加载或未分析，请先上传模板 XML';
    return `<div class="v4-panel-box">
      <div class="v4-panel-head">模板原型</div>
      <div class="diag-empty">${warnMsg}</div>
    </div>`;
  }

  const sections = [];

  // 按钮原型
  if (buttonPrototypes.length) {
    let html = `<div class="prototype-group">
      <div class="prototype-group-head">🔘 按钮模板 (${buttonPrototypes.length})</div>`;
    html += buttonPrototypes.map((p) => renderProtoCard(p)).join('');
    html += `</div>`;
    sections.push(html);
  }

  // 指示灯原型
  if (indicatorPrototypes.length) {
    let html = `<div class="prototype-group">
      <div class="prototype-group-head">💡 指示灯模板 (${indicatorPrototypes.length})</div>`;
    html += indicatorPrototypes.map((p) => renderProtoCard(p)).join('');
    html += `</div>`;
    sections.push(html);
  }

  return `<div class="v4-panel-box">
    <div class="v4-panel-head">模板原型</div>
    ${sections.join('')}
  </div>`;
}

function renderProtoCard(p) {
  const tags = (p.replaceable_tags || []).slice(0, 5);
  return `<div class="proto-card">
    <span class="proto-id">${escHtml(p.prototype_id)}</span>
    <span class="proto-source">${escHtml(p.source_name || '—')}</span>
    <span class="proto-kind">${escHtml(p.item_kind)}</span>
    ${p.behavior ? `<span class="proto-behavior">${escHtml(p.behavior)}</span>` : ''}
    ${p.indicator_mode ? `<span class="proto-mode">${escHtml(p.indicator_mode)}</span>` : ''}
    ${tags.length ? `<span class="proto-tags">变量: ${tags.map((t) => escHtml(t)).join(', ')}</span>` : ''}
    <span class="proto-counts">事件模式: ${(p.event_patterns || []).length} / 绑定模式: ${(p.binding_patterns || []).length}</span>
  </div>`;
}

function escHtml(s) {
  return String(s == null ? '' : s).replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]));
}

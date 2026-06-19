/**
 * BindingTable 渲染器 — 控件绑定表展示
 *
 * @param {Object} props
 * @param {import('../types/hmi').HmiBindingSummary[]} props.bindings
 * @returns {string} HTML string
 */
export function renderBindingTable(props) {
  const { bindings = [] } = props;

  if (!bindings.length) {
    return `<div class="v4-panel-box">
      <div class="v4-panel-head">控件绑定表 (0)</div>
      <div class="diag-empty">暂无控件绑定</div>
    </div>`;
  }

  const rows = bindings.map((b) => {
    const itemType = String(b.item_type || '').toLowerCase();
    const isButton = itemType === 'button';
    const isIndicator = itemType === 'indicator';
    const icon = isButton ? '🔘' : isIndicator ? '💡' : itemType === 'io_field' || itemType === 'symbolic_io_field' ? '📝' : '📄';

    const tagCell = b.tag
      ? `<span class="bind-tag">${escHtml(b.tag)}</span>`
      : '<span class="bind-no-tag">⚠ 未绑定</span>';

    const templateCell = b.template_ref
      ? escHtml(b.template_ref)
      : (b.prototype_id ? escHtml(b.prototype_id) : '<span class="bind-no-tmpl">—</span>');

    const detailCell = b.event_summary || b.binding_summary || '—';

    return `<tr>
      <td>${icon} ${escHtml(b.item_name)}</td>
      <td><span class="bind-type">${escHtml(b.item_type)}</span></td>
      <td>${escHtml(b.text || '—')}</td>
      <td>${templateCell}</td>
      <td>${tagCell}</td>
      <td>${escHtml(b.behavior || '—')}</td>
      <td>${escHtml(b.indicator_mode || '—')}</td>
      <td class="bind-detail">${escHtml(detailCell)}</td>
    </tr>`;
  }).join('');

  return `<div class="v4-panel-box">
    <div class="v4-panel-head">控件绑定表 (${bindings.length})</div>
    <div class="v4-table-wrap">
      <table class="v4-table">
        <thead><tr>
          <th>控件名</th><th>类型</th><th>文本</th><th>模板</th><th>变量</th><th>行为</th><th>指示灯模式</th><th>事件/动态</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  </div>`;
}

function escHtml(s) {
  return String(s == null ? '' : s).replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]));
}

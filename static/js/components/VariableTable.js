/**
 * VariableTable 渲染器 — 变量表展示
 *
 * @param {Object} props
 * @param {import('../types/hmi').HmiTag[]} props.tags
 * @returns {string} HTML string
 */
export function renderVariableTable(props) {
  const { tags = [] } = props;

  if (!tags.length) {
    return `<div class="v4-panel-box">
      <div class="v4-panel-head">变量表 (0)</div>
      <div class="diag-empty">暂无变量</div>
    </div>`;
  }

  const rows = tags.map((t) => {
    const scope = t.scope || 'hmi_internal';
    const scopeLabel = scope === 'plc_external' ? 'PLC 外部' : scope === 'derived' ? '派生' : 'HMI 内部';
    const direction = t.direction || 'read_write';
    const dirLabel = direction === 'write' ? '写入' : direction === 'read' ? '读取' : '读写';
    const dirClass = direction === 'write' ? 'var-dir-write' : direction === 'read' ? 'var-dir-read' : '';

    // pending_mapping 检查
    const pendingMapping = (t.metadata && t.metadata.pending_mapping) || false;
    const address = t.address || (scope === 'plc_external' && !pendingMapping ? '⚠ 未映射' : '—');

    // scope=plc_external 且无地址
    const addrClass = (scope === 'plc_external' && !t.address && !pendingMapping) ? 'var-addr-warn' : '';

    return `<tr>
      <td class="var-name">${escHtml(t.name)}</td>
      <td>${escHtml(t.data_type || '—')}</td>
      <td><span class="var-dir ${dirClass}">${dirLabel}</span></td>
      <td>${scopeLabel}</td>
      <td>${escHtml(t.connection || '—')}</td>
      <td class="${addrClass}">${escHtml(String(address))}</td>
      <td>${pendingMapping ? '<span class="var-pending">待映射</span>' : '—'}</td>
      <td class="var-comment">${escHtml(t.comment || '')}</td>
    </tr>`;
  }).join('');

  return `<div class="v4-panel-box">
    <div class="v4-panel-head">变量表 (${tags.length})</div>
    <div class="v4-table-wrap">
      <table class="v4-table">
        <thead><tr>
          <th>变量名</th><th>数据类型</th><th>方向</th><th>作用域</th><th>连接</th><th>地址</th><th>映射</th><th>说明</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  </div>`;
}

function escHtml(s) {
  return String(s == null ? '' : s).replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]));
}

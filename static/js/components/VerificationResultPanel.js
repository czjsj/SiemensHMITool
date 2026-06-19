/**
 * VerificationResultPanel 渲染器 — 验证结果展示
 */

/**
 * @param {Object} props
 * @param {Object|null} props.verificationResult
 * @param {boolean} [props.tiaConnected]
 * @returns {string} HTML string
 */
export function renderVerificationResultPanel(props) {
  const { verificationResult, tiaConnected } = props;

  if (!verificationResult) {
    return `<div class="v4-panel-box">
      <div class="v4-panel-head">验证结果</div>
      <div class="diag-empty">尚未验证</div>
    </div>`;
  }

  // 无 TIA 连接时不能显示验证成功
  if (tiaConnected === false) {
    return `<div class="v4-panel-box">
      <div class="v4-panel-head">验证结果</div>
      <div class="dep-notice dep-notice--err">✕ 未连接 TIA Portal，无法验证</div>
    </div>`;
  }

  const success = verificationResult.success !== false;
  const tags = verificationResult.tags || {};
  const screens = verificationResult.screens || {};
  const items = verificationResult.items || {};
  const bindings = verificationResult.bindings || {};
  const events = verificationResult.events || {};
  const scripts = verificationResult.scripts || {};

  const bannerHtml = success
    ? `<div class="dep-status dep-status--success"><span class="dep-status-icon">✓</span><span>验证通过</span></div>`
    : `<div class="dep-status dep-status--error"><span class="dep-status-icon">✕</span><span>验证未通过</span></div>`;

  const rows = [
    { label: '变量', expected: tags.expected || 0, found: tags.found || 0, missing: tags.missing || 0 },
    { label: '画面', expected: screens.expected || 0, found: screens.found || 0, missing: screens.missing || 0 },
    { label: '控件', expected: items.expected || 0, found: items.found || 0, missing: items.missing || 0 },
    { label: '绑定', expected: bindings.expected || bindings.matched || 0, found: bindings.found || bindings.matched || 0, missing: bindings.missing || 0 },
    { label: '事件', expected: events.expected || events.matched || 0, found: events.found || events.matched || 0, missing: events.missing || 0 },
    { label: '脚本', expected: scripts.expected || scripts.matched || 0, found: scripts.found || scripts.matched || 0, missing: scripts.missing || 0 },
  ].filter((r) => r.expected > 0 || r.found > 0 || r.missing > 0);

  let tableHtml = '';
  if (rows.length) {
    tableHtml = `<table class="v4-table" style="margin-top:8px">
      <thead><tr><th>项目</th><th>预期</th><th>实际</th><th>缺失</th></tr></thead>
      <tbody>${rows.map((r) => `<tr>
        <td>${r.label}</td><td>${r.expected}</td><td>${r.found}</td>
        <td class="${r.missing > 0 ? 'var-addr-warn' : ''}">${r.missing}</td>
      </tr>`).join('')}</tbody>
    </table>`;
  }

  return `<div class="v4-panel-box">
    <div class="v4-panel-head">验证结果</div>
    ${bannerHtml}
    ${tableHtml}
  </div>`;
}

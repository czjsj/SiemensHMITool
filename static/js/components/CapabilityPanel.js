/**
 * CapabilityPanel 渲染器 — 面板能力矩阵展示
 */

/**
 * @param {Object} props
 * @param {Object|null} props.capabilities
 * @param {Object|null} props.runtimeMetadata
 * @returns {string} HTML string
 */
export function renderCapabilityPanel(props) {
  const { capabilities, runtimeMetadata } = props;

  if (!capabilities && !runtimeMetadata) {
    return `<div class="v4-panel-box">
      <div class="v4-panel-head">HMI 能力</div>
      <div class="diag-empty">连接 TIA Portal 后自动获取</div>
    </div>`;
  }

  const capItems = [];

  if (capabilities) {
    const keys = [
      { key: 'screen_button', label: '按钮' },
      { key: 'screen_indicator', label: '指示灯' },
      { key: 'screen_io_field', label: 'IO 域' },
      { key: 'screen_text', label: '文本' },
      { key: 'color_dynamic', label: '颜色动态' },
      { key: 'blink_dynamic', label: '闪烁动态' },
      { key: 'VBS', label: 'VBS 脚本' },
      { key: 'JavaScript', label: 'JavaScript' },
      { key: 'unified_direct_model', label: 'Unified 直接对象模型' },
    ];

    capItems.push(...keys.map((k) => {
      const val = capabilities[k.key];
      const statusMap = { yes: '✓ 支持', no: '✕ 不支持', limited: '△ 有限', device: '📱 设备', unknown: '?' };
      const clsMap = { yes: 'cap-yes', no: 'cap-no', limited: 'cap-limited', device: 'cap-device', unknown: 'cap-unknown' };
      return { label: k.label, value: statusMap[val] || val || '?', cls: clsMap[val] || 'cap-unknown' };
    }));

    if (capabilities.hmi_family || capabilities.hmi_software_type) {
      capItems.unshift({
        label: '面板类型',
        value: capabilities.hmi_family || capabilities.hmi_software_type || '?',
        cls: 'cap-info',
      });
    }
  }

  if (runtimeMetadata) {
    if (runtimeMetadata.tia_version) {
      capItems.push({ label: 'TIA 版本', value: runtimeMetadata.tia_version, cls: 'cap-info' });
    }
    if (runtimeMetadata.unified_available !== undefined) {
      capItems.push({
        label: 'Unified 可用',
        value: runtimeMetadata.unified_available ? '✓ 是' : '✕ 否',
        cls: runtimeMetadata.unified_available ? 'cap-yes' : 'cap-no',
      });
    }
  }

  const rows = capItems.map((item) =>
    `<div class="cap-row"><span class="cap-label">${item.label}</span><span class="cap-value ${item.cls}">${escHtml(item.value)}</span></div>`
  ).join('');

  return `<div class="v4-panel-box">
    <div class="v4-panel-head">HMI 能力</div>
    <div class="cap-list">${rows}</div>
  </div>`;
}

function escHtml(s) {
  return String(s == null ? '' : s).replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]));
}

/**
 * HMI 数据适配器 — 从不同后端返回结构中提取变量表、绑定表、预览图
 */
import { normalizeHmiType } from '../types/hmi.js';

/**
 * 从 spec 或 legacy IR 中提取变量表
 * @param {Object} input
 * @returns {import('../types/hmi').HmiTag[]}
 */
export function extractTagsFromSpecOrIr(input) {
  if (!input) return [];

  // input.tags (HmiProjectSpec)
  if (Array.isArray(input.tags)) return input.tags;

  // input.spec.tags
  if (input.spec && Array.isArray(input.spec.tags)) return input.spec.tags;

  // input.project_spec.tags (summary response)
  if (input.project_spec && Array.isArray(input.project_spec.tags)) {
    return input.project_spec.tags;
  }

  // legacy ir.tags
  if (input.ir && Array.isArray(input.ir.tags)) return input.ir.tags;
  if (Array.isArray(input.ir_tags)) return input.ir_tags;

  // summary format
  if (Array.isArray(input.variables)) return input.variables;

  return [];
}

/**
 * 从 spec 或 legacy IR 中提取控件绑定表
 * @param {Object} input
 * @returns {import('../types/hmi').HmiBindingSummary[]}
 */
export function extractBindingsFromSpecOrIr(input) {
  if (!input) return [];

  // input.bindings (summary response)
  if (Array.isArray(input.bindings)) return input.bindings;

  // input.screens[*].items[*]
  if (Array.isArray(input.screens)) {
    return buildBindingsFromScreens(input.screens);
  }

  // input.spec.screens
  if (input.spec && Array.isArray(input.spec.screens)) {
    return buildBindingsFromScreens(input.spec.screens);
  }

  // input.project_spec.screens
  if (input.project_spec && Array.isArray(input.project_spec.screens)) {
    return buildBindingsFromScreens(input.project_spec.screens);
  }

  // legacy ir.objects
  const objects = input.ir ? input.ir.objects : (input.objects || []);
  if (objects.length > 0) {
    return objects.map((o) => ({
      item_id: o.id || '?',
      item_name: o.name || o.id || '?',
      item_type: (o.type || '?').toLowerCase(),
      text: o.text || '',
      template_ref: o.template_ref || null,
      tag: o.process_tag || o.tag_binding || '',
      behavior: o.behavior || null,
      indicator_mode: o.indicator_mode || null,
      event_summary: buildEventSummaryFromLegacy(o),
      binding_summary: buildBindingSummaryFromLegacy(o),
    }));
  }

  return [];
}

/**
 * 从 screen items 构建 binding 列表
 * @param {Object[]} screens
 * @returns {import('../types/hmi').HmiBindingSummary[]}
 */
function buildBindingsFromScreens(screens) {
  const result = [];
  for (const screen of screens) {
    const items = screen.items || [];
    for (const item of items) {
      const itemType = item.type && typeof item.type === 'object'
        ? (item.type.value || String(item.type))
        : String(item.type || '?');

      result.push({
        item_id: item.id || '?',
        item_name: item.name || item.id || '?',
        item_type: itemType.toLowerCase(),
        text: (item.text && item.text['zh-CN']) || '',
        template_ref: item.template_ref || null,
        prototype_id: item.prototype_id || null,
        tag: item.tag_binding || '',
        behavior: item.behavior && typeof item.behavior === 'object'
          ? (item.behavior.value || String(item.behavior))
          : (item.behavior || null),
        indicator_mode: item.indicator_mode && typeof item.indicator_mode === 'object'
          ? (item.indicator_mode.value || String(item.indicator_mode))
          : (item.indicator_mode || null),
        event_summary: buildEventSummary(item),
        binding_summary: buildBindingSummary(item),
      });
    }
  }
  return result;
}

function buildEventSummary(item) {
  const events = item.events || [];
  return events.map((ev) => {
    const evName = ev.event && typeof ev.event === 'object'
      ? (ev.event.value || String(ev.event))
      : String(ev.event || '?');
    const actions = (ev.actions || []).map((a) => {
      const aType = a.type && typeof a.type === 'object'
        ? (a.type.value || String(a.type))
        : String(a.type || '?');
      return a.tag ? `${aType}(${a.tag})` : aType;
    });
    return `${evName}: ${actions.join(', ')}`;
  }).join('; ');
}

function buildBindingSummary(item) {
  const bindings = item.bindings || [];
  return bindings.map((b) => {
    const prop = b.property || '?';
    const kind = b.kind && typeof b.kind === 'object'
      ? (b.kind.value || String(b.kind))
      : String(b.kind || '?');
    const tag = b.source_tag || b.tag || '';
    return `${prop}(${kind} → ${tag})`;
  }).join('; ');
}

function buildEventSummaryFromLegacy(o) {
  if (!o.events || !o.events.length) return '';
  return o.events.map((ev) => `${ev.event || '?'}: ${(ev.actions || []).join(', ')}`).join('; ');
}

function buildBindingSummaryFromLegacy(o) {
  if (!o.bindings || !o.bindings.length) return '';
  return o.bindings.map((b) => `${b.property || '?'}(${b.kind || '?'} → ${b.tag || ''})`).join('; ');
}

/**
 * 提取预览图 URL
 * @param {Object} input
 * @returns {string|null}
 */
export function extractPreviewImage(input) {
  if (!input) return null;
  return input.preview_url || input.preview_image || input.image_base64 || null;
}

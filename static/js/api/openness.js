/**
 * Openness API 封装 — TIA 连接/诊断/导出/同步
 */
import { getJson, postJson } from './request.js';

/** @returns {Promise<Object>} */
export function getOpennessStatus() {
  return getJson('/api/openness/status');
}

/** @returns {Promise<Object>} */
export function diagnoseOpenness() {
  return getJson('/api/openness/diagnose');
}

/** @param {Object} [payload] @returns {Promise<Object>} */
export function connectOpenness(payload = {}) {
  return postJson('/api/openness/connect', payload);
}

/** @returns {Promise<Object>} */
export function disconnectOpenness() {
  return postJson('/api/openness/disconnect', {});
}

/** @param {Object} payload @returns {Promise<Object>} */
export function exportTemplate(payload) {
  return postJson('/api/openness/export-template', payload);
}

/** @param {Object} payload @returns {Promise<Object>} */
export function exportReference(payload) {
  return postJson('/api/openness/export-reference', payload);
}

/** @param {Object} payload @returns {Promise<Object>} */
export function syncTags(payload) {
  return postJson('/api/openness/sync-tags', payload);
}

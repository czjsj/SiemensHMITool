/**
 * Template API 封装
 */
import { postJson } from './request.js';

/** @param {Object} payload @returns {Promise<Object>} */
export function buildTemplateXml(payload) {
  return postJson('/api/build/template-xml', payload);
}

/** @param {Object} payload @returns {Promise<Object>} */
export function buildTemplateV4(payload) {
  return postJson('/api/build/template-v4', payload);
}

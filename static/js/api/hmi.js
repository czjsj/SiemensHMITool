/**
 * HMI V4 API 封装 — 校验/计划/部署/验证/编译
 */
import { getJson, postJson } from './request.js';

/** @param {Object} payload @returns {Promise<Object>} */
export function validateHmiSpec(payload) {
  return postJson('/api/hmi/validate', payload);
}

/** @param {Object} payload @returns {Promise<Object>} */
export function getDeploymentPlan(payload) {
  return postJson('/api/hmi/plan', payload);
}

/** @param {Object} payload @returns {Promise<Object>} */
export function deployHmi(payload) {
  return postJson('/api/hmi/deploy', payload);
}

/** @param {Object} payload @returns {Promise<Object>} */
export function verifyHmi(payload) {
  return postJson('/api/hmi/verify', payload);
}

/** @param {Object} payload @returns {Promise<Object>} */
export function compileHmi(payload) {
  return postJson('/api/hmi/compile', payload);
}

/** @returns {Promise<Object>} */
export function getHmiCapabilities() {
  return getJson('/api/hmi/capabilities');
}

/** @returns {Promise<Object>} */
export function getRuntimeMetadata() {
  return getJson('/api/hmi/runtime-metadata');
}

/** @param {Object} payload @returns {Promise<Object>} */
export function getGenerationSummary(payload) {
  return postJson('/api/hmi/summary', payload);
}

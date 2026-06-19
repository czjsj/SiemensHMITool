/**
 * Openness 类型定义
 *
 * @typedef {Object} OpennessStatus
 * @property {boolean} [connected]
 * @property {string} [tia_version]
 * @property {string} [project_name]
 * @property {Object[]} [devices]
 * @property {import('./diagnostics').Diagnostic[]} [diagnostics]
 *
 * @typedef {Object} RuntimeMetadata
 * @property {string} [tia_version]
 * @property {boolean} [unified_available]
 * @property {string[]} [hmi_families]
 * @property {Object<string,any>} [capabilities]
 * @property {import('./diagnostics').Diagnostic[]} [diagnostics]
 */

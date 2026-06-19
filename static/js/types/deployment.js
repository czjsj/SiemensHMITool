/**
 * Deployment 类型定义
 *
 * @typedef {'IDLE'|'VALIDATING'|'VALIDATED'|'PLANNING'|'DRY_RUN'|'NOT_CONNECTED'|'BLOCKED'|'DEPLOYING'|'DEPLOYED'|'FAILED'|'VERIFYING'|'VERIFIED'|'COMPILING'|'COMPILED'} DeploymentStatus
 *
 * @typedef {Object} DeploymentStep
 * @property {string} [id]
 * @property {string} phase
 * @property {string} name
 * @property {string} [status]
 * @property {string[]} [depends_on]
 * @property {Object<string,any>} [payload]
 * @property {import('./diagnostics').Diagnostic[]} [diagnostics]
 *
 * @typedef {Object} DeploymentPlan
 * @property {string} [status]
 * @property {DeploymentStep[]} steps
 * @property {import('./diagnostics').Diagnostic[]} [diagnostics]
 * @property {Object<string,any>} [summary]
 *
 * @typedef {Object} DeploymentResult
 * @property {DeploymentStatus|string} status
 * @property {boolean} [success]
 * @property {string} [mode]
 * @property {import('./diagnostics').Diagnostic[]} [diagnostics]
 * @property {Object<string,any>} [tags]
 * @property {Object<string,any>} [screens]
 * @property {Object<string,any>} [items]
 * @property {Object<string,any>} [compile]
 * @property {Object<string,any>} [verification]
 * @property {Object<string,any>} [artifacts]
 */

/** @type {Object<string,string>} */
export const DEPLOYMENT_PHASES = {
  P00_PRECHECK: '预检查',
  P10_CONNECTIONS: '连接',
  P20_TAGS: '变量表',
  P30_TEXT_LISTS: '文本列表',
  P40_SCRIPTS: '脚本',
  P50_SCREENS: '画面',
  P60_COMPILE: '编译',
  P70_VERIFY: '验证',
  P80_REPORT: '报告',
  P90_ROLLBACK: '回滚',
};

/** @type {Object<string,string>} */
export const STATUS_LABELS = {
  IDLE: '未开始',
  VALIDATING: '正在校验',
  VALIDATED: '校验通过',
  PLANNING: '正在生成部署计划',
  DRY_RUN: '预演通过，未导入 TIA',
  NOT_CONNECTED: '未连接 TIA，无法真实部署',
  BLOCKED: '前置校验失败',
  DEPLOYING: '正在部署',
  DEPLOYED: '部署完成',
  FAILED: '部署失败',
  VERIFYING: '正在验证',
  VERIFIED: '验证完成',
  COMPILING: '正在编译',
  COMPILED: '编译完成',
};

/** @type {Object<string,string>} */
export const STATUS_COLORS = {
  IDLE: 'var(--text-muted)',
  VALIDATING: 'var(--accent)',
  VALIDATED: 'var(--success)',
  PLANNING: 'var(--accent)',
  DRY_RUN: 'var(--warning)',
  NOT_CONNECTED: 'var(--danger)',
  BLOCKED: 'var(--danger)',
  DEPLOYING: 'var(--accent)',
  DEPLOYED: 'var(--success)',
  FAILED: 'var(--danger)',
  VERIFYING: 'var(--accent)',
  VERIFIED: 'var(--success)',
  COMPILING: 'var(--accent)',
  COMPILED: 'var(--success)',
};

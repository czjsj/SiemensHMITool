/**
 * 生成事件标准化 — SSE 事件名映射为中文阶段名
 */

/** @type {Object<string,string>} */
const EVENT_TITLES = {
  thinking: 'AI 思考',
  content: 'AI 输出',
  start: '开始生成',
  ir_extracted: 'IR 已提取',
  ir_validated: 'IR 已校验',
  parsed_ok: '解析成功',
  parse_warn: '解析警告',
  variables_generated: '变量已生成',
  preview_rendered: '预览已渲染',
  review_completed: '视觉审查完成',
  xml_generated: 'XML 已生成',
  pipeline_start: '流水线开始',
  pipeline_done: '流水线完成',
  image_analysis_start: '图片分析',
  image_analysis_result: '图片分析完成',
  generate_start: '开始生成',
  review_start: '审查开始',
  review_progress: '审查中',
  review_result: '审查结果',
  review_pass: '审查通过',
  regenerate_start: '重新生成',
  deployment_completed: '部署完成',
  error: '错误',
  done: '完成',
};

/** @type {Object<string,'info'|'ok'|'warn'|'error'>} */
const EVENT_LEVELS = {
  thinking: 'info',
  content: 'info',
  start: 'info',
  ir_extracted: 'ok',
  ir_validated: 'ok',
  parsed_ok: 'ok',
  parse_warn: 'warn',
  variables_generated: 'ok',
  preview_rendered: 'ok',
  review_completed: 'ok',
  xml_generated: 'ok',
  pipeline_start: 'info',
  pipeline_done: 'ok',
  image_analysis_start: 'info',
  image_analysis_result: 'ok',
  generate_start: 'info',
  review_start: 'info',
  review_progress: 'info',
  review_result: 'warn',
  review_pass: 'ok',
  regenerate_start: 'warn',
  deployment_completed: 'ok',
  error: 'error',
  done: 'ok',
};

/**
 * 标准化生成事件
 * @param {string} eventName
 * @param {any} data
 * @returns {{eventName:string, title:string, level:string, data:any}}
 */
export function normalizeGenerationEvent(eventName, data) {
  return {
    eventName,
    title: EVENT_TITLES[eventName] || eventName,
    level: EVENT_LEVELS[eventName] || 'info',
    data,
  };
}

/**
 * 获取事件中文标题
 * @param {string} eventName
 * @returns {string}
 */
export function getEventTitle(eventName) {
  return EVENT_TITLES[eventName] || eventName;
}

/**
 * 获取事件级别
 * @param {string} eventName
 * @returns {'info'|'ok'|'warn'|'error'}
 */
export function getEventLevel(eventName) {
  return EVENT_LEVELS[eventName] || 'info';
}

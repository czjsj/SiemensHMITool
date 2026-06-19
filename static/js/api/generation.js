/**
 * Generation SSE API 封装
 */
import { streamPostSse } from '../utils/sse.js';

/**
 * @typedef {Object} GenerateOptions
 * @property {string} prompt
 * @property {boolean} [withReview]
 * @property {Object} [target]
 * @property {string} [template_xml]
 * @property {Object<string,any>} [config]
 * @property {string} [thinking_depth]
 * @property {boolean} [stream]
 * @property {File[]} [files]
 */

/**
 * SSE 流式生成
 * @param {GenerateOptions} options
 * @param {(eventName:string, data:any) => void} onEvent
 * @param {(error:any) => void} [onError]
 * @param {() => void} [onDone]
 * @returns {AbortController}
 */
export function streamGenerate(options, onEvent, onError, onDone) {
  const endpoint = options.withReview
    ? '/api/generate/with_review'
    : '/api/generate';

  return streamPostSse(endpoint, options, onEvent, onError, onDone);
}

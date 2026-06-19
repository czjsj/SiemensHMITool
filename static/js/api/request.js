/**
 * HTTP 请求工具 — 统一封装 fetch
 */
const BASE = '';

/**
 * GET JSON
 * @template T
 * @param {string} url
 * @returns {Promise<T>}
 */
export async function getJson(url) {
  const res = await fetch(BASE + url);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json();
}

/**
 * POST JSON
 * @template T
 * @param {string} url
 * @param {any} [payload]
 * @returns {Promise<T>}
 */
export async function postJson(url, payload = {}) {
  const res = await fetch(BASE + url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json();
}

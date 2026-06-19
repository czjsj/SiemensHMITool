/**
 * SSE 流式 POST 工具
 *
 * @typedef {Object} SseMessage
 * @property {string} event
 * @property {any} data
 * @property {string} [raw]
 */

/**
 * 发起 POST SSE 请求并流式解析事件
 * @param {string} url
 * @param {any} payload
 * @param {(msg: SseMessage) => void} onMessage
 * @param {(err: any) => void} [onError]
 * @param {() => void} [onDone]
 * @returns {AbortController}
 */
export function streamPostSse(url, payload, onMessage, onError, onDone) {
  const controller = new AbortController();
  const { signal } = controller;

  (async () => {
    let resp;
    try {
      const isMultipart = payload.files && payload.files.length > 0;
      if (isMultipart) {
        const fd = new FormData();
        fd.append('requirement', payload.prompt || payload.requirement || '');
        if (payload.thinking_depth) fd.append('thinking_depth', payload.thinking_depth);
        (payload.files || []).forEach((f) => fd.append('files', f));
        resp = await fetch(url, { method: 'POST', body: fd, signal });
      } else {
        resp = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
          signal,
        });
      }

      if (!resp.ok || !resp.body) {
        const txt = await resp.text().catch(() => '');
        const err = new Error(txt || `HTTP ${resp.status}`);
        if (onError) onError(err);
        if (onDone) onDone();
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split('\n\n');
        buffer = parts.pop();
        for (const part of parts) {
          const evLine = part.split('\n').find((l) => l.startsWith('event:'));
          const dataLine = part.split('\n').find((l) => l.startsWith('data:'));
          if (!dataLine) continue;

          const eventName = evLine ? evLine.slice(6).trim() : 'message';
          let data;
          const raw = dataLine.slice(5).trim();
          try {
            data = JSON.parse(raw);
          } catch {
            data = raw;
          }

          onMessage({ event: eventName, data, raw });
        }
      }
    } catch (e) {
      if (e.name !== 'AbortError' && onError) {
        onError(e);
      }
    } finally {
      if (onDone) onDone();
    }
  })();

  return controller;
}

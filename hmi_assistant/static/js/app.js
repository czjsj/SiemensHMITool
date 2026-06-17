/* ============================================================
   Siemens HMI 画面助手 —— 前端逻辑
   ============================================================ */
const $  = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

let CONFIG = null;
let LAST_BUILD = null;     // {ir, xml, xml_path, json_path}
let UPLOADED = [];         // File[]
let ABORT = null;          // 流式生成的 AbortController

// ---------------- 工具 ----------------
function toast(msg, isErr = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast show" + (isErr ? " err" : "");
  setTimeout(() => (t.className = "toast"), 2600);
}
function log(msg, cls = "") {
  const body = $("#logBody");
  const line = document.createElement("div");
  line.className = "log-line " + cls;
  const ts = new Date().toLocaleTimeString();
  line.textContent = `[${ts}] ${msg}`;
  body.appendChild(line);
  body.scrollTop = body.scrollHeight;
  if (body.style.display === "none") openLog();
}
function openLog() { $("#logBody").style.display = "block"; $("#logToggle").textContent = "收起"; }

// 取/设嵌套配置
function getPath(obj, path) { return path.split(".").reduce((o, k) => (o || {})[k], obj); }
function setPath(obj, path, val) {
  const ks = path.split("."); let o = obj;
  for (let i = 0; i < ks.length - 1; i++) { o[ks[i]] = o[ks[i]] || {}; o = o[ks[i]]; }
  o[ks[ks.length - 1]] = val;
}

// ---------------- 初始化 ----------------
async function init() {
  bindUI();
  await loadConfig();
}

async function loadConfig() {
  try {
    const r = await fetch("/api/config");
    const j = await r.json();
    CONFIG = j.config;
    $("#rawYaml").value = j.raw;
    populateModelSelect();
    fillConfigForm();
    fillSettingsModal();
    // 同步思考深度/选项控件
    $("#depthSelect").value = CONFIG.llm.thinking_depth || "中";
    $("#optShowThinking").checked = !!CONFIG.llm.show_thinking;
    $("#optStream").checked = !!CONFIG.llm.stream;
    $("#impCompile").checked = !!CONFIG.openness.compile_after_import;
    $("#impSave").checked = !!CONFIG.openness.save_after_import;
    $("#impBom").checked = (CONFIG.output.encoding === "utf-8-sig");
  } catch (e) { toast("加载配置失败：" + e, true); }
}

function populateModelSelect() {
  const sel = $("#modelSelect"); sel.innerHTML = "";
  const providers = CONFIG.llm.providers;
  Object.keys(providers).forEach((name) => {
    const p = providers[name];
    const opt = document.createElement("option");
    const configured = p.api_key ? "已配置" : "未配置";
    opt.value = name;
    opt.textContent = `${name} (${p.chat_model}) · ${configured}`;
    if (name === CONFIG.llm.active_provider) opt.selected = true;
    sel.appendChild(opt);
  });
}

function fillConfigForm() {
  $$("[data-cfg]").forEach((el) => {
    const v = getPath(CONFIG, el.dataset.cfg);
    if (v !== undefined && v !== null) el.value = v;
  });
  $$("[data-cfg-bool]").forEach((el) => {
    el.checked = !!getPath(CONFIG, el.dataset.cfgBool);
  });
}

function fillSettingsModal() {
  const sel = $("#setProvider"); sel.innerHTML = "";
  Object.keys(CONFIG.llm.providers).forEach((name) => {
    const opt = document.createElement("option");
    opt.value = name; opt.textContent = name;
    if (name === CONFIG.llm.active_provider) opt.selected = true;
    sel.appendChild(opt);
  });
  syncSettingsFields();
}
function syncSettingsFields() {
  const name = $("#setProvider").value;
  const p = CONFIG.llm.providers[name] || {};
  $("#setBaseUrl").value = p.base_url || "";
  $("#setApiKey").value = p.api_key || "";
  $("#setChatModel").value = p.chat_model || "";
  $("#setReasonerModel").value = p.reasoner_model || "";
  $("#setVision").checked = !!p.supports_vision;
}

// ---------------- 事件绑定 ----------------
function bindUI() {
  // 标签页
  $$(".tab").forEach((t) => t.addEventListener("click", () => {
    $$(".tab").forEach((x) => x.classList.remove("active"));
    $$(".tab-page").forEach((x) => x.classList.remove("active"));
    t.classList.add("active");
    $(`.tab-page[data-page="${t.dataset.tab}"]`).classList.add("active");
  }));

  // 主题
  $("#btnTheme").addEventListener("click", () => document.body.classList.toggle("light"));

  // 模型选择 -> 切换 active_provider
  $("#modelSelect").addEventListener("change", (e) => {
    CONFIG.llm.active_provider = e.target.value;
  });

  // 思考深度/选项实时写回内存
  $("#depthSelect").addEventListener("change", (e) => CONFIG.llm.thinking_depth = e.target.value);
  $("#optShowThinking").addEventListener("change", (e) => CONFIG.llm.show_thinking = e.target.checked);
  $("#optStream").addEventListener("change", (e) => CONFIG.llm.stream = e.target.checked);

  // 文件上传
  const dz = $("#dropzone"), fi = $("#fileInput");
  dz.addEventListener("click", () => fi.click());
  fi.addEventListener("change", () => addFiles(fi.files));
  ["dragover", "dragenter"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("drag"); }));
  dz.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));

  // 示例
  $$(".tag-btn").forEach((b) => b.addEventListener("click", () => fillExample(b.dataset.ex)));

  // 生成 / 停止
  $("#btnGenerate").addEventListener("click", startGenerate);
  $("#btnStop").addEventListener("click", () => { if (ABORT) ABORT.abort(); });

  // 输出工具
  $("#btnBuild").addEventListener("click", buildXml);
  $("#btnCopyOut").addEventListener("click", () => {
    navigator.clipboard.writeText($("#outputBody").innerText); toast("已复制输出");
  });
  $("#btnDownloadXml").addEventListener("click", downloadXml);

  // 思考折叠
  $("#thinkingHead").addEventListener("click", () => {
    const box = $("#thinkingBox");
    box.classList.toggle("collapsed");
    $("#thinkingToggle").textContent = box.classList.contains("collapsed") ? "展开" : "收起";
  });

  // 日志折叠
  $("#logHead").addEventListener("click", () => {
    const b = $("#logBody");
    const show = b.style.display === "none";
    b.style.display = show ? "block" : "none";
    $("#logToggle").textContent = show ? "收起" : "展开";
  });

  // 预览缩放
  $("#previewZoom").addEventListener("change", () => { if (LAST_BUILD) renderPreview(LAST_BUILD.ir); });

  // 配置：表单/原始切换
  $("#cfgModeForm").addEventListener("click", () => switchCfgMode("form"));
  $("#cfgModeRaw").addEventListener("click", () => switchCfgMode("raw"));
  $("#btnSaveConfig").addEventListener("click", saveConfigForm);
  $("#btnReloadConfig").addEventListener("click", loadConfig);
  $("#btnSaveRaw").addEventListener("click", saveRawYaml);

  // 设置模态
  $("#btnSettings").addEventListener("click", () => $("#settingsModal").classList.add("show"));
  $("#btnCloseSettings").addEventListener("click", () => $("#settingsModal").classList.remove("show"));
  $("#setProvider").addEventListener("change", syncSettingsFields);
  $("#btnSaveSettings").addEventListener("click", saveSettings);
  $("#btnTestKey").addEventListener("click", testConnection);

  // 诊断模态
  $("#btnDiagnose").addEventListener("click", openDiagnose);
  $("#btnCloseDiag").addEventListener("click", () => $("#diagModal").classList.remove("show"));
  $("#btnCloseDiag2").addEventListener("click", () => $("#diagModal").classList.remove("show"));
  $("#btnRediag").addEventListener("click", runDiagnose);

  // Openness
  $("#btnConnect").addEventListener("click", connectOpenness);
  $("#btnImport").addEventListener("click", importToTia);
}

// ---------------- 文件 ----------------
function addFiles(fileList) {
  for (const f of fileList) UPLOADED.push(f);
  renderChips();
}
function renderChips() {
  const host = $("#fileChips"); host.innerHTML = "";
  UPLOADED.forEach((f, i) => {
    const c = document.createElement("div");
    c.className = "chip";
    c.innerHTML = `<span>📎 ${f.name}</span><span class="x" data-i="${i}">✕</span>`;
    c.querySelector(".x").addEventListener("click", () => { UPLOADED.splice(i, 1); renderChips(); });
    host.appendChild(c);
  });
}

// ---------------- 示例 ----------------
const EXAMPLES = {
  "电机控制": "一个电机启停控制画面：启动/停止/复位三个按钮，运行指示灯、故障指示灯（故障时闪烁），显示电机转速（rpm）和当前运行模式（停止/手动/自动）。",
  "登录界面": "一个操作员登录界面：用户名和密码两个文本 IO 域，登录、退出两个按钮；登录按钮挂 VBS 脚本校验账号密码并提示，登录成功用指示灯表示在线状态。",
  "温度监控": "一个温度监控画面：显示三个测点的温度（℃）的文本 IO 域，每个测点配一个超温报警指示灯（超温时红色闪烁），一个复位报警按钮，一个用符号 IO 域显示的系统状态（正常/警告/故障）。",
  "流量动画": "一个管道流量画面：用文本 IO 域显示瞬时流量（m³/h）和累计流量，一个泵运行指示灯，启动/停止按钮，并用 VBS 脚本驱动一个流动动画变量在 0~100 之间循环步进表示介质流动。",
};
function fillExample(key) { $("#requirement").value = EXAMPLES[key] || ""; }

// ---------------- 流式生成 ----------------
async function startGenerate() {
  const requirement = $("#requirement").value.trim();
  if (!requirement) { toast("请先输入画面需求", true); return; }

  // 准备 UI
  $("#btnGenerate").style.display = "none";
  $("#btnStop").style.display = "inline-flex";
  $("#btnDownloadXml").disabled = true;
  $("#btnImport").disabled = true;
  LAST_BUILD = null;

  const out = $("#outputBody"); out.innerHTML = ""; out.textContent = "";
  const thinkBox = $("#thinkingBox"), thinkBody = $("#thinkingBody");
  const showThink = $("#optShowThinking").checked && $("#depthSelect").value !== "关闭";
  thinkBody.textContent = "";
  thinkBox.style.display = showThink ? "block" : "none";
  thinkBox.classList.remove("collapsed");
  $("#thinkingToggle").textContent = "收起";
  $("#thinkingHead").classList.add("active");

  // 组装请求（带文件用 multipart）
  ABORT = new AbortController();
  let resp;
  try {
    if (UPLOADED.length > 0) {
      const fd = new FormData();
      fd.append("requirement", requirement);
      fd.append("thinking_depth", $("#depthSelect").value);
      UPLOADED.forEach((f) => fd.append("files", f));
      resp = await fetch("/api/generate", { method: "POST", body: fd, signal: ABORT.signal });
    } else {
      resp = await fetch("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ requirement, thinking_depth: $("#depthSelect").value }),
        signal: ABORT.signal,
      });
    }
  } catch (e) { finishGenerate(); if (e.name !== "AbortError") toast("请求失败：" + e, true); return; }

  if (!resp.ok || !resp.body) {
    const txt = await resp.text().catch(() => "");
    out.textContent = "请求失败：" + txt; finishGenerate(); return;
  }

  // 读取 SSE 流
  const reader = resp.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let contentBuf = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop();
      for (const part of parts) {
        const line = part.split("\n").find((l) => l.startsWith("data:"));
        if (!line) continue;
        let payload;
        try { payload = JSON.parse(line.slice(5).trim()); } catch { continue; }
        handleEvent(payload, { out, thinkBody, contentRef: () => contentBuf, setContent: (v) => (contentBuf = v) });
        if (payload.event === "content") {
          contentBuf += payload.data;
          out.textContent = contentBuf;
          out.scrollTop = out.scrollHeight;
        }
      }
    }
  } catch (e) {
    if (e.name !== "AbortError") log("流读取异常：" + e, "err");
  }
  finishGenerate();
}

function handleEvent(payload, ctx) {
  const { event, data } = payload;
  switch (event) {
    case "start":
      log(`开始生成（思考深度=${data.depth}）`); break;
    case "thinking":
      ctx.thinkBody.textContent += data;
      ctx.thinkBody.scrollTop = ctx.thinkBody.scrollHeight; break;
    case "content":
      break; // 内容在外层累加
    case "parsed_ok":
      log(data.hint, "ok"); break;
    case "parse_warn":
      log(data, "warn"); break;
    case "error":
      log("错误：" + data, "err"); ctx.out.textContent += "\n\n[错误] " + data; toast(data, true); break;
    case "done":
      log("生成完成", "ok"); break;
  }
}

function finishGenerate() {
  $("#btnGenerate").style.display = "inline-flex";
  $("#btnStop").style.display = "none";
  $("#thinkingHead").classList.remove("active");
  ABORT = null;
}

// ---------------- 生成 XML + 预览 ----------------
async function buildXml() {
  const raw = $("#outputBody").innerText.trim();
  if (!raw) { toast("没有可用的模型输出", true); return; }
  log("正在校验 IR 并生成 SimaticML…");
  try {
    const r = await fetch("/api/build", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ raw_output: raw }),
    });
    const j = await r.json();
    if (!j.ok) { toast("生成失败：" + j.error, true); log("生成失败：" + j.error, "err"); return; }
    LAST_BUILD = j;
    (j.warnings || []).forEach((w) => log("⚠ " + w, "warn"));
    log(`已生成 XML：${j.xml_path}`, "ok");
    $("#btnDownloadXml").disabled = false;
    $("#btnImport").disabled = false;
    renderPreview(j.ir);
    // 跳到预览页
    $$(".tab").forEach((x) => x.classList.remove("active"));
    $$(".tab-page").forEach((x) => x.classList.remove("active"));
    $(`.tab[data-tab="preview"]`).classList.add("active");
    $(`.tab-page[data-page="preview"]`).classList.add("active");
    toast("画面已生成，可预览并导入");
  } catch (e) { toast("生成异常：" + e, true); }
}

function downloadXml() {
  if (!LAST_BUILD) return;
  const blob = new Blob([LAST_BUILD.xml], { type: "application/xml" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = (LAST_BUILD.ir.meta.screen_name || "screen") + ".xml";
  a.click();
}

// ---------------- IR -> SVG 预览 ----------------
function renderPreview(ir) {
  const host = $("#previewHost");
  const zoom = parseFloat($("#previewZoom").value);
  const W = ir._screen_size.width, H = ir._screen_size.height;
  $("#previewMeta").textContent =
    `${ir.meta.title}（${ir.meta.screen_name}） · ${W}×${H} · ${ir.meta.hmi_type} · 对象 ${ir.objects.length}`;

  const svg = [];
  svg.push(`<svg class="preview-canvas" width="${W * zoom}" height="${H * zoom}" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">`);
  svg.push(`<rect x="0" y="0" width="${W}" height="${H}" fill="#1f2630"/>`);

  for (const o of ir.objects) {
    svg.push(drawObject(o));
  }
  svg.push(`</svg>`);
  host.innerHTML = svg.join("");
}

function esc(s) { return String(s == null ? "" : s).replace(/[<>&]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" }[c])); }

function drawObject(o) {
  const fs = o.font_size || 16;
  switch (o.type) {
    case "Text": {
      const weight = o.bold ? "700" : "400";
      return `<text x="${o.x}" y="${o.y + fs}" fill="${o.color || "#e6edf3"}" font-size="${fs}" font-weight="${weight}" font-family="Arial">${esc(o.text)}</text>`;
    }
    case "IOField": {
      let g = labelSvg(o);
      g += rectField(o.x, o.y, o.width, o.height, "#0e1622", "#2a86ff");
      const sample = o.display_format === "String" ? "ABC" : "123";
      g += `<text x="${o.x + o.width / 2}" y="${o.y + o.height / 2 + fs / 3}" fill="#cfe3ff" font-size="${fs}" text-anchor="middle" font-family="Consolas">${sample}</text>`;
      if (o.unit) g += `<text x="${o.x + o.width + 8}" y="${o.y + o.height / 2 + fs / 3}" fill="#9aa7b4" font-size="${fs - 2}" font-family="Arial">${esc(o.unit)}</text>`;
      return g;
    }
    case "SymbolicIOField": {
      let g = labelSvg(o);
      g += rectField(o.x, o.y, o.width, o.height, "#15101f", "#8a5cff");
      g += `<text x="${o.x + 10}" y="${o.y + o.height / 2 + fs / 3}" fill="#d9caff" font-size="${fs}" font-family="Arial">${esc("〔列表〕")}</text>`;
      g += `<path d="M ${o.x + o.width - 18} ${o.y + o.height / 2 - 3} l 6 7 l 6 -7" stroke="#8a5cff" stroke-width="2" fill="none"/>`;
      return g;
    }
    case "Button": {
      const bg = o.background_color || "#27d17f";
      let g = `<rect x="${o.x}" y="${o.y}" width="${o.width}" height="${o.height}" rx="8" fill="${bg}" opacity="0.92"/>`;
      g += `<text x="${o.x + o.width / 2}" y="${o.y + o.height / 2 + 6}" fill="#06281f" font-size="17" font-weight="700" text-anchor="middle" font-family="Arial">${esc(o.text)}</text>`;
      if (o.press_script || o.click_script || o.release_script)
        g += `<circle cx="${o.x + o.width - 10}" cy="${o.y + 10}" r="4" fill="#06281f" opacity="0.7"/>`;
      return g;
    }
    case "Indicator": {
      const r = o.radius || 22;
      let g = `<circle cx="${o.x + r}" cy="${o.y + r}" r="${r}" fill="${o.color_on}" stroke="#0a0e14" stroke-width="2"/>`;
      g += `<circle cx="${o.x + r - r/3}" cy="${o.y + r - r/3}" r="${r/3.5}" fill="rgba(255,255,255,0.35)"/>`;
      if (o.blink) g += `<circle cx="${o.x + r}" cy="${o.y + r}" r="${r + 4}" fill="none" stroke="${o.color_on}" stroke-width="2" opacity="0.5"><animate attributeName="opacity" values="0.5;0;0.5" dur="1s" repeatCount="indefinite"/></circle>`;
      if (o.label) g += `<text x="${o.x + r}" y="${o.y + r * 2 + 16}" fill="#c9d3de" font-size="13" text-anchor="middle" font-family="Arial">${esc(o.label)}</text>`;
      return g;
    }
  }
  return "";
}
function rectField(x, y, w, h, fill, stroke) {
  return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="5" fill="${fill}" stroke="${stroke}" stroke-width="1.5"/>`;
}
function labelSvg(o) {
  if (!o.label) return "";
  return `<text x="${o.x - 8}" y="${o.y + (o.height || 40) / 2 + 5}" fill="#c9d3de" font-size="14" text-anchor="end" font-family="Arial">${esc(o.label)}</text>`;
}

// ---------------- 配置保存 ----------------
function switchCfgMode(mode) {
  const isForm = mode === "form";
  $("#cfgForm").style.display = isForm ? "block" : "none";
  $("#cfgRaw").style.display = isForm ? "none" : "block";
  $("#cfgModeForm").classList.toggle("active", isForm);
  $("#cfgModeRaw").classList.toggle("active", !isForm);
}
async function saveConfigForm() {
  // 把表单值写回 CONFIG
  $$("[data-cfg]").forEach((el) => setPath(CONFIG, el.dataset.cfg, el.value));
  $$("[data-cfg-bool]").forEach((el) => setPath(CONFIG, el.dataset.cfgBool, el.checked));
  try {
    const r = await fetch("/api/config", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config: CONFIG }),
    });
    const j = await r.json();
    if (j.ok) { CONFIG = j.config; $("#rawYaml").value = ""; await loadConfig(); toast("配置已保存"); }
    else toast("保存失败：" + j.error, true);
  } catch (e) { toast("保存异常：" + e, true); }
}
async function saveRawYaml() {
  try {
    const r = await fetch("/api/config/raw", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ raw: $("#rawYaml").value }),
    });
    const j = await r.json();
    if (j.ok) { CONFIG = j.config; await loadConfig(); toast("YAML 已保存"); }
    else toast("保存失败：" + j.error, true);
  } catch (e) { toast("保存异常：" + e, true); }
}

// ---------------- 设置（模型接口） ----------------
async function saveSettings() {
  const name = $("#setProvider").value;
  const p = CONFIG.llm.providers[name];
  p.base_url = $("#setBaseUrl").value.trim();
  p.api_key = $("#setApiKey").value.trim();
  p.chat_model = $("#setChatModel").value.trim();
  p.reasoner_model = $("#setReasonerModel").value.trim();
  p.supports_vision = $("#setVision").checked;
  CONFIG.llm.active_provider = name;
  try {
    const r = await fetch("/api/config", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config: CONFIG }),
    });
    const j = await r.json();
    if (j.ok) { CONFIG = j.config; populateModelSelect(); $("#settingsModal").classList.remove("show"); toast("设置已保存"); }
    else toast("保存失败：" + j.error, true);
  } catch (e) { toast("保存异常：" + e, true); }
}
async function testConnection() {
  // 用一条极短的生成请求探活
  toast("正在测试…");
  await saveSettings();
  try {
    const resp = await fetch("/api/generate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ requirement: "仅回复 OK 两个字母用于连通性测试。", thinking_depth: "关闭" }),
    });
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = "", ok = false, err = "";
    while (true) {
      const { done, value } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split("\n\n"); buf = parts.pop();
      for (const part of parts) {
        const line = part.split("\n").find((l) => l.startsWith("data:")); if (!line) continue;
        const pl = JSON.parse(line.slice(5).trim());
        if (pl.event === "content") ok = true;
        if (pl.event === "error") err = pl.data;
      }
    }
    if (ok) toast("连接正常 ✓"); else toast("连接失败：" + (err || "无响应"), true);
  } catch (e) { toast("测试失败：" + e, true); }
}

// ---------------- Openness ----------------
async function connectOpenness() {
  $("#btnConnect").disabled = true; $("#btnConnect").textContent = "连接中…";
  try {
    const r = await fetch("/api/openness/connect", { method: "POST" });
    const j = await r.json();
    if (j.connected) {
      $("#connDot").classList.add("online");
      $("#connTitle").textContent = "已连接";
      $("#connSub").textContent = j.project_name ? ("项目：" + j.project_name) : "";
      log(j.message || "已连接", "ok"); toast("已连接到博途");
      $("#btnConnect").textContent = "已连接";
    } else {
      log("连接失败：" + j.error, "err"); toast("连接失败：" + j.error, true);
      $("#btnConnect").textContent = "连接"; $("#btnConnect").disabled = false;
      if (j.diagnose) showDiag(j.diagnose);
    }
  } catch (e) {
    toast("连接异常：" + e, true); $("#btnConnect").textContent = "连接"; $("#btnConnect").disabled = false;
  }
}

async function importToTia() {
  if (!LAST_BUILD) { toast("请先生成画面", true); return; }
  // 同步导入选项到配置（仅本地展示用，真实导入读服务端配置）
  $("#btnImport").disabled = true; $("#btnImport").textContent = "导入中…";
  log("开始导入到博途…");
  try {
    const r = await fetch("/api/openness/import", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ xml_path: LAST_BUILD.xml_path }),
    });
    const j = await r.json();
    if (j.imported) { log(j.message || "导入成功", "ok"); toast("已导入到博途"); }
    else { log("导入失败：" + j.error, "err"); toast("导入失败：" + j.error, true); }
  } catch (e) { toast("导入异常：" + e, true); log("导入异常：" + e, "err"); }
  $("#btnImport").disabled = false; $("#btnImport").textContent = "导入到博途";
}

// ---------------- 诊断 ----------------
function openDiagnose() { $("#diagModal").classList.add("show"); runDiagnose(); }
async function runDiagnose() {
  $("#diagBody").textContent = "检测中…";
  try {
    const r = await fetch("/api/openness/diagnose");
    showDiag(await r.json());
  } catch (e) { $("#diagBody").textContent = "诊断失败：" + e; }
}
function showDiag(d) {
  const row = (label, ok, val) =>
    `<div class="diag-item"><span class="${ok ? "diag-ok" : "diag-bad"}">${ok ? "✓" : "✕"}</span>
     <span class="b">${label}</span><span style="color:var(--text-muted)">${val ?? ""}</span></div>`;
  let html = "";
  html += row("操作系统", d.is_windows, d.os);
  html += row("pythonnet", d.pythonnet_installed, d.pythonnet_installed ? "已安装" : "未安装");
  html += row("Openness DLL", d.dll_exists, d.dll_path);
  html += row("博途进程", (d.running_tia_processes || []).length > 0, (d.running_tia_processes || []).join(", ") || "未发现");
  html += `<div class="diag-item"><span>ℹ</span><span>${d.openness_group_hint || ""}</span></div>`;
  html += `<div style="margin-top:10px;padding:10px;border-radius:8px;background:var(--bg-input);font-size:12px;color:var(--text-sec)">`;
  (d.messages || []).forEach((m) => html += "· " + m + "<br>");
  html += `</div>`;
  $("#diagBody").innerHTML = html;
  $("#diagModal").classList.add("show");
}

window.addEventListener("DOMContentLoaded", init);

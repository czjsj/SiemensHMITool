/* ============================================================
   Siemens HMI 画面助手 —— 前端逻辑
   ============================================================ */
const $  = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

let CONFIG = null;
let LAST_BUILD = null;     // {ir, xml, xml_path, json_path}
let UPLOADED = [];         // File[]
let ABORT = null;          // 流式生成的 AbortController
let REVIEW_ENABLED = false; // 视觉审查开关
let PIPELINE_IR = null;     // 流水线最终 IR（供 build 使用）

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
    // 审查开关同步
    REVIEW_ENABLED = !!(CONFIG.mimo && CONFIG.mimo.enabled && CONFIG.mimo.api_key);
    $("#optReview").checked = REVIEW_ENABLED;
    $("#impSave").checked = !!CONFIG.openness.save_after_import;
    $("#impBom").checked = (CONFIG.output.encoding === "utf-8-sig");
    // 初始化生成模式选择
    const genMode = CONFIG.openness.generation_mode || "auto";
    $("#impMode").value = genMode;
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

  // MiMo 字段（独立于 LLM provider）
  const mimo = CONFIG.mimo || {};
  $("#setMimoEnabled").checked = !!mimo.enabled;
  $("#setMimoBaseUrl").value = mimo.base_url || "https://api.xiaomimimo.com/v1";
  $("#setMimoApiKey").value = mimo.api_key || "";
  $("#setMimoModel").value = mimo.model || "mimo-v2.5";
  $("#setMimoMaxIter").value = mimo.max_iterations || 3;
  $("#setMimoThreshold").value = mimo.review_pass_threshold || 70;
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
  $("#optReview").addEventListener("change", (e) => REVIEW_ENABLED = e.target.checked);

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
  $("#btnCalibrate").addEventListener("click", calibrateReference);
  $("#btnImport").addEventListener("click", importToTia);

  // 模板导出
  $("#btnExportTemplate").addEventListener("click", () => $("#exportTemplateModal").classList.add("show"));
  $("#btnCloseExport").addEventListener("click", () => $("#exportTemplateModal").classList.remove("show"));
  $("#btnCloseExport2").addEventListener("click", () => $("#exportTemplateModal").classList.remove("show"));
  $("#btnDoExport").addEventListener("click", exportTemplate);
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

  // 组装请求（带文件用 multipart）；审查模式走专用端点
  const endpoint = REVIEW_ENABLED ? "/api/generate/with_review" : "/api/generate";
  ABORT = new AbortController();
  let resp;
  try {
    if (UPLOADED.length > 0) {
      const fd = new FormData();
      fd.append("requirement", requirement);
      fd.append("thinking_depth", $("#depthSelect").value);
      UPLOADED.forEach((f) => fd.append("files", f));
      resp = await fetch(endpoint, { method: "POST", body: fd, signal: ABORT.signal });
    } else {
      resp = await fetch(endpoint, {
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
      if (data.pipeline) {
        log(`开始流水线生成（视觉审查模式）`);
        showPipelineUI(true);
        PIPELINE_IR = null;
      } else {
        log(`开始生成（思考深度=${data.depth}）`);
        showPipelineUI(false);
      }
      break;
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

    // ---- 流水线事件 ----
    case "pipeline_start":
      showPipelineUI(true);
      updatePipelineTitle("准备生成…");
      updatePipelineIter("-", data.max_iterations);
      initPipelineSteps(data.max_iterations);
      PIPELINE_IR = null;
      break;
    case "image_analysis_start":
      updatePipelineTitle("正在分析上传的参考图片…");
      log("正在用 MiMo 分析上传图片…");
      break;
    case "image_analysis_result":
      if (data.summary) log("参考图片分析完成", "ok");
      else log("参考图片无需额外分析");
      break;
    case "generate_start":
      updatePipelineTitle(`第 ${data.stage} 轮：AI 生成画面中…`);
      updatePipelineStep(0, "active");
      break;
    case "review_start":
      updatePipelineTitle(`第 ${data.iteration} 轮视觉审查`);
      updatePipelineIter(data.iteration);
      setPipelineStep(0, "completed");
      setPipelineStep(1, "active");
      break;
    case "review_progress":
      if (data.status === "rendering") {
        updatePipelineTitle("正在渲染预览图…");
      } else if (data.status === "analyzing") {
        updatePipelineTitle("MiMo 正在审查画面…");
      } else if (data.status === "review_skipped") {
        log("视觉审查跳过：" + data.reason, "warn");
        updatePipelineTitle("审查跳过");
      }
      break;
    case "review_result":
      setPipelineStep(1, "completed");
      renderReviewResult(data);
      const passed = data.pass;
      log(`审查结果: ${passed ? "✓ 通过" : "✕ 需改进"}（${data.score}分）`, passed ? "ok" : "warn");
      break;
    case "review_pass":
      setPipelineStep(2, "completed");
      updatePipelineTitle(`审查通过！(${data.score}分)`);
      PIPELINE_IR = data.ir;
      $("#btnDownloadXml").disabled = false;
      $("#btnImport").disabled = false;
      autoBuildPreview();
      break;
    case "regenerate_start":
      updatePipelineTitle(`第 ${data.iteration} 轮：根据审查意见修正…`);
      setPipelineStep(1, "completed");
      setPipelineStep(2, "active");
      log(`开始第${data.iteration}轮修正，关键问题: ${(data.issues||[]).join("; ") || "无"}`, "warn");
      break;
    case "pipeline_done":
      setPipelineStep(1, setPipelineStep(2, "completed") || "completed");
      if (data.passed === true) {
        updatePipelineTitle(`审查通过！(${data.final_score}分)`);
      } else if (data.passed === false) {
        updatePipelineTitle(`达到最大迭代次数 (${data.final_score}分)`);
      } else {
        updatePipelineTitle("完成（未审查）");
      }
      if (data.ir) {
        PIPELINE_IR = data.ir;
        autoBuildPreview();
      }
      if (data.passed === true) {
        $("#btnDownloadXml").disabled = false;
        $("#btnImport").disabled = false;
      }
      log(`流水线完成: ${data.note || (data.passed ? '审查通过' : '已返回最佳结果')}`, data.passed ? "ok" : "warn");
      break;
  }
}

function finishGenerate() {
  $("#btnGenerate").style.display = "inline-flex";
  $("#btnStop").style.display = "none";
  $("#thinkingHead").classList.remove("active");
  ABORT = null;
  // 审查模式下不自动隐藏 pipeline UI
  if (!REVIEW_ENABLED) showPipelineUI(false);
}

// ---------------- 流水线进度 UI ----------------
function showPipelineUI(show) {
  const panel = $("#pipelineProgress");
  if (panel) panel.style.display = show ? "block" : "none";
  if (show) {
    $("#reviewResult").style.display = "none";
  }
}

function updatePipelineTitle(text) {
  const el = $("#pipelineTitle");
  if (el) el.textContent = text;
}

function updatePipelineIter(current, max) {
  const el = $("#pipelineIter");
  if (el) el.textContent = max ? `${current}/${max}` : String(current);
}

function initPipelineSteps(maxIter) {
  const host = $("#pipelineSteps");
  if (!host) return;
  host.innerHTML = "";
  const steps = ["生成初始画面", "MiMo 视觉审查"];
  if (maxIter > 1) steps.push("修正画面");
  steps.forEach((label, i) => {
    const div = document.createElement("div");
    div.className = "pipeline-step";
    div.id = "pipeStep" + i;
    div.innerHTML = `<span class="step-dot">${i + 1}</span><span class="step-label">${label}</span>`;
    host.appendChild(div);
  });
}

function setPipelineStep(idx, status) {
  const el = document.getElementById("pipeStep" + idx);
  if (el) {
    el.classList.remove("active", "completed", "failed");
    if (status) el.classList.add(status);
  }
  return status;
}

function updatePipelineStep(idx, status) {
  setPipelineStep(idx, status);
}

function renderReviewResult(data) {
  const host = $("#reviewResult");
  if (!host) return;
  host.style.display = "block";

  const passIcon = data.pass ? "✓" : "✕";
  const passClass = data.pass ? "pass" : "fail";
  const catLabels = {
    layout_alignment: "布局对齐", component_sizing: "组件尺寸",
    color_conventions: "颜色规范", text_readability: "文字可读性",
    completeness: "元素完整性", professional_quality: "专业质量",
  };

  let catHtml = "";
  const cats = data.categories || {};
  Object.keys(catLabels).forEach((k) => {
    const c = cats[k] || {};
    const catPass = c.pass !== false;
    const issues = c.issues || [];
    catHtml += `<div class="review-category ${catPass ? "pass" : "fail"}">
      <span class="cat-icon">${catPass ? "✓" : "✕"}</span>
      <span class="cat-label">${catLabels[k]}</span>
      ${issues.length ? '<span class="cat-count">' + issues.length + ' 个问题</span>' : '<span class="cat-count ok">无问题</span>'}
    </div>`;
    if (issues.length) {
      catHtml += '<ul class="review-issues">' + issues.map((s) => "<li>" + esc(s) + "</li>").join("") + "</ul>";
    }
  });

  let criticalHtml = "";
  if ((data.critical_issues || []).length) {
    criticalHtml = '<div class="review-critical"><strong>⚠ 关键问题</strong><ul>' +
      data.critical_issues.map((s) => "<li>" + esc(s) + "</li>").join("") + "</ul></div>";
  }

  let sugHtml = "";
  if ((data.suggestions || []).length) {
    sugHtml = '<div class="review-suggestions"><strong>改进建议</strong><ul>' +
      data.suggestions.map((s) => "<li>" + esc(s) + "</li>").join("") + "</ul></div>";
  }

  host.innerHTML = `
    <div class="review-banner ${passClass}">
      <span class="review-pass-icon">${passIcon}</span>
      <span class="review-score-big">${data.score}</span><span class="review-score-unit">/100</span>
      <span class="review-summary">${esc(data.summary || "")}</span>
    </div>
    <div class="review-categories">${catHtml}</div>
    ${criticalHtml}
    ${sugHtml}
  `;
}

// ---------------- 生成 XML + 预览 ----------------
async function autoBuildPreview() {
  // 后台静默构建预览（审查流水线完成后自动调用，不切换标签页、不弹 toast）
  if (!PIPELINE_IR) return;
  try {
    const r = await fetch("/api/build", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ raw_output: JSON.stringify(PIPELINE_IR) }),
    });
    const j = await r.json();
    if (j.ok) {
      LAST_BUILD = j;
      renderPreview(j.ir);
      (j.warnings || []).forEach((w) => log("⚠ " + w, "warn"));
      log("预览已就绪，可切换到「画面预览」查看", "ok");
    }
  } catch (e) { /* 静默失败，用户可手动点击生成 XML */ }
}

async function buildXml() {
  // 审查模式下优先使用流水线 IR
  let raw;
  if (PIPELINE_IR) {
    raw = JSON.stringify(PIPELINE_IR);
  } else {
    raw = $("#outputBody").innerText.trim();
  }
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

  // 保存 MiMo 配置
  const mimo = CONFIG.mimo || {};
  mimo.enabled = $("#setMimoEnabled").checked;
  mimo.base_url = $("#setMimoBaseUrl").value.trim() || "https://api.xiaomimimo.com/v1";
  mimo.api_key = $("#setMimoApiKey").value.trim();
  mimo.model = $("#setMimoModel").value.trim() || "mimo-v2.5";
  mimo.max_iterations = parseInt($("#setMimoMaxIter").value) || 3;
  mimo.review_pass_threshold = parseInt($("#setMimoThreshold").value) || 70;
  CONFIG.mimo = mimo;

  try {
    const r = await fetch("/api/config", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config: CONFIG }),
    });
    const j = await r.json();
    if (j.ok) { CONFIG = j.config; populateModelSelect(); REVIEW_ENABLED = CONFIG.mimo.enabled && !!CONFIG.mimo.api_key; $("#optReview").checked = REVIEW_ENABLED; $("#settingsModal").classList.remove("show"); toast("设置已保存"); }
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
      $("#btnCalibrate").disabled = false;
      // 自动提醒校准
      if (!CONFIG.output || !CONFIG.output.reference_xml) {
        log("⚠ 建议点击「校准」按钮，从博途导出一个参考画面以匹配 SimaticML 格式", "warn");
        toast("连接成功！建议点击「校准」以适配当前 TIA 版本");
      }
      // 获取 HMI 能力信息
      fetchCapabilities();
    } else {
      const errMsg = j.message || j.error || "未知错误";
      log("连接失败：" + errMsg, "err"); toast("连接失败：" + errMsg, true);
      $("#btnConnect").textContent = "连接"; $("#btnConnect").disabled = false;
      if (j.diagnose) showDiag(j.diagnose);
    }
  } catch (e) {
    toast("连接异常：" + e, true); $("#btnConnect").textContent = "连接"; $("#btnConnect").disabled = false;
  }
}

async function fetchCapabilities() {
  try {
    const r = await fetch("/api/openness/capabilities");
    const caps = await r.json();
    showHmiCapabilities(caps);
  } catch (e) { /* 静默失败 */ }
}

function showHmiCapabilities(caps) {
  const bar = $("#hmiCapBar");
  if (!bar) return;
  bar.style.display = "flex";
  $("#hmiCapDevice").textContent = caps.hmi_device || "-";
  $("#hmiCapType").textContent = caps.hmi_software_type || "Unknown";
  // 显示推荐模式
  const modeLabels = { unified_direct: "Unified 直接绘制", classic_template_xml: "经典模板 XML", simaticml: "SimaticML 导入" };
  $("#hmiCapMode").textContent = modeLabels[caps.recommended_mode] || caps.recommended_mode || "-";
  $("#hmiCapScreens").textContent = (caps.available_screens || []).join(", ") || "无";

  // 自动设置导入模式选择
  if (caps.recommended_mode && caps.recommended_mode !== "simaticml") {
    $("#impMode").value = caps.recommended_mode;
  }

  // 警告
  const warnEl = $("#hmiCapWarn");
  if (caps.warnings && caps.warnings.length > 0) {
    warnEl.style.display = "inline";
    warnEl.textContent = "⚠ " + caps.warnings.join("; ");
  } else {
    warnEl.style.display = "none";
  }
}

async function calibrateReference() {
  $("#btnCalibrate").disabled = true; $("#btnCalibrate").textContent = "校准中…";
  log("正在从博途导出参考画面…");
  try {
    const r = await fetch("/api/openness/export-reference", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ screen_name: "" }),
    });
    const j = await r.json();
    if (j.ok) {
      log(j.message || "校准完成", "ok");
      toast("格式校准完成！已匹配当前 TIA 版本");
      (j.warnings || []).forEach((w) => log("⚠ " + w, "warn"));
      await loadConfig();
    } else {
      const errMsg = j.message || j.error || "未知错误";
      log("校准失败：" + errMsg, "err");
      // 显示诊断详情（attempts）
      if (j.details && j.details.attempts) {
        j.details.attempts.forEach((a) => {
          log(`  尝试: ${a.method} → ${a.error}`, "err");
        });
      }
      toast("校准失败：" + errMsg, true);
    }
  } catch (e) {
    toast("校准异常：" + e, true); log("校准异常：" + e, "err");
  }
  $("#btnCalibrate").disabled = false; $("#btnCalibrate").textContent = "校准";
}

async function importToTia() {
  if (!LAST_BUILD && !PIPELINE_IR) { toast("请先生成画面", true); return; }

  const mode = $("#impMode").value || "auto";
  $("#btnImport").disabled = true; $("#btnImport").textContent = "导入中…";
  log(`开始导入到博途（模式: ${mode}）…`);
  try {
    // 新双路线模式：传 IR + mode（优先）
    let body;
    if (PIPELINE_IR) {
      body = { ir: PIPELINE_IR, mode: mode };
    } else if (LAST_BUILD && LAST_BUILD.ir) {
      body = { ir: LAST_BUILD.ir, mode: mode };
    } else {
      body = { xml_path: (LAST_BUILD || {}).xml_path };
    }
    const r = await fetch("/api/openness/import", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const j = await r.json();

    // 处理新格式响应（含 mode / hmi_type / warnings / details）
    if (j.mode) {
      const modeLabels = { unified_direct: "Unified 直接绘制", classic_template_xml: "经典模板 XML", simaticml: "SimaticML 导入" };
      log(`使用模式: ${modeLabels[j.mode] || j.mode}（HMI 类型: ${j.hmi_type || "?"}）`, "ok");
      if (j.details && j.details.generated_xml_path) {
        log(`生成 XML: ${j.details.generated_xml_path}`);
      }
      if (j.details && j.details.xml_path) {
        log(`XML 路径: ${j.details.xml_path}`);
      }
      if (j.objects_created) {
        j.objects_created.forEach((o) => {
          const cls = o.status === "created" ? "ok" : (o.status === "failed" ? "err" : "warn");
          log(`  ${o.status === "created" ? "✓" : "✕"} ${o.object_id} (${o.object_type}): ${o.message}`, cls);
        });
      }
    }

    if (j.ok || j.imported) {
      log(j.message || "导入成功", "ok");
      toast("已导入到博途");
    } else {
      const errMsg = j.message || j.error || "未知错误";
      log("导入失败：" + errMsg, "err");
      toast("导入失败：" + errMsg, true);
    }

    // 显示 warnings
    (j.warnings || []).forEach((w) => log("⚠ " + w, "warn"));
  } catch (e) { toast("导入异常：" + e, true); log("导入异常：" + e, "err"); }
  $("#btnImport").disabled = false; $("#btnImport").textContent = "导入到博途";
}

// ---------------- 模板导出 ----------------
async function exportTemplate() {
  const screenName = $("#exportScreenName").value.trim();
  const exportDir = $("#exportDir").value.trim();
  if (!screenName) { toast("请输入模板画面名称", true); return; }

  $("#btnDoExport").disabled = true; $("#btnDoExport").textContent = "导出中…";
  log(`正在导出模板画面 '${screenName}' …`);
  try {
    const r = await fetch("/api/openness/export-template", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ screen_name: screenName, export_dir: exportDir || undefined, overwrite: true }),
    });
    const j = await r.json();
    if (j.ok) {
      log(`模板 XML 已导出: ${j.xml_path}`, "ok");
      log(`导出方法: ${(j.details && j.details.export_method) || "未知"}`, "ok");
      toast(`模板 "${j.screen_name}" 导出成功！`);
      (j.warnings || []).forEach((w) => log("⚠ " + w, "warn"));
      $("#exportTemplateModal").classList.remove("show");
      await loadConfig();
    } else {
      const errMsg = j.message || j.error || "未知错误";
      log("导出失败：" + errMsg, "err");
      // 显示诊断详情
      if (j.details && j.details.attempts) {
        j.details.attempts.forEach((a) => {
          log(`  尝试: ${a.method} → ${a.error}`, "err");
        });
      }
      (j.warnings || []).forEach((w) => log("⚠ " + w, "warn"));
      if (j.available_screens) {
        log(`可用画面: ${j.available_screens.join(", ")}`, "warn");
      }
      toast("导出失败：" + errMsg, true);
    }
  } catch (e) {
    toast("导出异常：" + e, true); log("导出异常：" + e, "err");
  }
  $("#btnDoExport").disabled = false; $("#btnDoExport").textContent = "导出";
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

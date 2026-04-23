const contentInput = document.getElementById("content-input");
const contentPreview = document.getElementById("content-preview");
const runBtn = document.getElementById("run-btn");

function setRunButtonsDisabled(disabled) {
  if (runBtn) {
    runBtn.disabled = disabled;
    runBtn.classList.toggle("is-loading", disabled);
  }
}
const cancelBtn = document.getElementById("cancel-btn");
const statusText =
  document.querySelector("#workspace-shell #status-text.sr-only") ||
  document.getElementById("status-text");
const progressBar = document.getElementById("progress-bar");
const resultGallery = document.getElementById("result-gallery");
const loadingOverlay = document.getElementById("loading-overlay");
const progressHud = document.getElementById("progress-hud");
const progressValue = document.getElementById("progress-value");
const progressPhase = document.getElementById("progress-phase");
const progressMeter = document.getElementById("progress-meter");
const generatingOverlay = document.getElementById("generating-overlay");
const genCanvas = document.getElementById("gen-canvas");
const genPercent = document.getElementById("gen-percent");
const genSteps = document.getElementById("gen-steps");

const denoiseInput = document.getElementById("denoise-input");
const denoiseValue = document.getElementById("denoise-value");
const stepsInput = document.getElementById("steps-input");
const stepsValue = document.getElementById("steps-value");
const guidanceInput = document.getElementById("guidance-input");
const guidanceValue = document.getElementById("guidance-value");
const quickModeInput = document.getElementById("quick-mode-input");
const sdStyleSelect = document.getElementById("sd-style-select");
const promptInput = document.getElementById("prompt-input");
const negativePromptInput = document.getElementById("negative-prompt-input");
const positivePresetSelect = document.getElementById("positive-preset-select");
const negativePresetSelect = document.getElementById("negative-preset-select");
const clearPositiveBtn = document.getElementById("clear-positive-btn");
const clearNegativeBtn = document.getElementById("clear-negative-btn");
const resetPromptsBtn = document.getElementById("reset-prompts-btn");
const analyzeInputBtn = document.getElementById("analyze-input-btn");
const applySuggestionBtn = document.getElementById("apply-suggestion-btn");
const analyzeResultText = document.getElementById("analyze-result-text");
const pauseJobBtn = document.getElementById("pause-job-btn");
const resumeJobBtn = document.getElementById("resume-job-btn");
const cancelJobBtn = document.getElementById("cancel-job-btn");
const exportCompareBatchBtn = document.getElementById("export-compare-batch-btn");
const exportNineGridBtn = document.getElementById("export-nine-grid-btn");
const exportTransitionBtn = document.getElementById("export-transition-btn");
const buildShareCardBtn = document.getElementById("build-share-card-btn");
const buildXhsCoverBtn = document.getElementById("build-xhs-cover-btn");
const buildDyCoverBtn = document.getElementById("build-dy-cover-btn");
const shareResultText = document.getElementById("share-result-text");

/** 下载文件名前缀（与 /api/result 的 label 对应） */
const PAGE_DOWNLOAD_LABEL = "sd-img2img";

let currentJobId = null;
let pollingTimer = null;

let queueFiles = [];
let queueIdx = 0;
let latestAnalyzeSuggestion = null;
const finishedJobIds = [];
let genCtx = null;
let genFrame = null;
let genParticles = [];
let genProgress = 0;

const PHASE_LABELS = {
  pending: "排队",
  downloading: "下载模型",
  loading_model: "加载模型",
  running: "推理中",
  done: "完成",
  error: "出错",
};

function nextPollMs() {
  return typeof ClientHelpers !== "undefined" && ClientHelpers.pollDelayMs ? ClientHelpers.pollDelayMs() : 700;
}

function showUiNotice(message, kind = "info") {
  if (statusText) statusText.textContent = message;
  const banner = document.getElementById("queue-banner");
  if (banner) {
    banner.hidden = false;
    banner.textContent = message;
    banner.classList.remove("text-red-300", "text-emerald-300", "text-slate-400");
    if (kind === "error") banner.classList.add("text-red-300");
    else if (kind === "success") banner.classList.add("text-emerald-300");
    else banner.classList.add("text-slate-400");
  }
  const placeholder = document.getElementById("result-placeholder");
  if (placeholder && !currentJobId) {
    placeholder.textContent = message;
  }
  if (progressPhase && kind !== "success") progressPhase.textContent = message;
}

function setProgressHud(visible, phaseText = "", percent = 0) {
  if (progressHud) progressHud.classList.toggle("hidden", !visible);
  const safe = Math.max(0, Math.min(100, Number(percent || 0)));
  if (progressValue) progressValue.textContent = `${Math.round(safe)}%`;
  if (progressMeter) progressMeter.style.width = `${safe}%`;
  if (progressPhase && phaseText) progressPhase.textContent = phaseText;
}

function ensureGenerationCanvas() {
  if (!genCanvas || !generatingOverlay) return false;
  const rect = generatingOverlay.getBoundingClientRect();
  const w = Math.max(320, Math.round(rect.width));
  const h = Math.max(320, Math.round(rect.height));
  if (genCanvas.width !== w || genCanvas.height !== h) {
    genCanvas.width = w;
    genCanvas.height = h;
  }
  if (!genCtx) genCtx = genCanvas.getContext("2d");
  return !!genCtx;
}

function seedGenerationParticles() {
  if (!ensureGenerationCanvas()) return;
  const w = genCanvas.width;
  const h = genCanvas.height;
  genParticles = Array.from({ length: 140 }, () => ({
    angle: Math.random() * Math.PI * 2,
    radius: 8 + Math.random() * Math.min(w, h) * 0.06,
    speed: 0.4 + Math.random() * 1.5,
    size: 0.8 + Math.random() * 1.2,
    life: 0.45 + Math.random() * 0.55,
    spin: (Math.random() - 0.5) * 0.08,
    twinkle: Math.random() * Math.PI * 2,
    orbit: 0.14 + Math.random() * 0.6,
  }));
}

function drawAnimeStar(ctx, x, y, size, rotation, hue, alpha) {
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(rotation);
  ctx.beginPath();
  for (let i = 0; i < 5; i++) {
    const outer = (-Math.PI / 2) + (i * Math.PI * 2) / 5;
    const inner = outer + Math.PI / 5;
    ctx.lineTo(Math.cos(outer) * size, Math.sin(outer) * size);
    ctx.lineTo(Math.cos(inner) * (size * 0.42), Math.sin(inner) * (size * 0.42));
  }
  ctx.closePath();
  ctx.fillStyle = `hsla(${hue}, 100%, 80%, ${alpha})`;
  ctx.fill();
  ctx.restore();
}

function renderGenerationFrame(ts = performance.now()) {
  if (!genCtx || !generatingOverlay || generatingOverlay.classList.contains("hidden")) return;
  const w = genCanvas.width;
  const h = genCanvas.height;
  const cx = w / 2;
  const cy = h / 2;
  const hue = 320 - (genProgress * 140);
  const pulse = Math.sin(ts * 0.0024) * 0.5 + 0.5;

  genCtx.clearRect(0, 0, w, h);
  genCtx.fillStyle = "rgba(244,240,255,0.1)";
  genCtx.fillRect(0, 0, w, h);
  genCtx.strokeStyle = "rgba(255,106,213,0.06)";
  genCtx.lineWidth = 1;
  for (let gx = 0; gx < w; gx += 40) {
    genCtx.beginPath();
    genCtx.moveTo(gx, 0);
    genCtx.lineTo(gx, h);
    genCtx.stroke();
  }
  for (let gy = 0; gy < h; gy += 40) {
    genCtx.beginPath();
    genCtx.moveTo(0, gy);
    genCtx.lineTo(w, gy);
    genCtx.stroke();
  }

  const waveRadius = 28 + genProgress * Math.min(w, h) * 0.4;
  for (let i = 0; i < 4; i++) {
    const r = waveRadius - i * 28;
    if (r > 0) {
      genCtx.beginPath();
      genCtx.strokeStyle = `hsla(${hue - i * 12}, 100%, 72%, ${0.18 - i * 0.03})`;
      genCtx.lineWidth = 1.8 - i * 0.2;
      genCtx.arc(cx, cy, r, 0, Math.PI * 2);
      genCtx.stroke();
    }
  }

  const targetCount = Math.min(220, 140 + Math.round(genProgress * 80));
  while (genParticles.length < targetCount) {
    genParticles.push({
      angle: Math.random() * Math.PI * 2,
      radius: 8 + Math.random() * Math.min(w, h) * 0.06,
      speed: 0.4 + Math.random() * 1.5,
      size: 0.8 + Math.random() * 1.2,
      life: 0.45 + Math.random() * 0.55,
      spin: (Math.random() - 0.5) * 0.08,
      twinkle: Math.random() * Math.PI * 2,
      orbit: 0.14 + Math.random() * 0.6,
    });
  }

  genParticles.forEach((p) => {
    p.twinkle += 0.02 + genProgress * 0.02;
    p.angle += p.spin + Math.sin(ts * 0.005 + p.twinkle) * 0.02;
    p.radius += p.speed * (1.1 + genProgress);
    p.life *= 0.9955;
    if (p.radius > Math.max(w, h) * 0.64 || p.life < 0.16) {
      p.angle = Math.random() * Math.PI * 2;
      p.radius = Math.random() * 16;
      p.speed = 0.4 + Math.random() * 1.5;
      p.life = 0.45 + Math.random() * 0.55;
      p.twinkle = Math.random() * Math.PI * 2;
    }

    const wobble = Math.sin(ts * 0.004 + p.twinkle) * 12 * p.orbit;
    const x = cx + Math.cos(p.angle) * (p.radius + wobble);
    const y = cy + Math.sin(p.angle) * (p.radius - wobble * 0.6);
    const size = 4 + p.life * 5 + p.size * 1.6;
    const alpha = Math.min(0.92, 0.2 + p.life);
    const rot = p.angle + ts * 0.0015;

    genCtx.shadowBlur = 15;
    genCtx.shadowColor = `hsla(${hue}, 100%, 65%, 0.9)`;
    drawAnimeStar(genCtx, x, y, size, rot, hue, alpha);
  });
  genCtx.shadowBlur = 0;

  const core = genCtx.createRadialGradient(cx, cy, 0, cx, cy, 110 + genProgress * 90);
  core.addColorStop(0, "rgba(255,255,255,0.86)");
  core.addColorStop(0.15, `hsla(${hue}, 100%, 80%, 0.5)`);
  core.addColorStop(0.55, `hsla(${Math.max(180, hue - 40)}, 100%, 72%, 0.12)`);
  core.addColorStop(1, "rgba(255,255,255,0)");
  genCtx.fillStyle = core;
  genCtx.beginPath();
  genCtx.arc(cx, cy, 88 + pulse * 18 + genProgress * 42, 0, Math.PI * 2);
  genCtx.fill();

  const t = ts * (0.0024 + genProgress * 0.0022);
  const scanA = ((Math.sin(t) * 0.5) + 0.5) * h;
  const scanB = ((Math.sin(t + 1.8) * 0.5) + 0.5) * h;
  [scanA, scanB].forEach((scanY, idx) => {
    const line = genCtx.createLinearGradient(0, scanY, w, scanY);
    line.addColorStop(0, "rgba(255,106,213,0)");
    line.addColorStop(0.5, idx === 0 ? "rgba(255,106,213,0.42)" : "rgba(0,204,255,0.34)");
    line.addColorStop(1, "rgba(0,204,255,0)");
    genCtx.beginPath();
    genCtx.strokeStyle = line;
    genCtx.lineWidth = idx === 0 ? 2.2 : 1.2;
    genCtx.moveTo(0, scanY);
    genCtx.lineTo(w, scanY);
    genCtx.stroke();
  });

  genFrame = requestAnimationFrame(renderGenerationFrame);
}

function startGenerationVisual() {
  if (!generatingOverlay) return;
  generatingOverlay.classList.remove("collapsing");
  generatingOverlay.classList.add("active");
  ensureGenerationCanvas();
  seedGenerationParticles();
  if (genFrame) cancelAnimationFrame(genFrame);
  genFrame = requestAnimationFrame(renderGenerationFrame);
}

function updateGenerationVisual(percent) {
  genProgress = Math.max(0, Math.min(1, Number(percent || 0) / 100));
  if (genPercent) genPercent.textContent = `${Math.round(percent || 0)}%`;
  if (genSteps && stepsInput) {
    const total = Number.parseInt(stepsInput.value || "35", 10) || 35;
    const done = Math.max(0, Math.min(total, Math.round((percent || 0) / 100 * total)));
    genSteps.textContent = `Steps: ${done}/${total}`;
  }
}

function stopGenerationVisual() {
  if (genFrame) cancelAnimationFrame(genFrame);
  genFrame = null;
  if (generatingOverlay) {
    generatingOverlay.classList.add("collapsing");
    setTimeout(() => {
      generatingOverlay.classList.remove("active", "collapsing");
    }, 500);
  }
  if (genCtx && genCanvas) genCtx.clearRect(0, 0, genCanvas.width, genCanvas.height);
}

function pulseValue(el) {
  if (!el) return;
  el.classList.remove("is-pulsing");
  requestAnimationFrame(() => {
    el.classList.add("is-pulsing");
    setTimeout(() => el.classList.remove("is-pulsing"), 420);
  });
}

function formatPhaseLine(data) {
  const code = data.phase || "";
  const tag = PHASE_LABELS[code] || code || "状态";
  const det = (data.phase_detail || "").trim();
  const pct = data.progress != null ? `${data.progress}%` : "";
  if (det) return `${tag} · ${det}${pct ? ` · ${pct}` : ""}`;
  return pct ? `${tag} · ${pct}` : tag;
}

function notifyDone(title, body) {
  try {
    if (typeof Notification !== "undefined" && Notification.permission === "granted") {
      new Notification(title, { body });
    }
  } catch (_) {}
}

function playCompleteCelebration() {
  const el = document.getElementById("result-container") || document.querySelector(".result-container");
  if (!el) return;
  el.classList.remove("celebrate-result");
  requestAnimationFrame(() => {
    void el.offsetWidth;
    el.classList.add("celebrate-result");
    setTimeout(() => el.classList.remove("celebrate-result"), 2100);
  });
}

function setProcessingOverlay(active) {
  if (!loadingOverlay) return;
  loadingOverlay.classList.toggle("hidden", !active);
}

function randomizeSdParams() {
  if (sdStyleSelect && sdStyleSelect.options.length) {
    const opts = Array.from(sdStyleSelect.options);
    const pick = opts[Math.floor(Math.random() * opts.length)];
    sdStyleSelect.value = pick.value;
  }
  if (denoiseInput) {
    const min = Number.parseFloat(denoiseInput.min);
    const max = Number.parseFloat(denoiseInput.max);
    const v = min + Math.random() * (max - min);
    const rounded = Math.round(v * 100) / 100;
    denoiseInput.value = String(Math.min(max, Math.max(min, rounded)));
    syncRangeUI(denoiseInput, denoiseValue, 2);
  }
  if (stepsInput) {
    const lo = 18;
    const hi = 52;
    const steps = lo + Math.floor(Math.random() * (hi - lo + 1));
    stepsInput.value = String(Math.min(60, Math.max(10, steps)));
    syncRangeUI(stepsInput, stepsValue, 0);
  }
  if (guidanceInput) {
    const g = 4.5 + Math.random() * 4;
    const snapped = Math.round(g * 2) / 2;
    const max = Number.parseFloat(guidanceInput.max);
    const min = Number.parseFloat(guidanceInput.min);
    guidanceInput.value = String(Math.min(max, Math.max(min, snapped)));
    syncRangeUI(guidanceInput, guidanceValue, 1);
  }
  if (quickModeInput) quickModeInput.checked = Math.random() < 0.22;

  const posKeys = Object.keys(positivePresets);
  const negKeys = Object.keys(negativePresets);
  if (promptInput && posKeys.length) {
    const k = posKeys[Math.floor(Math.random() * posKeys.length)];
    promptInput.value = positivePresets[k];
  }
  if (negativePromptInput && negKeys.length) {
    const nk = negKeys[Math.floor(Math.random() * negKeys.length)];
    negativePromptInput.value = negativePresets[nk];
  }
}

async function copySdRecipe() {
  const sdStyle = sdStyleSelect ? sdStyleSelect.value : "";
  const sdStyleLabel =
    sdStyleSelect && sdStyleSelect.selectedIndex >= 0
      ? sdStyleSelect.options[sdStyleSelect.selectedIndex].text.trim()
      : "";
  const payload = {
    page: "sd-img2img",
    sdStyle,
    sdStyleLabel,
    denoise: denoiseInput ? Number.parseFloat(denoiseInput.value) : null,
    steps: stepsInput ? Number.parseInt(stepsInput.value, 10) : null,
    guidance: guidanceInput ? Number.parseFloat(guidanceInput.value) : null,
    quick: !!(quickModeInput && quickModeInput.checked),
    prompt: promptInput ? promptInput.value.trim() : "",
    negative: negativePromptInput ? negativePromptInput.value.trim() : "",
  };
  const text = JSON.stringify(payload, null, 2);
  try {
    await navigator.clipboard.writeText(text);
    if (statusText) {
      const prev = statusText.textContent;
      statusText.textContent = "📋 配方已复制到剪贴板";
      setTimeout(() => {
        if (statusText.textContent === "📋 配方已复制到剪贴板") statusText.textContent = prev;
      }, 2200);
    } else {
      alert("已复制到剪贴板");
    }
  } catch (_) {
    window.prompt("请手动复制：", text);
  }
}

async function pasteSdRecipe() {
  let text = "";
  try {
    text = await navigator.clipboard.readText();
  } catch (_) {
    text = window.prompt("请粘贴配方 JSON：") || "";
  }
  const trimmed = text.trim();
  if (!trimmed) return;
  let obj;
  try {
    obj = JSON.parse(trimmed);
  } catch (_) {
    alert("不是有效的 JSON");
    return;
  }
  if (obj.page && obj.page !== "sd-img2img") {
    alert("这是其它页面的配方，请在风格迁移页使用「粘贴配方」");
    return;
  }
  const styleKey = obj.sdStyle || obj.sd_style_name;
  if (styleKey && sdStyleSelect) {
    const found = Array.from(sdStyleSelect.options).some((o) => o.value === styleKey);
    if (!found) {
      alert("当前列表中不存在该 LoRA 组合：" + styleKey);
      return;
    }
  }
  applySdEntry({
    type: "sd",
    sdStyle: styleKey,
    denoise: obj.denoise,
    steps: obj.steps,
    guidance: obj.guidance,
    quick: obj.quick,
    prompt: obj.prompt,
    negative: obj.negative,
  });
  if (statusText) statusText.textContent = "已应用粘贴的配方";
}

function updateQueueBanner() {
  const el = document.getElementById("queue-banner");
  if (!el) return;
  if (queueFiles.length <= 1) {
    el.hidden = true;
    return;
  }
  el.hidden = false;
  el.textContent = `队列：第 ${queueIdx + 1} / ${queueFiles.length} 张`;
}

function scrollSdResultIntoView() {
  const el = document.getElementById("result-container") || document.querySelector(".result-container");
  if (!el) return;
  try {
    const reduced =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "nearest" });
  } catch (_) {
    el.scrollIntoView();
  }
}

function recordSdHistoryJob(jobId) {
  if (typeof HistoryLocal === "undefined") return;
  HistoryLocal.push({
    type: "sd",
    jobId,
    at: Date.now(),
    sdStyle: sdStyleSelect ? sdStyleSelect.value : "default",
    denoise: denoiseInput ? Number.parseFloat(denoiseInput.value) : 0.5,
    steps: stepsInput ? Number.parseInt(stepsInput.value, 10) : 30,
    guidance: guidanceInput ? Number.parseFloat(guidanceInput.value) : 7,
    quick: !!(quickModeInput && quickModeInput.checked),
    prompt: promptInput ? promptInput.value : "",
    negative: negativePromptInput ? negativePromptInput.value : "",
  });
  if (!finishedJobIds.includes(jobId)) finishedJobIds.push(jobId);
}

async function analyzeInputAndSuggest() {
  if (!contentInput || !contentInput.files || contentInput.files.length === 0) {
    showUiNotice("请先上传内容图，再执行分析或渲染。", "error");
    return;
  }
  const fd = new FormData();
  fd.append("content_image", contentInput.files[0]);
  const resp = await fetch("/api/analyze-input", { method: "POST", body: fd });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.error || "分析失败");
  latestAnalyzeSuggestion = data;
  if (analyzeResultText) {
    analyzeResultText.textContent =
      `建议风格：${data.style_suggestion}，权重区间：${(data.weight_range || []).join("~")}，` +
      `推荐参数：steps ${data.recommended.steps} / cfg ${data.recommended.guidance} / denoise ${data.recommended.denoise}`;
  }
}

function applySuggestion() {
  if (!latestAnalyzeSuggestion) return;
  const r = latestAnalyzeSuggestion.recommended || {};
  if (sdStyleSelect) sdStyleSelect.value = latestAnalyzeSuggestion.style_suggestion || sdStyleSelect.value;
  if (stepsInput && r.steps != null) {
    stepsInput.value = String(r.steps);
    syncRangeUI(stepsInput, stepsValue, 0);
  }
  if (guidanceInput && r.guidance != null) {
    guidanceInput.value = String(r.guidance);
    syncRangeUI(guidanceInput, guidanceValue, 1);
  }
  if (denoiseInput && r.denoise != null) {
    denoiseInput.value = String(r.denoise);
    syncRangeUI(denoiseInput, denoiseValue, 2);
  }
  if (statusText) statusText.textContent = "已应用智能分析给出的推荐参数";
}

async function queueAction(action) {
  if (!currentJobId) {
    showUiNotice("当前没有可控制的任务。", "error");
    return;
  }
  const resp = await fetch(`/api/jobs/${currentJobId}/${action}`, { method: "POST" });
  const data = await resp.json();
  if (!resp.ok || data.error) throw new Error(data.error || `操作失败: ${action}`);
}

async function exportBatch(kind) {
  if (!finishedJobIds.length) {
    showUiNotice("暂无已完成任务，无法导出。", "error");
    return;
  }
  const fd = new FormData();
  fd.append("job_ids", finishedJobIds.join(","));
  const url = kind === "compare" ? "/api/export/compare-batch" : "/api/export/nine-grid";
  const resp = await fetch(url, { method: "POST", body: fd });
  const data = await resp.json();
  if (!resp.ok || data.error) throw new Error(data.error || "导出失败");
  alert("导出成功: " + (data.file || (data.files || []).join("\n")));
}

async function exportTransition() {
  if (!currentJobId) {
    showUiNotice("当前没有可导出的视频任务。", "error");
    return;
  }
  const fd = new FormData();
  fd.append("job_id", currentJobId);
  const resp = await fetch("/api/export/transition-video", { method: "POST", body: fd });
  const data = await resp.json();
  if (!resp.ok || data.error) throw new Error(data.error || "导出失败");
  alert("导出成功: " + data.file);
}

async function buildShare(template) {
  if (!currentJobId) {
    showUiNotice("当前没有可生成分享素材的任务。", "error");
    return;
  }
  const fd = new FormData();
  fd.append("job_id", currentJobId);
  fd.append("template", template);
  const resp = await fetch("/api/share/build", { method: "POST", body: fd });
  const data = await resp.json();
  if (!resp.ok || data.error) throw new Error(data.error || "分享生成失败");
  if (shareResultText) {
    shareResultText.textContent = `卡片: ${data.card} | 封面: ${data.cover}`;
  }
  try {
    await navigator.clipboard.writeText(data.copywriting || "");
  } catch (_) {}
}

const defaultPositivePrompt =
  "masterpiece, best quality, anime style, detailed face, clean lineart, soft lighting";
const defaultNegativePrompt =
  "(worst quality, low quality), (zombie, interlocked fingers)";

const positivePresets = {
  portrait:
    "anime portrait, detailed face, clean lineart, natural skin shading, soft light, sharp eyes",
  strong:
    "anime illustration, vibrant colors, dramatic lighting, detailed texture, stylized shading, high contrast",
  scene:
    "anime background, detailed architecture, clean edges, cinematic composition, soft atmospheric light",
};

const negativePresets = {
  portrait: "(worst quality, low quality), (zombie, interlocked fingers)",
  strong: "blurry, noisy, overexposed, underexposed",
  scene: "distorted perspective, noisy texture",
  noHires: "(worst quality:1.6, low quality:1.6), (zombie, sketch, interlocked fingers, comic)",
};

/** 名场面：一键填提示词 + 推荐数值（不改 LoRA） */
const SCENE_PRESETS = {
  oil: {
    title: "油画感",
    prompt:
      "masterpiece, oil painting, thick impasto brushstrokes, canvas texture, warm gallery lighting, artistic, rich colors, museum quality, detailed",
    negative: "photorealistic, plastic skin, flat shading, 3d render, blurry, lowres, jpeg artifacts",
    denoise: 0.52,
    steps: 36,
    guidance: 7.5,
  },
  cyber: {
    title: "赛博霓虹",
    prompt:
      "cyberpunk anime, neon pink and cyan lights, rainy street reflections, futuristic city, detailed, cinematic composition, glowing signs",
    negative: "daylight, natural outdoor, muted colors, blurry, low quality, text watermark",
    denoise: 0.58,
    steps: 38,
    guidance: 8,
  },
  ink: {
    title: "水墨",
    prompt:
      "chinese ink wash painting, sumi-e style, flowing brush strokes, mist and negative space, bamboo or mountains, elegant traditional art, monochrome ink",
    negative: "full color oil, western comic, 3d, photograph, noisy, oversaturated",
    denoise: 0.45,
    steps: 34,
    guidance: 6.5,
  },
  sunset: {
    title: "黄昏动漫",
    prompt:
      "golden hour anime, dramatic sunset sky, rim lighting, emotional atmosphere, detailed clouds, soft film grain, cinematic",
    negative: "harsh flash, overexposed, flat lighting, noon daylight, blurry",
    denoise: 0.5,
    steps: 32,
    guidance: 7,
  },
  noir: {
    title: "黑白映画",
    prompt:
      "anime film noir, high contrast black and white, dramatic shadows, spotlight, grainy film texture, moody storytelling",
    negative: "colorful, saturated, flat gray, low contrast, blurry, lowres",
    denoise: 0.55,
    steps: 35,
    guidance: 7.5,
  },
};

/** 一键套系：重绘 / 步数 / CFG（不改 LoRA 与提示词） */
const SD_PARAM_TRIPLES = {
  light: { denoise: 0.38, steps: 26, guidance: 6 },
  balanced: { denoise: 0.52, steps: 34, guidance: 7 },
  heavy: { denoise: 0.68, steps: 42, guidance: 8 },
};

const STYLE_RECOMMENDATIONS = {
  jojo: { denoise: 0.72, steps: 28, guidance: 7.5 },
};

function applySdParamTriple(key) {
  const p = SD_PARAM_TRIPLES[key];
  if (!p) return;
  if (denoiseInput) {
    const dmin = Number.parseFloat(denoiseInput.min);
    const dmax = Number.parseFloat(denoiseInput.max);
    const dv = Math.min(dmax, Math.max(dmin, p.denoise));
    denoiseInput.value = String(dv);
    syncRangeUI(denoiseInput, denoiseValue, 2);
  }
  if (stepsInput) {
    const smin = Number.parseInt(stepsInput.min, 10);
    const smax = Number.parseInt(stepsInput.max, 10);
    const sv = Math.min(smax, Math.max(smin, p.steps));
    stepsInput.value = String(sv);
    syncRangeUI(stepsInput, stepsValue, 0);
  }
  if (guidanceInput) {
    const gmin = Number.parseFloat(guidanceInput.min);
    const gmax = Number.parseFloat(guidanceInput.max);
    const gv = Math.min(gmax, Math.max(gmin, p.guidance));
    guidanceInput.value = String(gv);
    syncRangeUI(guidanceInput, guidanceValue, 1);
  }
  const tripleLabels = { light: "轻触风格", balanced: "均衡默认", heavy: "重风格" };
  if (statusText) statusText.textContent = "已应用「" + (tripleLabels[key] || key) + "」";
}

function applyStyleRecommendation(styleKey) {
  const rec = STYLE_RECOMMENDATIONS[styleKey];
  if (!rec) return;
  if (denoiseInput) {
    const dmin = Number.parseFloat(denoiseInput.min);
    const dmax = Number.parseFloat(denoiseInput.max);
    const dv = Math.min(dmax, Math.max(dmin, rec.denoise));
    denoiseInput.value = String(dv);
    syncRangeUI(denoiseInput, denoiseValue, 2);
  }
  if (stepsInput) {
    const smin = Number.parseInt(stepsInput.min, 10);
    const smax = Number.parseInt(stepsInput.max, 10);
    const sv = Math.min(smax, Math.max(smin, rec.steps));
    stepsInput.value = String(sv);
    syncRangeUI(stepsInput, stepsValue, 0);
  }
  if (guidanceInput) {
    const gmin = Number.parseFloat(guidanceInput.min);
    const gmax = Number.parseFloat(guidanceInput.max);
    const gv = Math.min(gmax, Math.max(gmin, rec.guidance));
    guidanceInput.value = String(gv);
    syncRangeUI(guidanceInput, guidanceValue, 1);
  }
  if (statusText) {
    statusText.textContent = "已应用 JoJo 推荐参数（权重 0.6~0.8，步数 25~30，重绘 < 0.8）";
  }
}

function appendPromptText(inputEl, chunk) {
  if (!inputEl || !chunk) return;
  const base = (inputEl.value || "").trim();
  inputEl.value = base ? `${base}, ${chunk}` : chunk;
}

function dedupePromptText(text) {
  const raw = String(text || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const seen = new Set();
  const deduped = [];
  let removed = 0;
  for (const token of raw) {
    const key = token.toLowerCase();
    if (seen.has(key)) {
      removed += 1;
      continue;
    }
    seen.add(key);
    deduped.push(token);
  }
  return { text: deduped.join(", "), removed };
}

function initPromptHelpers() {
  if (positivePresetSelect) {
    positivePresetSelect.addEventListener("change", () => {
      const key = positivePresetSelect.value;
      if (!key || !positivePresets[key]) return;
      appendPromptText(promptInput, positivePresets[key]);
      positivePresetSelect.value = "";
    });
  }

  if (negativePresetSelect) {
    negativePresetSelect.addEventListener("change", () => {
      const key = negativePresetSelect.value;
      if (!key || !negativePresets[key]) return;
      appendPromptText(negativePromptInput, negativePresets[key]);
      negativePresetSelect.value = "";
    });
  }

  document.querySelectorAll(".quick-chips button").forEach((btn) => {
    btn.addEventListener("click", () => {
      const word = btn.dataset.word || "";
      const target = btn.dataset.target || "positive";
      if (!word) return;
      if (target === "negative") appendPromptText(negativePromptInput, word);
      else appendPromptText(promptInput, word);
    });
  });

  if (clearPositiveBtn) {
    clearPositiveBtn.addEventListener("click", () => {
      if (promptInput) promptInput.value = "";
    });
  }

  if (clearNegativeBtn) {
    clearNegativeBtn.addEventListener("click", () => {
      if (negativePromptInput) negativePromptInput.value = "";
    });
  }

  if (resetPromptsBtn) {
    resetPromptsBtn.addEventListener("click", () => {
      if (promptInput) promptInput.value = defaultPositivePrompt;
      if (negativePromptInput) negativePromptInput.value = defaultNegativePrompt;
    });
  }
}

function syncRangeUI(rangeEl, valueEl, digits = 2) {
  if (!rangeEl || !valueEl) return;
  const v = Number.parseFloat(rangeEl.value);
  valueEl.textContent = Number.isInteger(v) ? String(v) : v.toFixed(digits);
  pulseValue(valueEl);
}

function applyScenePreset(sceneKey) {
  const p = SCENE_PRESETS[sceneKey];
  if (!p) return;
  if (promptInput) promptInput.value = p.prompt;
  if (negativePromptInput) negativePromptInput.value = p.negative;
  if (denoiseInput) {
    const dmin = Number.parseFloat(denoiseInput.min);
    const dmax = Number.parseFloat(denoiseInput.max);
    const dv = Math.min(dmax, Math.max(dmin, p.denoise));
    denoiseInput.value = String(dv);
    syncRangeUI(denoiseInput, denoiseValue, 2);
  }
  if (stepsInput) {
    const smin = Number.parseInt(stepsInput.min, 10);
    const smax = Number.parseInt(stepsInput.max, 10);
    const sv = Math.min(smax, Math.max(smin, p.steps));
    stepsInput.value = String(sv);
    syncRangeUI(stepsInput, stepsValue, 0);
  }
  if (guidanceInput) {
    const gmin = Number.parseFloat(guidanceInput.min);
    const gmax = Number.parseFloat(guidanceInput.max);
    const gv = Math.min(gmax, Math.max(gmin, p.guidance));
    guidanceInput.value = String(gv);
    syncRangeUI(guidanceInput, guidanceValue, 1);
  }
  if (statusText) statusText.textContent = `已套用「${p.title}」名场面预设`;
}

syncRangeUI(denoiseInput, denoiseValue, 2);
syncRangeUI(stepsInput, stepsValue, 0);
syncRangeUI(guidanceInput, guidanceValue, 1);
initPromptHelpers();

if (denoiseInput)
  denoiseInput.addEventListener("input", () => syncRangeUI(denoiseInput, denoiseValue, 2));
if (stepsInput) stepsInput.addEventListener("input", () => syncRangeUI(stepsInput, stepsValue, 0));
if (guidanceInput)
  guidanceInput.addEventListener("input", () => syncRangeUI(guidanceInput, guidanceValue, 1));

function setPreviewMulti(input, container) {
  container.innerHTML = "";
  const files = input.files ? Array.from(input.files) : [];
  if (!files.length) {
    container.textContent = "暂无预览";
    return;
  }
  const first = files[0];
  const img = document.createElement("img");
  img.src = URL.createObjectURL(first);
  container.appendChild(img);
  if (files.length > 1) {
    const count = document.createElement("div");
    count.textContent = `共 ${files.length} 张`;
    container.appendChild(count);
  }
}

if (contentInput) {
  contentInput.addEventListener("change", () => setPreviewMulti(contentInput, contentPreview));
}

function clearGallery() {
  if (resultGallery) resultGallery.innerHTML = "";
}

// ============ 二维码弹窗（扫码下载）===========
let qrModalSeq = 0;
let qrModalLastObjUrl = null;

function toAbsUrl(maybeRelativeUrl) {
  try {
    return new URL(maybeRelativeUrl, window.location.origin).href;
  } catch (_) {
    return String(maybeRelativeUrl || "");
  }
}

async function fetchQrObjectUrl(text) {
  try {
    // 复用项目里已有的外部 QR 生成服务（参数卡也用它）。
    const u = `https://api.qrserver.com/v1/create-qr-code/?size=240x240&margin=1&data=${encodeURIComponent(
      String(text || "")
    )}`;
    const r = await fetch(u, { cache: "no-store" });
    if (!r.ok) return null;
    const blob = await r.blob();
    return URL.createObjectURL(blob);
  } catch (_) {
    return null;
  }
}

function ensureQrModalEl() {
  let overlay = document.getElementById("qr-download-modal-overlay");
  if (overlay) return overlay;

  overlay = document.createElement("div");
  overlay.id = "qr-download-modal-overlay";
  overlay.style.position = "fixed";
  overlay.style.inset = "0";
  overlay.style.background = "rgba(2, 6, 23, 0.62)";
  overlay.style.backdropFilter = "blur(12px) saturate(1.1)";
  overlay.style.zIndex = "9999";
  overlay.style.display = "none";
  overlay.style.alignItems = "center";
  overlay.style.justifyContent = "center";

  const modal = document.createElement("div");
  modal.style.width = "min(92vw, 520px)";
  modal.style.background = "linear-gradient(180deg, #0f172a 0%, #0b1220 100%)";
  modal.style.color = "#e2e8f0";
  modal.style.borderRadius = "18px";
  modal.style.border = "1px solid rgba(99, 102, 241, 0.25)";
  modal.style.boxShadow = "0 18px 80px rgba(0,0,0,0.52), 0 0 0 1px rgba(99, 102, 241, 0.10) inset";
  modal.style.padding = "20px 18px 16px";

  const header = document.createElement("div");
  header.style.display = "flex";
  header.style.alignItems = "center";
  header.style.justifyContent = "space-between";
  header.style.gap = "10px";

  const title = document.createElement("div");
  title.className = "qr-modal-title";
  title.style.fontSize = "17px";
  title.style.fontWeight = "800";
  title.style.letterSpacing = "0.2px";

  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.textContent = "关闭";
  closeBtn.className = "secondary-btn";
  closeBtn.style.flex = "0 0 auto";
  closeBtn.addEventListener("click", () => hideQrModal());

  header.appendChild(title);
  header.appendChild(closeBtn);

  const status = document.createElement("div");
  status.className = "qr-modal-status";
  status.style.marginTop = "12px";
  status.style.opacity = "0.95";
  status.style.fontSize = "13px";

  const img = document.createElement("img");
  img.id = "qr-modal-img";
  img.alt = "二维码";
  img.style.display = "block";
  img.style.margin = "14px auto 10px";
  img.style.width = "252px";
  img.style.height = "252px";
  img.style.objectFit = "contain";
  img.style.borderRadius = "14px";
  img.style.border = "1px solid rgba(226, 232, 240, 0.18)";
  img.style.boxShadow = "0 0 0 6px rgba(99, 102, 241, 0.10), 0 12px 40px rgba(0,0,0,0.20)";

  const linkWrap = document.createElement("div");
  linkWrap.style.fontSize = "13px";
  linkWrap.style.opacity = "0.92";
  linkWrap.style.wordBreak = "break-word";

  const link = document.createElement("a");
  link.className = "qr-modal-link";
  link.href = "#";
  link.target = "_blank";
  link.rel = "noreferrer";
  linkWrap.textContent = "下载链接：";
  linkWrap.appendChild(link);

  const hint = document.createElement("div");
  hint.style.marginTop = "10px";
  hint.style.opacity = "0.86";
  hint.style.fontSize = "12.8px";
  hint.style.lineHeight = "1.45";
  hint.textContent = "说明：二维码指向“下载接口”。手机扫码后会直接触发下载（可能需要浏览器权限）。";

  const actions = document.createElement("div");
  actions.style.display = "flex";
  actions.style.gap = "10px";
  actions.style.marginTop = "14px";
  actions.style.flexWrap = "wrap";
  actions.style.justifyContent = "flex-start";

  const copyBtn = document.createElement("button");
  copyBtn.type = "button";
  copyBtn.className = "secondary-btn";
  copyBtn.textContent = "复制下载链接";
  copyBtn.addEventListener("click", async () => {
    const href = link.href;
    if (!href || href === "#") return;
    try {
      await navigator.clipboard.writeText(href);
      copyBtn.textContent = "已复制";
      setTimeout(() => (copyBtn.textContent = "复制下载链接"), 1600);
    } catch (_) {
      window.prompt("请手动复制链接：", href);
    }
  });

  actions.appendChild(copyBtn);

  modal.appendChild(header);
  modal.appendChild(status);
  modal.appendChild(img);
  modal.appendChild(linkWrap);
  modal.appendChild(hint);
  modal.appendChild(actions);
  overlay.appendChild(modal);

  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) hideQrModal();
  });

  document.body.appendChild(overlay);
  return overlay;
}

function hideQrModal() {
  const overlay = document.getElementById("qr-download-modal-overlay");
  if (!overlay) return;
  overlay.style.display = "none";
  const img = document.getElementById("qr-modal-img");
  if (img) img.src = "";
  if (qrModalLastObjUrl) URL.revokeObjectURL(qrModalLastObjUrl);
  qrModalLastObjUrl = null;
}

async function showQrModalForDownload(titleText, downloadHref) {
  const overlay = ensureQrModalEl();
  if (!overlay) return;

  // 每次展示递增序号，避免“快速连点”导致旧请求覆盖新二维码。
  const seq = ++qrModalSeq;

  const title = overlay.querySelector(".qr-modal-title");
  const status = overlay.querySelector(".qr-modal-status");
  const link = overlay.querySelector(".qr-modal-link");
  const img = overlay.querySelector("#qr-modal-img");

  const absDownloadUrl = toAbsUrl(downloadHref);

  if (title) title.textContent = String(titleText || "二维码");
  if (status) status.textContent = "正在生成二维码…";
  if (link) link.href = absDownloadUrl;
  if (link) link.textContent = absDownloadUrl;
  if (img) img.src = "";

  overlay.style.display = "flex";

  const objUrl = await fetchQrObjectUrl(absDownloadUrl);
  if (seq !== qrModalSeq) return;

  if (qrModalLastObjUrl) URL.revokeObjectURL(qrModalLastObjUrl);
  qrModalLastObjUrl = objUrl;

  if (objUrl && img) {
    img.src = objUrl;
    if (status) status.textContent = "二维码已就绪，请使用手机扫码下载";
  } else {
    if (status) status.textContent = "二维码生成失败（可能是网络不可用）。请手动打开下载链接。";
  }
}

function downloadUrlForJob(jobId, index = 0, label = PAGE_DOWNLOAD_LABEL) {
  const p = new URLSearchParams({
    t: String(Date.now()),
    download: "1",
    label: String(label || PAGE_DOWNLOAD_LABEL),
  });
  if (index) p.set("index", String(index));
  return `/api/result/${jobId}?${p.toString()}`;
}

function appendResultWithDownload(jobId, imageIndex, altText) {
  if (!resultGallery) return;
  const wrap = document.createElement("div");
  wrap.className = "result-item";
  const resultSrc = `/api/result/${jobId}?t=${Date.now()}&index=${imageIndex}`;
  const img = document.createElement("img");
  img.src = resultSrc;
  img.alt = altText;
  img.loading = imageIndex > 0 ? "lazy" : "eager";
  img.style.display = "block";
  img.style.maxHeight = "calc(84vh - 40px)";
  img.style.maxWidth = "min(98%, 1040px)";
  img.style.boxShadow = "0 24px 70px rgba(0,0,0,0.38)";
  img.classList.add("fade-in", "active");
  wrap.appendChild(img);
  const actions = document.createElement("div");
  actions.className = "result-actions";
  const dlResult = document.createElement("a");
  dlResult.href = downloadUrlForJob(jobId, imageIndex, PAGE_DOWNLOAD_LABEL);
  dlResult.className = "secondary-btn download-link";
  dlResult.title = "仅包含 SD 转换后的结果图";
  dlResult.textContent =
    imageIndex > 0 ? `仅下载第 ${imageIndex + 1} 张结果` : "仅下载结果图";
  actions.appendChild(dlResult);

  const qrResultBtn = document.createElement("button");
  qrResultBtn.type = "button";
  qrResultBtn.className = "secondary-btn";
  qrResultBtn.textContent = "结果二维码";
  qrResultBtn.title = "生成结果图下载二维码（手机扫码即可下载）";
  const resultDownloadHref = dlResult.href;
  qrResultBtn.addEventListener("click", async () => {
    await showQrModalForDownload("结果图二维码", resultDownloadHref);
  });
  actions.appendChild(qrResultBtn);

  const copyLinkBtn = document.createElement("button");
  copyLinkBtn.type = "button";
  copyLinkBtn.className = "secondary-btn";
  copyLinkBtn.textContent = "复制图片链接";
  copyLinkBtn.title = "复制该结果图的完整 URL";
  copyLinkBtn.addEventListener("click", async () => {
    const abs = new URL(resultSrc, window.location.origin).href;
    try {
      await navigator.clipboard.writeText(abs);
      copyLinkBtn.textContent = "已复制";
      setTimeout(() => {
        copyLinkBtn.textContent = "复制图片链接";
      }, 1600);
    } catch (_) {
      window.prompt("请手动复制链接：", abs);
    }
  });
  actions.appendChild(copyLinkBtn);

  const shareCardBtn = document.createElement("button");
  shareCardBtn.type = "button";
  shareCardBtn.className = "secondary-btn secondary-btn-primary";
  shareCardBtn.textContent = "分享卡片";
  shareCardBtn.title = "导出带参数条、水印与二维码的 PNG（生成二维码需短暂联网）";
  shareCardBtn.addEventListener("click", async () => {
    if (typeof buildSdShareCard !== "function") {
      alert("分享模块未加载");
      return;
    }
    shareCardBtn.disabled = true;
    try {
      const styleLabel =
        sdStyleSelect && sdStyleSelect.selectedIndex >= 0
          ? sdStyleSelect.options[sdStyleSelect.selectedIndex].text.trim()
          : "";
      const lines = [
        styleLabel || "SD img2img",
        `重绘 ${denoiseInput ? denoiseInput.value : "?"} · ${stepsInput ? stepsInput.value : "?"}步 · CFG ${guidanceInput ? guidanceInput.value : "?"}`,
      ];
      const snap = (promptInput && promptInput.value.trim().slice(0, 140)) || "";
      await buildSdShareCard(jobId, lines, snap);
    } catch (e) {
      console.error(e);
      alert("生成分享卡片失败：" + (e && e.message ? e.message : "未知错误"));
    } finally {
      shareCardBtn.disabled = false;
    }
  });
  actions.appendChild(shareCardBtn);

  if (imageIndex === 0) {
    const dlCompare = document.createElement("a");
    const cmpUrl =
      typeof downloadCompareUrlForJob === "function"
        ? downloadCompareUrlForJob(jobId, PAGE_DOWNLOAD_LABEL)
        : `/api/compare-download/${encodeURIComponent(String(jobId))}?${new URLSearchParams({
            t: String(Date.now()),
            download: "1",
            label: String(PAGE_DOWNLOAD_LABEL || "compare"),
          }).toString()}`;
    dlCompare.href = cmpUrl;
    dlCompare.className = "secondary-btn secondary-btn-primary download-link";
    dlCompare.title = "原图与结果左右并排一张图";
    dlCompare.textContent = "下载对比图";
    actions.appendChild(dlCompare);

    const qrCompareBtn = document.createElement("button");
    qrCompareBtn.type = "button";
    qrCompareBtn.className = "secondary-btn";
    qrCompareBtn.textContent = "对比二维码";
    qrCompareBtn.title = "生成对比图下载二维码（手机扫码即可下载）";
    const compareDownloadHref = dlCompare.href;
    qrCompareBtn.addEventListener("click", async () => {
      await showQrModalForDownload("对比图二维码", compareDownloadHref);
    });
    actions.appendChild(qrCompareBtn);
  }

  wrap.appendChild(actions);
  resultGallery.appendChild(wrap);
}

function showSingleResult(jobId) {
  if (!resultGallery) return;
  clearGallery();
  setProcessingOverlay(false);
  setProgressHud(false);
  stopGenerationVisual();
  const placeholder = document.getElementById("result-placeholder");
  if (placeholder) placeholder.style.display = "none";
  appendResultWithDownload(jobId, 0, "转换结果");
  scrollSdResultIntoView();
}

function showBatchResults(jobId, count) {
  if (!resultGallery) return;
  clearGallery();
  setProcessingOverlay(false);
  setProgressHud(false);
  stopGenerationVisual();
  const placeholder = document.getElementById("result-placeholder");
  if (placeholder) placeholder.style.display = "none";
  const n = Math.max(0, Number(count || 0));
  for (let i = 0; i < n; i++) {
    appendResultWithDownload(jobId, i, `转换结果 ${i + 1}`);
  }
  scrollSdResultIntoView();
}

function setCancelEnabled(enabled) {
  if (!cancelBtn) return;
  cancelBtn.disabled = !enabled;
}

async function submitQueueSdJob() {
  const file = queueFiles[queueIdx];
  if (!file) return;

  const posResult = dedupePromptText(promptInput ? promptInput.value : "");
  const negResult = dedupePromptText(negativePromptInput ? negativePromptInput.value : "");
  if (promptInput) promptInput.value = posResult.text;
  if (negativePromptInput) negativePromptInput.value = negResult.text;

  const downCb = document.getElementById("upload-downscale-checkbox");
  const useDown = !!(downCb && downCb.checked && window.ClientHelpers);
  const maxEdge = 2048;
  let contentFile = file;
  if (useDown) {
    if (statusText) {
      statusText.textContent =
        queueFiles.length > 1 ? `压缩第 ${queueIdx + 1}/${queueFiles.length} 张…` : "正在压缩大图…";
    }
    contentFile = await ClientHelpers.downscaleImageFile(file, maxEdge);
  }

  const formData = new FormData();
  formData.append("content_image", contentFile);
  formData.append("sd_style_name", sdStyleSelect ? sdStyleSelect.value : "default");
  formData.append("denoising_strength", denoiseInput ? denoiseInput.value : "0.65");
  formData.append("guidance_scale", guidanceInput ? guidanceInput.value : "5.5");
  formData.append("num_inference_steps", stepsInput ? stepsInput.value : "30");
  formData.append("prompt", posResult.text);
  formData.append("negative_prompt", negResult.text);
  formData.append("quick_mode", quickModeInput && quickModeInput.checked ? "1" : "0");

  const resp = await fetch("/api/sd-style-transfer", { method: "POST", body: formData });
  const data = await resp.json();
  if (!resp.ok || data.error) throw new Error(data.error || "任务创建失败");

  currentJobId = data.job_id;
  statusText.textContent =
    queueFiles.length > 1
      ? `已提交队列 ${queueIdx + 1}/${queueFiles.length}，等待处理…`
      : "任务已创建，开始处理…";
  pollStatus();
}

async function startSdStyleTransfer() {
  if (!contentInput || !contentInput.files || contentInput.files.length === 0) {
    showUiNotice("请先上传内容图，再点击开始执行渲染。", "error");
    return;
  }

  const posResult = dedupePromptText(promptInput ? promptInput.value : "");
  const negResult = dedupePromptText(negativePromptInput ? negativePromptInput.value : "");
  if (promptInput) promptInput.value = posResult.text;
  if (negativePromptInput) negativePromptInput.value = negResult.text;
  const removedTotal = posResult.removed + negResult.removed;

  queueFiles = Array.from(contentInput.files);
  queueIdx = 0;
  updateQueueBanner();
  showUiNotice(`准备提交 ${queueFiles.length} 个任务…`);

  if (typeof Notification !== "undefined" && Notification.permission === "default") {
    Notification.requestPermission();
  }

  setRunButtonsDisabled(true);
  setCancelEnabled(false);
  setProgressHud(true, "正在提交任务…", 0);
  startGenerationVisual();
  updateGenerationVisual(0);
  statusText.textContent = removedTotal > 0
    ? `检测到 ${removedTotal} 个重复提示词，已自动去重，正在提交…`
    : "正在提交 SD 任务到服务器...";
  progressBar.style.width = "0%";
  clearGallery();
  setProcessingOverlay(true);
  const phRun = document.getElementById("result-placeholder");
  if (phRun) {
    phRun.style.display = "";
    phRun.textContent = "处理完成后，结果将显示在此处";
  }

  try {
    await submitQueueSdJob();
  } catch (e) {
    console.error(e);
    showUiNotice("提交失败：" + e.message, "error");
    queueFiles = [];
    queueIdx = 0;
    updateQueueBanner();
    setProcessingOverlay(false);
  } finally {
    setRunButtonsDisabled(false);
  }
}

async function cancelCurrentJob() {
  if (!currentJobId) return;
  setCancelEnabled(false);
  showUiNotice("取消请求已发送…");
  setProcessingOverlay(true);
  try {
    const resp = await fetch(`/api/cancel/${currentJobId}`, { method: "POST" });
    const data = await resp.json();
    if (!resp.ok || data.error) throw new Error(data.error || "取消失败");
  } catch (e) {
    console.error(e);
    showUiNotice("取消失败：" + (e && e.message ? e.message : "未知错误"), "error");
  }
}

async function pollStatus() {
  if (!currentJobId) return;
  if (pollingTimer) clearTimeout(pollingTimer);

  try {
    const resp = await fetch(`/api/status/${currentJobId}`);
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || "状态查询失败");

    progressBar.style.width = `${data.progress || 0}%`;

    const status = data.status;
    const kind = data.kind;
    const count = data.result_count || 0;

    if (status === "queued") {
      showUiNotice(formatPhaseLine(data));
      setProgressHud(true, "任务排队中，等待显卡空闲…", data.progress || 2);
      updateGenerationVisual(data.progress || 2);
      setCancelEnabled(true);
      setProcessingOverlay(true);
      pollingTimer = setTimeout(pollStatus, nextPollMs());
      return;
    }

    if (status === "pending") {
      showUiNotice(formatPhaseLine(data));
      setProgressHud(true, "正在准备模型和资源…", data.progress || 8);
      updateGenerationVisual(data.progress || 8);
      setCancelEnabled(false);
      setProcessingOverlay(true);
      pollingTimer = setTimeout(pollStatus, nextPollMs());
      return;
    }

    if (status === "running") {
      showUiNotice(formatPhaseLine(data));
      setProgressHud(true, "正在渲染图像，请稍候…", data.progress || 40);
      updateGenerationVisual(data.progress || 40);
      setCancelEnabled(true);
      setProcessingOverlay(true);
      pollingTimer = setTimeout(pollStatus, nextPollMs());
      return;
    }

    if (status === "finished") {
      showUiNotice(formatPhaseLine({ ...data, phase: "done", phase_detail: "处理完成" }), "success");
      setProgressHud(true, "渲染完成，正在整理结果…", 100);
      updateGenerationVisual(100);
      setCancelEnabled(false);
      setProcessingOverlay(false);
      const multi = queueFiles.length > 1;
      recordSdHistoryJob(currentJobId);
      if (queueFiles.length > 1 && queueIdx < queueFiles.length - 1) {
        queueIdx++;
        updateQueueBanner();
        void submitQueueSdJob().catch((e) => {
          console.error(e);
          showUiNotice("队列下一项提交失败：" + e.message, "error");
          queueFiles = [];
          queueIdx = 0;
          updateQueueBanner();
        });
        return;
      }
      if (multi) notifyDone("SD 转换", "队列已全部完成");
      queueFiles = [];
      queueIdx = 0;
      updateQueueBanner();
      playCompleteCelebration();
      if (kind === "batch" && count > 1) showBatchResults(currentJobId, count);
      else showSingleResult(currentJobId);
      return;
    }

    if (status === "cancelled") {
      showUiNotice("任务已取消（已生成的结果保留）", "error");
      setProgressHud(false);
      stopGenerationVisual();
      setCancelEnabled(false);
      setProcessingOverlay(false);
      queueFiles = [];
      queueIdx = 0;
      updateQueueBanner();
      if (kind === "batch" && count > 1) showBatchResults(currentJobId, count);
      else if (data.has_result) showSingleResult(currentJobId);
      return;
    }

    if (status === "error") {
      showUiNotice("任务失败：" + (data.error || "未知错误"), "error");
      setProgressHud(true, "渲染失败，请调整参数后重试。", data.progress || 0);
      stopGenerationVisual();
      setCancelEnabled(false);
      setProcessingOverlay(false);
      queueFiles = [];
      queueIdx = 0;
      updateQueueBanner();
      return;
    }

    pollingTimer = setTimeout(pollStatus, nextPollMs());
  } catch (e) {
    console.error(e);
    showUiNotice("查询状态失败", "error");
    setProgressHud(true, "状态查询失败，请稍后重试。", 0);
    stopGenerationVisual();
    setCancelEnabled(false);
    setProcessingOverlay(false);
  }
}

async function rerunJob(oldJobId) {
  showUiNotice("正在重跑任务…");
  progressBar.style.width = "0%";
  clearGallery();
  setProcessingOverlay(true);
  try {
    const resp = await fetch(`/api/rerun/${oldJobId}`, { method: "POST" });
    const data = await resp.json();
    if (!resp.ok || data.error) throw new Error(data.error || "重跑失败");
    currentJobId = data.job_id;
    setCancelEnabled(false);
    pollStatus();
  } catch (e) {
    console.error(e);
    showUiNotice("重跑失败：" + e.message, "error");
    setProcessingOverlay(false);
  }
}

function applySdEntry(entry) {
  if (!entry || entry.type !== "sd") return;
  if (sdStyleSelect && entry.sdStyle) sdStyleSelect.value = entry.sdStyle;
  if (denoiseInput && entry.denoise != null) {
    denoiseInput.value = String(entry.denoise);
    syncRangeUI(denoiseInput, denoiseValue, 2);
  }
  if (stepsInput && entry.steps != null) {
    stepsInput.value = String(entry.steps);
    syncRangeUI(stepsInput, stepsValue, 0);
  }
  if (guidanceInput && entry.guidance != null) {
    guidanceInput.value = String(entry.guidance);
    syncRangeUI(guidanceInput, guidanceValue, 1);
  }
  if (quickModeInput) quickModeInput.checked = !!entry.quick;
  if (promptInput && entry.prompt != null) promptInput.value = entry.prompt;
  if (negativePromptInput && entry.negative != null) negativePromptInput.value = entry.negative;
}

function consumeHistoryApplySd() {
  try {
    const raw = sessionStorage.getItem("historyApply");
    if (!raw) return;
    sessionStorage.removeItem("historyApply");
    const entry = JSON.parse(raw);
    if (entry.type === "sd") applySdEntry(entry);
  } catch (e) {
    console.error(e);
  }
}

function consumeHistoryPreviewSd() {
  try {
    const raw = sessionStorage.getItem("historyPreview");
    if (!raw) return;
    sessionStorage.removeItem("historyPreview");
    const { jobId, type } = JSON.parse(raw);
    if (type !== "sd") return;
    currentJobId = null;
    setCancelEnabled(false);
    showSingleResult(jobId);
  } catch (e) {
    console.error(e);
  }
}

if (runBtn) runBtn.addEventListener("click", startSdStyleTransfer);
if (cancelBtn) cancelBtn.addEventListener("click", cancelCurrentJob);
if (analyzeInputBtn) analyzeInputBtn.addEventListener("click", () => void analyzeInputAndSuggest().catch((e) => alert(e.message)));
if (applySuggestionBtn) applySuggestionBtn.addEventListener("click", applySuggestion);
if (pauseJobBtn) pauseJobBtn.addEventListener("click", () => void queueAction("pause").catch((e) => alert(e.message)));
if (resumeJobBtn) resumeJobBtn.addEventListener("click", () => void queueAction("resume").catch((e) => alert(e.message)));
if (cancelJobBtn) cancelJobBtn.addEventListener("click", () => void queueAction("cancel").catch((e) => alert(e.message)));
if (exportCompareBatchBtn) exportCompareBatchBtn.addEventListener("click", () => void exportBatch("compare").catch((e) => alert(e.message)));
if (exportNineGridBtn) exportNineGridBtn.addEventListener("click", () => void exportBatch("grid").catch((e) => alert(e.message)));
if (exportTransitionBtn) exportTransitionBtn.addEventListener("click", () => void exportTransition().catch((e) => alert(e.message)));
if (buildShareCardBtn) buildShareCardBtn.addEventListener("click", () => void buildShare("xiaohongshu").catch((e) => alert(e.message)));
if (buildXhsCoverBtn) buildXhsCoverBtn.addEventListener("click", () => void buildShare("xiaohongshu").catch((e) => alert(e.message)));
if (buildDyCoverBtn) buildDyCoverBtn.addEventListener("click", () => void buildShare("douyin").catch((e) => alert(e.message)));
if (sdStyleSelect) {
  sdStyleSelect.addEventListener("change", () => applyStyleRecommendation(sdStyleSelect.value));
}

const sdRandomParamsBtn = document.getElementById("sd-random-params-btn");
const sdCopyRecipeBtn = document.getElementById("sd-copy-recipe-btn");
const sdPasteRecipeBtn = document.getElementById("sd-paste-recipe-btn");
if (sdRandomParamsBtn) sdRandomParamsBtn.addEventListener("click", randomizeSdParams);
if (sdCopyRecipeBtn) sdCopyRecipeBtn.addEventListener("click", () => void copySdRecipe());
if (sdPasteRecipeBtn) sdPasteRecipeBtn.addEventListener("click", () => void pasteSdRecipe());

(function initUploadDownscalePref() {
  const cb = document.getElementById("upload-downscale-checkbox");
  if (!cb) return;
  try {
    cb.checked = localStorage.getItem("upload_downscale_pref") === "1";
  } catch (_) {}
  cb.addEventListener("change", () => {
    try {
      localStorage.setItem("upload_downscale_pref", cb.checked ? "1" : "0");
    } catch (_) {}
  });
})();

document.addEventListener("visibilitychange", () => {
  if (document.hidden || !currentJobId) return;
  if (pollingTimer) clearTimeout(pollingTimer);
  pollingTimer = null;
  void pollStatus();
});

document.addEventListener("keydown", (e) => {
  if (!(e.ctrlKey || e.metaKey) || e.key !== "Enter") return;
  if (!runBtn || runBtn.disabled) return;
  e.preventDefault();
  runBtn.click();
});

document.querySelectorAll(".sd-triple-preset").forEach((btn) => {
  btn.addEventListener("click", () => {
    const key = btn.dataset.preset;
    if (!key) return;
    applySdParamTriple(key);
  });
});

document.querySelectorAll(".scene-preset-card").forEach((btn) => {
  btn.addEventListener("click", () => applyScenePreset(btn.dataset.scene || ""));
});

consumeHistoryApplySd();
consumeHistoryPreviewSd();
if (sdStyleSelect) applyStyleRecommendation(sdStyleSelect.value);

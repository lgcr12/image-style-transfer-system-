const contentInput = document.getElementById("content-input");
const styleInput = document.getElementById("style-input");
const contentPreview = document.getElementById("content-preview");
const stylePreview = document.getElementById("style-preview");
const runBtn = document.getElementById("run-btn");

function setRunButtonsDisabled(disabled) {
  if (runBtn) runBtn.disabled = disabled;
}
const cancelBtn = document.getElementById("cancel-btn");
const modelSelect = document.getElementById("model-select");
const statusText = document.getElementById("status-text");
const progressBar = document.getElementById("progress-bar");
const resultGallery = document.getElementById("result-gallery");
const canvasArea = document.getElementById("canvas-area");
const resultContainer = document.getElementById("result-container");
const loadingOverlay = document.getElementById("loading-overlay");
const resultImage = document.getElementById("result-image");
const processingCanvas = document.getElementById("triger-warp-canvas");
const processingDetail = document.getElementById("processing-detail");
const processingSteps = document.getElementById("processing-steps");
const processingModel = document.getElementById("processing-model");
const processingPercent = document.getElementById("processing-percent");
const strengthInput = document.getElementById("strength-input");
const strengthValue = document.getElementById("strength-value");
const modelPicker = document.getElementById("model-picker");
const processingCtx = processingCanvas ? processingCanvas.getContext("2d") : null;

/** 婵炴垶鎸搁鍫澝归崶顒€妫橀柛銉檮椤愪粙鏌涘顒傂㈠褏濮风槐鎾诲焵椤掑嫭鏅柛顐ｇ矌閻?/api/result 闂?label 闁诲海鏁搁幊鎾惰姳閺屻儲鏅?*/
const PAGE_DOWNLOAD_LABEL = "style-transfer";

let currentJobId = null;
let pollingTimer = null;
let processingResizeBound = false;

/** 婵犮垼鍩栭懝鎯瑰鈧濂告偄瀹勬壆浠氶梺鎸庣☉閻楀懐鍒掓惔銈冧汗闁规儳鍟块·鍛渻閵堝娑ч柛鐐差嚟閳ь剚绋掗敃顐ゆ?*/
let queueFiles = [];
let queueIdx = 0;

const PROCESSING_COPY = [
  { until: 12, text: "Singularity lit. Compressing noise field." },
  { until: 38, text: "Liquid flow is converging. Structure is appearing." },
  { until: 68, text: "Ripples pass through the canvas. Details are forming." },
  { until: 92, text: "Neural texture is converging. Final frame is stabilizing." },
  { until: 101, text: "Final light sweep. Locking the generated result." },
];

const processingState = {
  active: false,
  progress: 0,
  frameId: 0,
  startTime: 0,
  lastTs: 0,
  ripples: [],
  particles: [],
  previewImage: null,
  previewSrc: "",
  revealBoost: 0,
  flashUntil: 0,
  lastRippleProgress: 0,
};

const PHASE_LABELS = {
  pending: "Queued",
  downloading: "Downloading model",
  loading_model: "Loading model",
  running: "Running",
  done: "Done",
  error: "Error",
};

function nextPollMs() {
  return typeof ClientHelpers !== "undefined" && ClientHelpers.pollDelayMs ? ClientHelpers.pollDelayMs() : 700;
}

function formatPhaseLine(data) {
  const code = data.phase || "";
  const tag = PHASE_LABELS[code] || code || "Status";
  const det = (data.phase_detail || "").trim();
  const pct = data.progress != null ? `${data.progress}%` : "";
  if (det) return `${tag} | ${det}${pct ? ` | ${pct}` : ""}`;
  return pct ? `${tag} | ${pct}` : tag;
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

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function resizeProcessingCanvas() {
  if (!processingCanvas || !resultContainer) return;
  const rect = resultContainer.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  processingCanvas.width = Math.round(rect.width * dpr);
  processingCanvas.height = Math.round(rect.height * dpr);
  processingCanvas.style.width = `${rect.width}px`;
  processingCanvas.style.height = `${rect.height}px`;
  if (processingCtx) processingCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function ensureProcessingResizeBinding() {
  if (processingResizeBound) return;
  processingResizeBound = true;
  window.addEventListener("resize", () => {
    if (!processingState.active) return;
    resizeProcessingCanvas();
    resetProcessingParticles();
  });
}

function getProcessingPreviewSrc() {
  if (contentInput && contentInput.files && contentInput.files[0]) {
    if (processingState.previewSrc && processingState.previewSrc.startsWith("blob:")) {
      URL.revokeObjectURL(processingState.previewSrc);
    }
    processingState.previewSrc = URL.createObjectURL(contentInput.files[0]);
    return processingState.previewSrc;
  }
  if (resultImage && resultImage.src) return resultImage.src;
  return "";
}

function primeProcessingPreview() {
  const src = getProcessingPreviewSrc();
  if (!src) {
    processingState.previewImage = null;
    return;
  }
  const img = new Image();
  img.src = src;
  processingState.previewImage = img;
}

function resetProcessingParticles() {
  if (!processingCanvas || !resultContainer) return;
  const rect = resultContainer.getBoundingClientRect();
  const width = rect.width || processingCanvas.clientWidth || 0;
  const height = rect.height || processingCanvas.clientHeight || 0;
  const count = Math.max(32, Math.round((width * height) / 26000));
  processingState.particles = Array.from({ length: count }, () => ({
    x: Math.random() * width,
    y: Math.random() * height,
    size: 18 + Math.random() * 34,
    speed: 0.35 + Math.random() * 0.8,
    angle: Math.random() * Math.PI * 2,
  }));
}

function spawnProcessingRipple(progress, forced = false) {
  const rect = resultContainer ? resultContainer.getBoundingClientRect() : null;
  const width = rect?.width || processingCanvas?.clientWidth || 0;
  const height = rect?.height || processingCanvas?.clientHeight || 0;
  const maxRadius = Math.hypot(width, height) * 0.58;
  if (!maxRadius) return;
  processingState.ripples.push({
    radius: forced ? 12 : 18 + progress * 0.18,
    speed: 3.6 + progress * 0.016,
    alpha: forced ? 0.95 : 0.78,
    width: 40 + progress * 0.32,
    maxRadius,
  });
  if (processingState.ripples.length > 8) processingState.ripples.shift();
}

function syncProcessingMeta(progress, data = {}) {
  const safeProgress = clamp(Math.round(progress || 0), 0, 100);
  const currentCopy = PROCESSING_COPY.find((item) => safeProgress <= item.until) || PROCESSING_COPY[PROCESSING_COPY.length - 1];
  if (processingDetail) processingDetail.textContent = currentCopy.text;

  const reportedSteps = Number(data.step || data.current_step || 0);
  const reportedTotal = Number(data.total_steps || data.steps || 0);
  const totalSteps = reportedTotal > 0 ? reportedTotal : 30;
  const currentSteps =
    reportedSteps > 0 ? Math.min(reportedSteps, totalSteps) : Math.min(totalSteps, Math.max(1, Math.round((safeProgress / 100) * totalSteps)));

  if (processingSteps) {
    const left = String(currentSteps).padStart(2, "0");
    const right = String(totalSteps).padStart(2, "0");
    processingSteps.textContent = `Steps ${left} / ${right}`;
  }
  if (processingPercent) processingPercent.textContent = `${String(safeProgress).padStart(2, "0")}%`;

  if (processingModel) {
    const sampler = data.sampler || data.phase_detail || "DPM++ 2M Karras";
    processingModel.textContent = `Sampler 閻?${String(sampler).slice(0, 42)}`;
  }
}

function drawProcessingPreview(width, height, centerX, centerY, progress) {
  const img = processingState.previewImage;
  if (!img || !img.complete || !img.naturalWidth || !processingCtx) return;
  const scale = Math.min(width / img.naturalWidth, height / img.naturalHeight);
  const drawWidth = img.naturalWidth * scale;
  const drawHeight = img.naturalHeight * scale;
  const drawX = (width - drawWidth) / 2;
  const drawY = (height - drawHeight) / 2;

  processingCtx.save();
  processingCtx.globalAlpha = 0.08 + progress * 0.0018;
  processingCtx.filter = `blur(${Math.max(18 - progress * 0.12, 4)}px) saturate(0.7) brightness(0.9)`;
  processingCtx.drawImage(img, drawX, drawY, drawWidth, drawHeight);
  processingCtx.restore();

  processingState.ripples.forEach((ripple, index) => {
    processingCtx.save();
    processingCtx.beginPath();
    processingCtx.arc(centerX, centerY, ripple.radius, 0, Math.PI * 2);
    processingCtx.lineWidth = ripple.width;
    processingCtx.stroke();
    processingCtx.clip();
    processingCtx.globalAlpha = clamp(0.1 + progress * 0.003 + index * 0.04, 0, 0.68);
    processingCtx.filter = `blur(${Math.max(12 - progress * 0.08 - index * 1.2, 1)}px) saturate(${1 + progress * 0.003}) brightness(${0.78 + progress * 0.0032})`;
    processingCtx.drawImage(img, drawX, drawY, drawWidth, drawHeight);
    processingCtx.restore();
  });
}

function drawProcessingHud(width, progress) {
  if (!processingCtx) return;
  processingCtx.save();
  processingCtx.font = "600 28px 'JetBrains Mono', monospace";
  processingCtx.textAlign = "right";
  processingCtx.textBaseline = "top";
  processingCtx.shadowBlur = 16;
  processingCtx.shadowColor = "rgba(139, 92, 246, 0.18)";
  processingCtx.fillStyle = "#475569";
  processingCtx.fillText(`${String(Math.round(progress)).padStart(2, "0")}%`, width - 28, 24);
  processingCtx.font = "500 10px 'JetBrains Mono', monospace";
  processingCtx.fillStyle = "rgba(100, 116, 139, 0.82)";
  processingCtx.fillText("GENERATION PROGRESS", width - 28, 58);
  processingCtx.restore();
}

function animateProcessingFrame(ts) {
  if (!processingState.active || !processingCtx || !processingCanvas) return;
  const rect = resultContainer ? resultContainer.getBoundingClientRect() : null;
  const width = rect?.width || processingCanvas.clientWidth;
  const height = rect?.height || processingCanvas.clientHeight;
  const cx = width / 2;
  const cy = height / 2;
  const centerPull = processingState.progress / 100;

  processingCtx.clearRect(0, 0, width, height);
  processingCtx.fillStyle = "rgba(255,255,255,0.08)";
  processingCtx.fillRect(0, 0, width, height);

  processingCtx.save();
  processingCtx.filter = "blur(18px) contrast(28)";

  processingState.particles.forEach((particle) => {
    particle.y -= particle.speed * 0.4;
    particle.x += Math.sin(ts / 1000 + particle.angle) * 0.7;
    particle.x += (cx - particle.x) * centerPull * 0.02;
    particle.y += (cy - particle.y) * centerPull * 0.02;
    if (particle.y < -50) {
      particle.y = height + 50;
      particle.x = Math.random() * width;
    }
    if (particle.x < -60) particle.x = width + 60;
    if (particle.x > width + 60) particle.x = -60;

    processingCtx.fillStyle = "#10B981";
    processingCtx.beginPath();
    processingCtx.arc(particle.x, particle.y, particle.size * (1 + centerPull), 0, Math.PI * 2);
    processingCtx.fill();
  });

  const coreSize = 40 + processingState.progress * 0.8;
  processingCtx.fillStyle = "#10B981";
  processingCtx.beginPath();
  processingCtx.arc(cx, cy, coreSize, 0, Math.PI * 2);
  processingCtx.fill();
  processingCtx.restore();

  drawProcessingHud(width, processingState.progress);
  processingState.frameId = requestAnimationFrame(animateProcessingFrame);
}

function setProcessingProgress(progress, data = {}) {
  processingState.progress = clamp(progress, 0, 100);
  syncProcessingMeta(processingState.progress, data);
}

const trigerWarp = {
  start(data = {}) {
    setProcessingOverlay(true, data);
  },
  update(progress, data = {}) {
    setProcessingProgress(progress, { ...data, progress });
  },
  finish() {
    revealProcessingOverlay();
  },
  stop() {
    setProcessingOverlay(false);
  },
  getCenter() {
    const rect = resultContainer ? resultContainer.getBoundingClientRect() : { width: 0, height: 0 };
    return { cx: rect.width / 2, cy: rect.height / 2 };
  },
};

function setProcessingOverlay(active, data = {}) {
  if (!loadingOverlay) return;
  if (active) {
    ensureProcessingResizeBinding();
    resizeProcessingCanvas();
    if (!processingState.active) {
      processingState.active = true;
      processingState.startTime = performance.now();
      processingState.lastTs = 0;
      processingState.ripples = [];
      processingState.lastRippleProgress = 0;
      processingState.flashUntil = 0;
      primeProcessingPreview();
      resetProcessingParticles();
      spawnProcessingRipple(0, true);
      loadingOverlay.classList.remove("revealing");
      loadingOverlay.classList.add("active");
      processingCanvas.classList.add("active");
      if (resultImage) resultImage.classList.add("is-generating");
      processingState.frameId = requestAnimationFrame(animateProcessingFrame);
    }
    setProcessingProgress(data.progress || 0, data);
    return;
  }

  loadingOverlay.classList.remove("active", "revealing");
  processingCanvas.classList.remove("active");
  if (processingState.frameId) cancelAnimationFrame(processingState.frameId);
  processingState.active = false;
  processingState.frameId = 0;
  processingState.lastTs = 0;
  processingState.ripples = [];
  processingState.particles = [];
  if (resultImage) resultImage.classList.remove("is-generating");
  if (processingCtx && processingCanvas) {
    processingCtx.clearRect(0, 0, processingCanvas.clientWidth, processingCanvas.clientHeight);
  }
}

function revealProcessingOverlay() {
  if (!loadingOverlay) return;
  let revealed = false;
  const doReveal = () => {
    if (revealed) return;
    revealed = true;
    processingState.progress = 100;
    syncProcessingMeta(100, { progress: 100, phase_detail: "Completed" });
    processingState.flashUntil = performance.now() + 520;
    loadingOverlay.classList.add("revealing");
    window.setTimeout(() => {
      setProcessingOverlay(false);
    }, 620);
    window.setTimeout(() => {
      if (resultImage) resultImage.classList.remove("is-generating");
    }, 90);
  };

  if (resultImage && !resultImage.complete) {
    resultImage.addEventListener("load", doReveal, { once: true });
    window.setTimeout(doReveal, 1200);
    return;
  }

  doReveal();
}

function randomizeStyleParams() {
  if (!modelSelect || !modelSelect.options.length) return;
  const opts = Array.from(modelSelect.options);
  const pick = opts[Math.floor(Math.random() * opts.length)];
  modelSelect.value = pick.value;
  setActiveModelCard(pick.value);
  if (strengthInput) {
    const min = Number.parseFloat(strengthInput.min);
    const max = Number.parseFloat(strengthInput.max);
    const step = Number.parseFloat(strengthInput.step) || 0.05;
    const raw = min + Math.random() * (max - min);
    const snapped = Math.round(raw / step) * step;
    const clamped = Math.min(max, Math.max(min, snapped));
    strengthInput.value = String(clamped);
    syncStrengthUI();
  }
}

async function copyStyleRecipe() {
  const modelKey = modelSelect ? modelSelect.value : "";
  const modelLabel =
    modelSelect && modelSelect.selectedIndex >= 0 ? modelSelect.options[modelSelect.selectedIndex].text.trim() : "";
  const strength = strengthInput ? Number.parseFloat(strengthInput.value) : null;
  const text = JSON.stringify(
    { page: "style-transfer", model: modelKey, modelLabel, strength },
    null,
    2
  );
  try {
    await navigator.clipboard.writeText(text);
    if (statusText) {
      const prev = statusText.textContent;
      statusText.textContent = "Recipe copied to clipboard";
      setTimeout(() => {
        if (statusText.textContent === "Recipe copied to clipboard") statusText.textContent = prev;
      }, 2200);
    } else {
      alert("Copied to clipboard");
    }
  } catch (_) {
    window.prompt("Copy manually:", text);
  }
}

async function pasteStyleRecipe() {
  let text = "";
  try {
    text = await navigator.clipboard.readText();
  } catch (_) {
    text = window.prompt("Paste recipe JSON:") || "";
  }
  const trimmed = text.trim();
  if (!trimmed) return;
  let obj;
  try {
    obj = JSON.parse(trimmed);
  } catch (_) {
    alert("Invalid JSON");
    return;
  }
  if (obj.page && obj.page !== "style-transfer") {
    alert("This recipe belongs to another page. Use paste recipe on the SD page.");
    return;
  }
  const key = obj.model || obj.modelName;
  if (key && modelSelect) {
    const found = Array.from(modelSelect.options).some((o) => o.value === key);
    if (!found) {
      alert("Model not found in the current list: " + key);
      return;
    }
    modelSelect.value = key;
    setActiveModelCard(key);
  }
  if (strengthInput && obj.strength != null) {
    const v = Number.parseFloat(obj.strength);
    if (!Number.isNaN(v)) {
      const min = Number.parseFloat(strengthInput.min);
      const max = Number.parseFloat(strengthInput.max);
      const step = Number.parseFloat(strengthInput.step) || 0.05;
      const snapped = Math.round(v / step) * step;
      strengthInput.value = String(Math.min(max, Math.max(min, snapped)));
      syncStrengthUI();
    }
  }
  if (statusText) statusText.textContent = "Recipe applied";
}

function updateQueueBanner() {
  const el = document.getElementById("queue-banner");
  if (!el) return;
  if (queueFiles.length <= 1) {
    el.hidden = true;
    return;
  }
  el.hidden = false;
  el.textContent = `Queue: ${queueIdx + 1} / ${queueFiles.length}`;
}

function recordStyleHistoryJob(jobId) {
  if (typeof HistoryLocal === "undefined") return;
  HistoryLocal.push({
    type: "style",
    jobId,
    at: Date.now(),
    modelName: modelSelect ? modelSelect.value : "",
    strength: strengthInput ? Number.parseFloat(strengthInput.value) : 1.5,
  });
}

function setActiveModelCard(modelValue) {
  if (!modelPicker) return;
  const cards = modelPicker.querySelectorAll(".style-card");
  cards.forEach((card) => {
    const isActive = card.dataset.value === modelValue;
    card.classList.toggle("active", isActive);
  });
}

function initModelPicker() {
  if (!modelSelect || !modelPicker) return;
  const cards = modelPicker.querySelectorAll(".style-card");
  if (!cards.length) return;

  const hasCurrentOption = Array.from(modelSelect.options).some((opt) => opt.value === modelSelect.value);
  if (!hasCurrentOption && cards[0].dataset.value) {
    modelSelect.value = cards[0].dataset.value;
  }

  setActiveModelCard(modelSelect.value);

  cards.forEach((card) => {
    card.addEventListener("click", () => {
      const nextValue = card.dataset.value;
      if (!nextValue) return;
      modelSelect.value = nextValue;
      setActiveModelCard(nextValue);
    });
  });
}

function syncStrengthUI() {
  if (!strengthInput || !strengthValue) return;
  strengthValue.textContent = Number.parseFloat(strengthInput.value).toFixed(2);
}

syncStrengthUI();
initModelPicker();
if (strengthInput) {
  strengthInput.addEventListener("input", syncStrengthUI);
}

function setPreviewMulti(input, container) {
  container.innerHTML = "";
  const files = input.files ? Array.from(input.files) : [];
  if (!files.length) {
    container.textContent = "No preview";
    return;
  }

  const first = files[0];
  const img = document.createElement("img");
  img.src = URL.createObjectURL(first);
  container.appendChild(img);

  if (files.length > 1) {
    const count = document.createElement("div");
    count.textContent = `${files.length} files`;
    container.appendChild(count);
  }
}

function setPreviewSingle(input, container) {
  container.innerHTML = "";
  const file = input.files ? input.files[0] : null;
  if (!file) {
    container.textContent = "No preview";
    return;
  }
  const img = document.createElement("img");
  img.src = URL.createObjectURL(file);
  container.appendChild(img);
}

if (contentInput) {
  contentInput.addEventListener("change", () => setPreviewMulti(contentInput, contentPreview));
}
if (styleInput) {
  styleInput.addEventListener("change", () => setPreviewSingle(styleInput, stylePreview));
}

function clearGallery() {
  if (resultGallery) resultGallery.innerHTML = "";
  if (resultImage) {
    resultImage.classList.remove("fade-in", "active");
    resultImage.classList.add("hidden");
    resultImage.src = "";
  }
}

// ============ 婵炲瓨绮岄惉鐓幥庨鈧幆宥嗘媴濮濆苯澧剧紓浣瑰姈椤ㄦ劗妲愬▎鎾崇妞ゆ劑鍊楅崹鍐测槈閹炬剚鍎撴繛鏉戞喘閺?==========
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
    // 婵犮垼娉涚粔鍫曞极閵堝棎浜滈柛锔诲幗缁愭姊洪幓鎺曞闁告埊绻濆鍨緞鐏炲墽鏆犳繝銏ｅ煐閻楃娀宕?QR 闂佹眹鍨婚崰鎰板垂濮樿泛瀚夌€广儱鎳庨～銈夋煥濞戞澧曠€殿噮鍓熷顐﹀级閸喖鑰挎繛鎴炴⒒閸犳捇寮妶鍥ｅ亾閻熸澘鏋︾紒杈ㄥ哺婵?
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
  closeBtn.textContent = "Close";
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
  img.alt = "QR code";
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
  linkWrap.textContent = "Download link: ";
  linkWrap.appendChild(link);

  const hint = document.createElement("div");
  hint.style.marginTop = "10px";
  hint.style.opacity = "0.86";
  hint.style.fontSize = "12.8px";
  hint.style.lineHeight = "1.45";
  hint.textContent = "The QR code points to the download endpoint for the generated result.";

  const actions = document.createElement("div");
  actions.style.display = "flex";
  actions.style.gap = "10px";
  actions.style.marginTop = "14px";
  actions.style.flexWrap = "wrap";
  actions.style.justifyContent = "flex-start";

  const copyBtn = document.createElement("button");
  copyBtn.type = "button";
  copyBtn.className = "secondary-btn";
  copyBtn.textContent = "Copy download link";
  copyBtn.addEventListener("click", async () => {
    const href = link.href;
    if (!href || href === "#") return;
    try {
      await navigator.clipboard.writeText(href);
      copyBtn.textContent = "Copied";
      setTimeout(() => (copyBtn.textContent = "Copy download link"), 1600);
    } catch (_) {
      window.prompt("Copy link manually:", href);
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

  // 濠殿噯绲界换鎴︻敃閼测晙娌柡鍥╁О娴犳盯姊洪锝呯瑨妞ゃ倕鍟幆鏃囩疀閹惧啿鈻忛梺鎸庣☉閻倹瀵奸埡鍛鐎广儰璁查崑鎾愁煥閸愨晛娓愰梻渚囧亞閸犳洜鎹㈠☉銏″€烽柛蹇擃槴閸嬫挸鈹戦崱鈺佹闂佺厧鍢查悺銊ノ涢銈嗗珰闂佸灝顑囧﹢鎾偡閺囩偞顥犳繛鎻掞躬瀵剚锛愭担铏规缂傚倷绀侀顓㈡偉濠婂牆违?
  const seq = ++qrModalSeq;

  const title = overlay.querySelector(".qr-modal-title");
  const status = overlay.querySelector(".qr-modal-status");
  const link = overlay.querySelector(".qr-modal-link");
  const img = overlay.querySelector("#qr-modal-img");

  const absDownloadUrl = toAbsUrl(downloadHref);

  if (title) title.textContent = String(titleText || "QR code");
  if (status) status.textContent = "Generating QR code...";
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
    if (status) status.textContent = "QR code ready. Scan to download.";
  } else {
    if (status) status.textContent = "Failed to generate QR code. Open the link directly.";
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

  if (imageIndex === 0 && resultImage) {
    resultImage.src = resultSrc;
    resultImage.alt = altText;
    resultImage.classList.remove("hidden", "is-generating", "fade-in", "active");
    void resultImage.offsetWidth;
    resultImage.classList.add("fade-in", "active");
  } else {
    const img = document.createElement("img");
    img.src = resultSrc;
    img.alt = altText;
    img.loading = imageIndex > 0 ? "lazy" : "eager";
    img.style.display = "block";
    img.classList.add("fade-in", "active");
    wrap.appendChild(img);
  }

  const actions = document.createElement("div");
  actions.className = "result-actions";

  const dlResult = document.createElement("a");
  dlResult.href = downloadUrlForJob(jobId, imageIndex, PAGE_DOWNLOAD_LABEL);
  dlResult.className = "secondary-btn download-link";
  dlResult.title = "仅下载结果图";
  dlResult.textContent = imageIndex > 0 ? `下载结果 ${imageIndex + 1}` : "下载结果图";
  actions.appendChild(dlResult);

  const qrResultBtn = document.createElement("button");
  qrResultBtn.type = "button";
  qrResultBtn.className = "secondary-btn";
  qrResultBtn.textContent = "结果二维码";
  qrResultBtn.title = "生成结果图下载二维码";
  qrResultBtn.addEventListener("click", async () => {
    await showQrModalForDownload("结果图二维码", dlResult.href);
  });
  actions.appendChild(qrResultBtn);

  const copyLinkBtn = document.createElement("button");
  copyLinkBtn.type = "button";
  copyLinkBtn.className = "secondary-btn";
  copyLinkBtn.textContent = "复制图片链接";
  copyLinkBtn.title = "复制结果图的完整链接";
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

  if (imageIndex === 0 && resultImage) {
    resultGallery.appendChild(actions);
    return;
  }

  wrap.appendChild(actions);
  resultGallery.appendChild(wrap);
}
function showSingleResult(jobId) {
  if (!resultGallery) return;
  clearGallery();
  const placeholder = document.getElementById("result-placeholder");
  if (placeholder) placeholder.style.display = "none";
  appendResultWithDownload(jobId, 0, "Transfer result");
}

function showBatchResults(jobId, count) {
  if (!resultGallery) return;
  clearGallery();
  const placeholder = document.getElementById("result-placeholder");
  if (placeholder) placeholder.style.display = "none";
  const n = Math.max(0, Number(count || 0));
  for (let i = 0; i < n; i++) {
    appendResultWithDownload(jobId, i, `Transfer result ${i + 1}`);
  }
}

function setCancelEnabled(enabled) {
  if (!cancelBtn) return;
  cancelBtn.disabled = !enabled;
}

async function submitQueueStyleJob() {
  const file = queueFiles[queueIdx];
  if (!file) return;
  const downCb = document.getElementById("upload-downscale-checkbox");
  const useDown = !!(downCb && downCb.checked && window.ClientHelpers);
  const maxEdge = 2048;
  let contentFile = file;
  if (useDown) {
    if (statusText) {
      statusText.textContent =
        queueFiles.length > 1 ? `Compressing ${queueIdx + 1}/${queueFiles.length}...` : "Compressing image...";
    }
    contentFile = await ClientHelpers.downscaleImageFile(file, maxEdge);
  }
  let styleFile = styleInput && styleInput.files && styleInput.files[0];
  if (styleFile && useDown) {
    styleFile = await ClientHelpers.downscaleImageFile(styleFile, maxEdge);
  }
  const formData = new FormData();
  formData.append("content_image", contentFile);
  if (styleFile) {
    formData.append("style_image", styleFile);
  }
  formData.append("model_name", modelSelect.value);
  if (strengthInput) {
    formData.append("strength", strengthInput.value);
  }

  const resp = await fetch("/api/style-transfer", { method: "POST", body: formData });
  const data = await resp.json();
  if (!resp.ok || data.error) {
    throw new Error(data.error || "Failed to create job");
  }
  currentJobId = data.job_id;
  statusText.textContent =
    queueFiles.length > 1
      ? `Queued ${queueIdx + 1}/${queueFiles.length}. Waiting...`
      : "Job created. Processing...";
  pollStatus();
}

async function startStyleTransfer() {
  if (!contentInput || !contentInput.files || contentInput.files.length === 0) {
    alert("Please select a content image first");
    return;
  }
  if (modelSelect.value === "vgg19_neural_style" && (!styleInput || !styleInput.files || styleInput.files.length === 0)) {
    alert("VGG19 classic style transfer requires a style image.");
    return;
  }

  const files = Array.from(contentInput.files);
  queueFiles = files;
  queueIdx = 0;
  updateQueueBanner();

  if (typeof Notification !== "undefined" && Notification.permission === "default") {
    Notification.requestPermission();
  }

  setRunButtonsDisabled(true);
  if (cancelBtn) setCancelEnabled(false);
  statusText.textContent = "Submitting job to server...";
  progressBar.style.width = "0%";
  clearGallery();
  trigerWarp.start({ progress: 0, sampler: "DPM++ 2M Karras" });
  if (resultImage) {
    resultImage.classList.remove("fade-in");
    if (resultImage.src) resultImage.classList.remove("hidden");
    resultImage.classList.add("is-generating");
  }

  try {
    await submitQueueStyleJob();
  } catch (e) {
    console.error(e);
    alert("Submit failed: " + e.message);
    queueFiles = [];
    queueIdx = 0;
    updateQueueBanner();
    trigerWarp.stop();
  } finally {
    setRunButtonsDisabled(false);
  }
}

async function cancelCurrentJob() {
  if (!currentJobId) return;
  setCancelEnabled(false);
  statusText.textContent = "Cancel request sent...";
  trigerWarp.update(processingState.progress, {});
  try {
    const resp = await fetch(`/api/cancel/${currentJobId}`, { method: "POST" });
    const data = await resp.json();
    if (!resp.ok || data.error) throw new Error(data.error || "Cancel failed");
  } catch (e) {
    console.error(e);
  }
}

async function pollStatus() {
  if (!currentJobId) return;
  if (pollingTimer) clearTimeout(pollingTimer);

  try {
    const resp = await fetch(`/api/status/${currentJobId}`);
    const data = await resp.json();
    if (!resp.ok || data.error) {
      throw new Error(data.error || "Status query failed");
    }

    progressBar.style.width = `${data.progress || 0}%`;

    const status = data.status;
    const kind = data.kind;
    const count = data.result_count || 0;

    if (status === "queued") {
      statusText.textContent = formatPhaseLine(data);
      setCancelEnabled(true);
      trigerWarp.update(data.progress || 0, data);
      pollingTimer = setTimeout(pollStatus, nextPollMs());
      return;
    }

    if (status === "pending") {
      statusText.textContent = formatPhaseLine(data);
      setCancelEnabled(false);
      trigerWarp.update(data.progress || 0, data);
      pollingTimer = setTimeout(pollStatus, nextPollMs());
      return;
    }

    if (status === "running") {
      statusText.textContent = formatPhaseLine(data);
      setCancelEnabled(true);
      trigerWarp.update(data.progress || 0, data);
      pollingTimer = setTimeout(pollStatus, nextPollMs());
      return;
    }

    if (status === "finished") {
      statusText.textContent = formatPhaseLine({ ...data, phase: "done", phase_detail: "Completed" });
      setCancelEnabled(false);
      const multi = queueFiles.length > 1;
      recordStyleHistoryJob(currentJobId);
      if (queueFiles.length > 1 && queueIdx < queueFiles.length - 1) {
        queueIdx++;
        updateQueueBanner();
        void submitQueueStyleJob().catch((e) => {
          console.error(e);
          statusText.textContent = "Next queued item failed: " + e.message;
          queueFiles = [];
          queueIdx = 0;
          updateQueueBanner();
        });
        return;
      }
      if (multi) notifyDone("Style transfer", "Queue completed");
      queueFiles = [];
      queueIdx = 0;
      updateQueueBanner();
      if (kind === "batch" && count > 1) showBatchResults(currentJobId, count);
      else showSingleResult(currentJobId);
      trigerWarp.finish();
      playCompleteCelebration();
      return;
    }

    if (status === "cancelled") {
      statusText.textContent = "Task cancelled. Existing results are preserved.";
      setCancelEnabled(false);
      trigerWarp.stop();
      queueFiles = [];
      queueIdx = 0;
      updateQueueBanner();
      if (kind === "batch" && count > 1) showBatchResults(currentJobId, count);
      else if (data.has_result) showSingleResult(currentJobId);
      return;
    }

    if (status === "error") {
      statusText.textContent = "Task failed: " + (data.error || "Unknown error");
      setCancelEnabled(false);
      trigerWarp.stop();
      queueFiles = [];
      queueIdx = 0;
      updateQueueBanner();
      return;
    }

    // 闂佺绻戠划宀€鑺?
    pollingTimer = setTimeout(pollStatus, nextPollMs());
  } catch (e) {
    console.error(e);
    statusText.textContent = "Status query failed";
    setCancelEnabled(false);
    trigerWarp.stop();
  }
}

async function rerunJob(oldJobId) {
  statusText.textContent = "Re-running job...";
  progressBar.style.width = "0%";
  clearGallery();
  trigerWarp.start({ progress: 0, sampler: "DPM++ 2M Karras" });
  try {
    const resp = await fetch(`/api/rerun/${oldJobId}`, { method: "POST" });
    const data = await resp.json();
    if (!resp.ok || data.error) throw new Error(data.error || "Rerun failed");
    currentJobId = data.job_id;
    setCancelEnabled(false);
    pollStatus();
  } catch (e) {
    console.error(e);
    alert("Rerun failed: " + e.message);
    trigerWarp.stop();
  }
}

function applyStyleEntry(entry) {
  if (!entry || entry.type !== "style") return;
  if (modelSelect && entry.modelName) modelSelect.value = entry.modelName;
  if (strengthInput && entry.strength != null) {
    strengthInput.value = String(entry.strength);
    syncStrengthUI();
  }
}

function consumeHistoryApplyMain() {
  try {
    const raw = sessionStorage.getItem("historyApply");
    if (!raw) return;
    sessionStorage.removeItem("historyApply");
    const entry = JSON.parse(raw);
    if (entry.type === "style") applyStyleEntry(entry);
  } catch (e) {
    console.error(e);
  }
}

function consumeHistoryPreviewMain() {
  try {
    const raw = sessionStorage.getItem("historyPreview");
    if (!raw) return;
    sessionStorage.removeItem("historyPreview");
    const { jobId, type } = JSON.parse(raw);
    if (type !== "style") return;
    currentJobId = null;
    setCancelEnabled(false);
    showSingleResult(jobId);
  } catch (e) {
    console.error(e);
  }
}

if (runBtn) runBtn.addEventListener("click", startStyleTransfer);
if (cancelBtn) cancelBtn.addEventListener("click", cancelCurrentJob);

const randomParamsBtn = document.getElementById("random-params-btn");
const copyRecipeBtn = document.getElementById("copy-recipe-btn");
const pasteRecipeBtn = document.getElementById("paste-recipe-btn");
if (randomParamsBtn) randomParamsBtn.addEventListener("click", randomizeStyleParams);
if (copyRecipeBtn) copyRecipeBtn.addEventListener("click", () => void copyStyleRecipe());
if (pasteRecipeBtn) pasteRecipeBtn.addEventListener("click", () => void pasteStyleRecipe());

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

document.querySelectorAll(".strength-quick-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const v = btn.dataset.strength;
    if (!strengthInput || v == null || v === "") return;
    strengthInput.value = v;
    syncStrengthUI();
  });
});

consumeHistoryApplyMain();
consumeHistoryPreviewMain();

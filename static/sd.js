const contentInput = document.getElementById("content-input");
const contentPreview = document.getElementById("content-preview");
const runBtn = document.getElementById("run-btn");

function setRunButtonsDisabled(disabled) {
  if (runBtn) runBtn.disabled = disabled;
}
const cancelBtn = document.getElementById("cancel-btn");
const statusText = document.getElementById("status-text");
const progressBar = document.getElementById("progress-bar");
const resultGallery = document.getElementById("result-gallery");

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

/** 下载文件名前缀（与 /api/result 的 label 对应） */
const PAGE_DOWNLOAD_LABEL = "sd-img2img";

let currentJobId = null;
let pollingTimer = null;

let queueFiles = [];
let queueIdx = 0;

const PHASE_LABELS = {
  pending: "排队",
  downloading: "下载模型",
  loading_model: "加载模型",
  running: "推理中",
  done: "完成",
  error: "出错",
};

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
  if (typeof createCompareView === "function" && imageIndex === 0) {
    wrap.appendChild(createCompareView(jobId, resultSrc));
  } else {
    const img = document.createElement("img");
    img.src = resultSrc;
    img.alt = altText;
    img.style.display = "block";
    wrap.appendChild(img);
  }
  const actions = document.createElement("div");
  actions.className = "result-actions";
  const dlResult = document.createElement("a");
  dlResult.href = downloadUrlForJob(jobId, imageIndex, PAGE_DOWNLOAD_LABEL);
  dlResult.className = "secondary-btn download-link";
  dlResult.title = "仅包含 SD 转换后的结果图";
  dlResult.textContent =
    imageIndex > 0 ? `仅下载第 ${imageIndex + 1} 张结果` : "仅下载结果图";
  actions.appendChild(dlResult);

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
  }

  wrap.appendChild(actions);
  resultGallery.appendChild(wrap);
}

function showSingleResult(jobId) {
  if (!resultGallery) return;
  clearGallery();
  const placeholder = document.getElementById("result-placeholder");
  if (placeholder) placeholder.style.display = "none";
  appendResultWithDownload(jobId, 0, "转换结果");
}

function showBatchResults(jobId, count) {
  if (!resultGallery) return;
  clearGallery();
  const placeholder = document.getElementById("result-placeholder");
  if (placeholder) placeholder.style.display = "none";
  const n = Math.max(0, Number(count || 0));
  for (let i = 0; i < n; i++) {
    appendResultWithDownload(jobId, i, `转换结果 ${i + 1}`);
  }
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

  const formData = new FormData();
  formData.append("content_image", file);
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
    alert("请先选择内容图像");
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

  if (typeof Notification !== "undefined" && Notification.permission === "default") {
    Notification.requestPermission();
  }

  setRunButtonsDisabled(true);
  setCancelEnabled(false);
  statusText.textContent = removedTotal > 0
    ? `检测到 ${removedTotal} 个重复提示词，已自动去重，正在提交…`
    : "正在提交 SD 任务到服务器...";
  progressBar.style.width = "0%";
  clearGallery();

  try {
    await submitQueueSdJob();
  } catch (e) {
    console.error(e);
    alert("提交失败: " + e.message);
    queueFiles = [];
    queueIdx = 0;
    updateQueueBanner();
  } finally {
    setRunButtonsDisabled(false);
  }
}

async function cancelCurrentJob() {
  if (!currentJobId) return;
  setCancelEnabled(false);
  statusText.textContent = "取消请求已发送...";
  try {
    const resp = await fetch(`/api/cancel/${currentJobId}`, { method: "POST" });
    const data = await resp.json();
    if (!resp.ok || data.error) throw new Error(data.error || "取消失败");
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
    if (!resp.ok) throw new Error(data.error || "状态查询失败");

    progressBar.style.width = `${data.progress || 0}%`;

    const status = data.status;
    const kind = data.kind;
    const count = data.result_count || 0;

    if (status === "queued") {
      statusText.textContent = formatPhaseLine(data);
      setCancelEnabled(true);
      pollingTimer = setTimeout(pollStatus, 600);
      return;
    }

    if (status === "pending") {
      statusText.textContent = formatPhaseLine(data);
      setCancelEnabled(false);
      pollingTimer = setTimeout(pollStatus, 600);
      return;
    }

    if (status === "running") {
      statusText.textContent = formatPhaseLine(data);
      setCancelEnabled(true);
      pollingTimer = setTimeout(pollStatus, 600);
      return;
    }

    if (status === "finished") {
      statusText.textContent = formatPhaseLine({ ...data, phase: "done", phase_detail: "处理完成" });
      setCancelEnabled(false);
      const multi = queueFiles.length > 1;
      recordSdHistoryJob(currentJobId);
      if (queueFiles.length > 1 && queueIdx < queueFiles.length - 1) {
        queueIdx++;
        updateQueueBanner();
        void submitQueueSdJob().catch((e) => {
          console.error(e);
          statusText.textContent = "队列下一项提交失败: " + e.message;
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
      if (kind === "batch" && count > 1) showBatchResults(currentJobId, count);
      else showSingleResult(currentJobId);
      return;
    }

    if (status === "cancelled") {
      statusText.textContent = "任务已取消（已生成的结果保留）";
      setCancelEnabled(false);
      queueFiles = [];
      queueIdx = 0;
      updateQueueBanner();
      if (kind === "batch" && count > 1) showBatchResults(currentJobId, count);
      else if (data.has_result) showSingleResult(currentJobId);
      return;
    }

    if (status === "error") {
      statusText.textContent = "任务失败: " + (data.error || "未知错误");
      setCancelEnabled(false);
      queueFiles = [];
      queueIdx = 0;
      updateQueueBanner();
      return;
    }

    pollingTimer = setTimeout(pollStatus, 600);
  } catch (e) {
    console.error(e);
    statusText.textContent = "查询状态失败";
    setCancelEnabled(false);
  }
}

async function rerunJob(oldJobId) {
  statusText.textContent = "正在重跑任务...";
  progressBar.style.width = "0%";
  clearGallery();
  try {
    const resp = await fetch(`/api/rerun/${oldJobId}`, { method: "POST" });
    const data = await resp.json();
    if (!resp.ok || data.error) throw new Error(data.error || "重跑失败");
    currentJobId = data.job_id;
    setCancelEnabled(false);
    pollStatus();
  } catch (e) {
    console.error(e);
    alert("重跑失败: " + e.message);
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
consumeHistoryApplySd();
consumeHistoryPreviewSd();


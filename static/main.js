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
const strengthInput = document.getElementById("strength-input");
const strengthValue = document.getElementById("strength-value");
const modelPicker = document.getElementById("model-picker");

/** 下载文件名前缀（与 /api/result 的 label 对应） */
const PAGE_DOWNLOAD_LABEL = "style-transfer";

let currentJobId = null;
let pollingTimer = null;

/** 多图队列（仅当前页内存） */
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

function playCompleteCelebration() {
  const el = document.querySelector(".card-output .result-container");
  if (!el) return;
  el.classList.remove("celebrate-result");
  requestAnimationFrame(() => {
    void el.offsetWidth;
    el.classList.add("celebrate-result");
    setTimeout(() => el.classList.remove("celebrate-result"), 2100);
  });
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

function setPreviewSingle(input, container) {
  container.innerHTML = "";
  const file = input.files ? input.files[0] : null;
  if (!file) {
    container.textContent = "暂无预览";
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
  dlResult.title = "仅包含迁移后的结果图";
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
  appendResultWithDownload(jobId, 0, "迁移结果");
}

function showBatchResults(jobId, count) {
  if (!resultGallery) return;
  clearGallery();
  const placeholder = document.getElementById("result-placeholder");
  if (placeholder) placeholder.style.display = "none";
  const n = Math.max(0, Number(count || 0));
  for (let i = 0; i < n; i++) {
    appendResultWithDownload(jobId, i, `迁移结果 ${i + 1}`);
  }
}

function setCancelEnabled(enabled) {
  if (!cancelBtn) return;
  cancelBtn.disabled = !enabled;
}

async function submitQueueStyleJob() {
  const file = queueFiles[queueIdx];
  if (!file) return;
  const formData = new FormData();
  formData.append("content_image", file);
  if (styleInput && styleInput.files && styleInput.files[0]) {
    formData.append("style_image", styleInput.files[0]);
  }
  formData.append("model_name", modelSelect.value);
  if (strengthInput) {
    formData.append("strength", strengthInput.value);
  }

  const resp = await fetch("/api/style-transfer", { method: "POST", body: formData });
  const data = await resp.json();
  if (!resp.ok || data.error) {
    throw new Error(data.error || "任务创建失败");
  }
  currentJobId = data.job_id;
  statusText.textContent =
    queueFiles.length > 1
      ? `已提交队列 ${queueIdx + 1}/${queueFiles.length}，等待处理…`
      : "任务已创建，开始处理…";
  pollStatus();
}

async function startStyleTransfer() {
  if (!contentInput || !contentInput.files || contentInput.files.length === 0) {
    alert("请先选择内容图像");
    return;
  }
  if (modelSelect.value === "vgg19_neural_style" && (!styleInput || !styleInput.files || styleInput.files.length === 0)) {
    alert("VGG19 经典风格迁移需要上传风格图（style_image）");
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
  statusText.textContent = "正在提交任务到服务器...";
  progressBar.style.width = "0%";
  clearGallery();

  try {
    await submitQueueStyleJob();
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
    if (!resp.ok || data.error) {
      throw new Error(data.error || "状态查询失败");
    }

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
      recordStyleHistoryJob(currentJobId);
      if (queueFiles.length > 1 && queueIdx < queueFiles.length - 1) {
        queueIdx++;
        updateQueueBanner();
        void submitQueueStyleJob().catch((e) => {
          console.error(e);
          statusText.textContent = "队列下一项提交失败: " + e.message;
          queueFiles = [];
          queueIdx = 0;
          updateQueueBanner();
        });
        return;
      }
      if (multi) notifyDone("风格迁移", "队列已全部完成");
      queueFiles = [];
      queueIdx = 0;
      updateQueueBanner();
      playCompleteCelebration();
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

    // 兜底
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
if (randomParamsBtn) randomParamsBtn.addEventListener("click", randomizeStyleParams);
if (copyRecipeBtn) copyRecipeBtn.addEventListener("click", () => void copyStyleRecipe());

consumeHistoryApplyMain();
consumeHistoryPreviewMain();


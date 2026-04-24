function downloadUrlForJob(jobId, label) {
  const params = new URLSearchParams({
    t: String(Date.now()),
    download: "1",
    label: String(label || "result"),
  });
  return `/api/result/${encodeURIComponent(jobId)}?${params.toString()}`;
}

function normalizeType(type) {
  const value = String(type || "").toLowerCase();
  if (value === "style-transfer" || value === "style") return "style";
  if (value === "sd") return "sd";
  return "style";
}

function typeLabel(type) {
  return normalizeType(type) === "sd" ? "SD 重绘" : "风格迁移";
}

function modeBadge(type) {
  return normalizeType(type) === "sd" ? "SD" : "STYLE";
}

function formatDate(value) {
  const date = new Date(value || Date.now());
  if (Number.isNaN(date.getTime())) return "未知时间";
  return date.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

function makePreviewUrl(entry) {
  if (entry.thumb) return entry.thumb;
  if (entry.imgSrc) return entry.imgSrc;
  if (entry.jobId) return `/api/result/${encodeURIComponent(entry.jobId)}?t=${Date.now()}&index=0`;
  return "";
}

function goApply(entry) {
  try {
    sessionStorage.setItem("historyApply", JSON.stringify(entry));
  } catch (error) {
    console.error(error);
  }
  window.location.href = normalizeType(entry.type) === "sd" ? "/sd" : "/";
}

function goViewResult(entry) {
  try {
    sessionStorage.setItem(
      "historyPreview",
      JSON.stringify({ jobId: entry.jobId, type: normalizeType(entry.type) })
    );
  } catch (error) {
    console.error(error);
  }
  window.location.href = normalizeType(entry.type) === "sd" ? "/sd" : "/";
}

function matchesKeyword(entry, keyword) {
  if (!keyword) return true;
  const haystack = [entry.styleName, entry.mode, entry.prompt, entry.type, entry.jobId]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return haystack.includes(keyword.toLowerCase());
}

function buildEmptyState() {
  const node = document.createElement("div");
  node.className = "history-empty";
  node.innerHTML = `
    <div class="history-empty-icon">◈</div>
    <h2>还没有本地记录</h2>
    <p>完成一次风格迁移或 SD 重绘后，这里会自动收集结果卡片，方便你回看、复用和下载。</p>
    <div class="history-empty-actions">
      <a href="/" class="empty-link primary">去风格迁移</a>
      <a href="/sd" class="empty-link">去 SD 重绘</a>
    </div>
  `;
  return node;
}

function buildHistoryItem(entry) {
  const node = document.createElement("article");
  node.className = "history-item";

  const previewUrl = makePreviewUrl(entry);
  const title = entry.styleName || entry.mode || typeLabel(entry.type);
  const prompt = String(entry.prompt || "").trim();
  const meta = formatDate(entry.at || entry.timestamp);
  const badge = modeBadge(entry.type);

  node.innerHTML = `
    <div class="history-card-media">
      <span class="history-card-badge">${badge}</span>
      <div class="history-card-image-shell">
        <img src="${previewUrl}" alt="${title}" loading="lazy" />
      </div>
    </div>
    <div class="history-card-info">
      <div class="history-card-title">${title}</div>
      <div class="history-card-meta">
        <span>${meta}</span>
        <span class="history-card-type">${typeLabel(entry.type)}</span>
      </div>
      ${prompt ? `<div class="history-card-prompt">${prompt}</div>` : ""}
    </div>
    <div class="history-card-actions">
      <button type="button" class="history-action ghost action-apply">复用参数</button>
      <button type="button" class="history-action primary action-view">查看结果</button>
      ${entry.jobId ? `<a class="history-action ghost" href="${downloadUrlForJob(entry.jobId, normalizeType(entry.type) === "sd" ? "sd-result" : "style-result")}">下载结果</a>` : ""}
    </div>
    <div class="history-card-glint" aria-hidden="true"></div>
  `;

  const image = node.querySelector("img");
  const glint = node.querySelector(".history-card-glint");
  const applyButton = node.querySelector(".action-apply");
  const viewButton = node.querySelector(".action-view");

  if (image) {
    image.addEventListener("click", () => goViewResult(entry));
    image.addEventListener("error", () => {
      image.closest(".history-card-image-shell")?.classList.add("is-broken");
    });
  }

  applyButton?.addEventListener("click", () => goApply(entry));
  viewButton?.addEventListener("click", () => goViewResult(entry));

  node.addEventListener("mouseenter", () => {
    if (glint) glint.style.transform = "translateX(150%) skewX(-18deg)";
  });
  node.addEventListener("mouseleave", () => {
    if (glint) glint.style.transform = "translateX(-150%) skewX(-18deg)";
  });

  return node;
}

function renderHistoryPage() {
  const wall = document.getElementById("history-wall");
  const modeEl = document.getElementById("history-filter-mode");
  const keywordEl = document.getElementById("history-filter-q");
  const applyEl = document.getElementById("history-filter-apply");
  const resetEl = document.getElementById("history-filter-reset");

  if (!wall || typeof HistoryLocal === "undefined") return;

  const sourceItems = HistoryLocal.load()
    .slice()
    .sort((a, b) => Number(b.at || b.timestamp || 0) - Number(a.at || a.timestamp || 0));

  function getFilteredItems() {
    const mode = String(modeEl?.value || "").trim().toLowerCase();
    const keyword = String(keywordEl?.value || "").trim();
    return sourceItems.filter((entry) => {
      if (mode && normalizeType(entry.type) !== normalizeType(mode)) return false;
      return matchesKeyword(entry, keyword);
    });
  }

  function render() {
    const items = getFilteredItems();
    wall.innerHTML = "";

    if (!items.length) {
      wall.appendChild(buildEmptyState());
      return;
    }

    const nodes = items.map((entry) => buildHistoryItem(entry));
    if (typeof HistoryLocal.renderWithEffect === "function") {
      HistoryLocal.renderWithEffect(nodes, wall);
    } else {
      nodes.forEach((node) => wall.appendChild(node));
    }
  }

  applyEl?.addEventListener("click", render);
  resetEl?.addEventListener("click", () => {
    if (modeEl) modeEl.value = "";
    if (keywordEl) keywordEl.value = "";
    render();
  });

  keywordEl?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") render();
  });

  render();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", renderHistoryPage, { once: true });
} else {
  renderHistoryPage();
}

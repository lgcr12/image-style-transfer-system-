/**
 * 独立页：展示 localStorage 中的风格 + SD 记录
 */
function downloadUrlForJob(jobId, label) {
  const p = new URLSearchParams({
    t: String(Date.now()),
    download: "1",
    label: String(label || "result"),
  });
  return `/api/result/${jobId}?${p.toString()}`;
}

function downloadCompareUrlForJob(jobId, label) {
  const id = String(jobId == null ? "" : jobId).trim();
  if (!id || id === "undefined" || id === "null") {
    return "#";
  }
  const p = new URLSearchParams({
    t: String(Date.now()),
    download: "1",
    label: String(label || "compare"),
  });
  return `/api/compare-download/${encodeURIComponent(id)}?${p.toString()}`;
}

function goApply(entry) {
  try {
    sessionStorage.setItem("historyApply", JSON.stringify(entry));
  } catch (e) {
    console.error(e);
  }
  window.location.href = entry.type === "style" ? "/" : "/sd";
}

function goViewResult(entry) {
  try {
    sessionStorage.setItem(
      "historyPreview",
      JSON.stringify({ jobId: entry.jobId, type: entry.type })
    );
  } catch (e) {
    console.error(e);
  }
  window.location.href = entry.type === "style" ? "/" : "/sd";
}

function renderHistoryPage() {
  const historyList = document.getElementById("history-list");
  const countEl = document.getElementById("history-count");
  if (!historyList || typeof HistoryLocal === "undefined") return;

  const items = HistoryLocal.load().slice().sort((a, b) => (b.at || 0) - (a.at || 0));
  historyList.innerHTML = "";

  if (countEl) {
    countEl.textContent = items.length ? `共 ${items.length} 条` : "暂无记录";
  }

  if (!items.length) {
    historyList.innerHTML = `
      <div class="history-empty-state">
        <div class="history-empty-glow" aria-hidden="true"></div>
        <div class="history-empty-icon" aria-hidden="true">📭</div>
        <p class="history-empty-title">还没有任何记录</p>
        <p class="history-empty-desc">完成一次风格迁移或 SD 转换后，结果会自动出现在这里。</p>
        <div class="history-empty-actions">
          <a href="/" class="primary history-empty-btn">🎨 去风格迁移</a>
          <a href="/sd" class="secondary-btn history-empty-btn-secondary">✨ 去 SD 转换</a>
        </div>
      </div>`;
    return;
  }

  for (const item of items) {
    const row = document.createElement("div");
    row.className = "local-history-item";

    const badge = document.createElement("span");
    badge.className =
      item.type === "style"
        ? "history-type-badge history-type-badge--style"
        : "history-type-badge history-type-badge--sd";
    badge.textContent = item.type === "style" ? "风格迁移" : "SD";

    const thumb = document.createElement("img");
    thumb.className = "local-history-thumb";
    thumb.alt = "";
    thumb.loading = "lazy";
    thumb.src = `/api/result/${item.jobId}?t=${Date.now()}&index=0`;
    thumb.addEventListener("error", () => {
      thumb.style.visibility = "hidden";
    });

    const body = document.createElement("div");
    body.className = "local-history-body";

    const title = document.createElement("div");
    title.className = "local-history-title";
    if (item.type === "style") {
      title.textContent = `${item.modelName || "?"} · 强度 ${item.strength ?? "-"}`;
    } else {
      title.textContent = `${item.sdStyle || "?"} · 重绘 ${item.denoise ?? "-"} · ${item.steps ?? "?"}步`;
    }

    const time = document.createElement("div");
    time.className = "local-history-time";
    time.textContent = new Date(item.at || Date.now()).toLocaleString();

    const act = document.createElement("div");
    act.className = "local-history-actions";

    const reuse = document.createElement("button");
    reuse.type = "button";
    reuse.className = "secondary-btn";
    reuse.textContent = "复用参数";
    reuse.addEventListener("click", () => goApply(item));

    const view = document.createElement("button");
    view.type = "button";
    view.className = "secondary-btn secondary-btn-primary";
    view.textContent = "查看结果";
    view.addEventListener("click", () => goViewResult(item));

    const fileLabel = item.type === "style" ? "style-transfer" : "sd-img2img";

    const dlResult = document.createElement("a");
    dlResult.href = downloadUrlForJob(item.jobId, fileLabel);
    dlResult.className = "secondary-btn download-link";
    dlResult.title = "仅包含处理后的结果图";
    dlResult.textContent = "仅下载结果图";

    const dlCompare = document.createElement("a");
    dlCompare.href = downloadCompareUrlForJob(item.jobId, fileLabel);
    dlCompare.className = "secondary-btn secondary-btn-primary download-link";
    dlCompare.title = "原图与结果左右并排一张图";
    dlCompare.textContent = "下载对比图";

    act.appendChild(reuse);
    act.appendChild(view);
    act.appendChild(dlResult);
    act.appendChild(dlCompare);

    const head = document.createElement("div");
    head.className = "local-history-head";
    head.appendChild(badge);
    head.appendChild(title);
    body.appendChild(head);
    body.appendChild(time);
    body.appendChild(act);

    row.appendChild(thumb);
    row.appendChild(body);
    historyList.appendChild(row);
  }
}

document.addEventListener("DOMContentLoaded", renderHistoryPage);

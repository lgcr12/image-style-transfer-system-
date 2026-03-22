/**
 * 本地记录页：时间轴 + 缩略图墙
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

function formatDayHeading(isoDate) {
  const [y, m, d] = isoDate.split("-").map((x) => Number.parseInt(x, 10));
  return `${y} 年 ${m} 月 ${d} 日`;
}

function formatShortDay(isoDate) {
  const [y, m, d] = isoDate.split("-").map((x) => Number.parseInt(x, 10));
  const now = new Date();
  if (y === now.getFullYear()) return `${m}月${d}日`;
  return `${y}年${m}月${d}日`;
}

function buildWallItem(item) {
  const wrap = document.createElement("div");
  wrap.className = "history-wall-item";

  const badge = document.createElement("span");
  badge.className =
    item.type === "style"
      ? "history-wall-badge history-wall-badge--style"
      : "history-wall-badge history-wall-badge--sd";
  badge.textContent = item.type === "style" ? "迁移" : "SD";

  const img = document.createElement("img");
  img.alt = item.type === "style" ? "风格迁移缩略图" : "SD 结果缩略图";
  img.loading = "lazy";
  img.src = `/api/result/${item.jobId}?t=${Date.now()}&index=0`;
  img.addEventListener("click", () => goViewResult(item));
  img.addEventListener("error", () => {
    img.style.opacity = "0.25";
  });

  const time = document.createElement("div");
  time.className = "history-wall-item-time";
  time.textContent = new Date(item.at || Date.now()).toLocaleString();

  const act = document.createElement("div");
  act.className = "history-wall-item-actions";

  const reuse = document.createElement("button");
  reuse.type = "button";
  reuse.className = "secondary-btn";
  reuse.textContent = "复用";
  reuse.addEventListener("click", () => goApply(item));

  const view = document.createElement("button");
  view.type = "button";
  view.className = "secondary-btn secondary-btn-primary";
  view.textContent = "查看";
  view.addEventListener("click", () => goViewResult(item));

  const fileLabel = item.type === "style" ? "style-transfer" : "sd-img2img";

  const dlResult = document.createElement("a");
  dlResult.href = downloadUrlForJob(item.jobId, fileLabel);
  dlResult.className = "secondary-btn download-link";
  dlResult.textContent = "图";

  const dlCompare = document.createElement("a");
  dlCompare.href = downloadCompareUrlForJob(item.jobId, fileLabel);
  dlCompare.className = "secondary-btn download-link";
  dlCompare.textContent = "对比";

  act.appendChild(reuse);
  act.appendChild(view);
  act.appendChild(dlResult);
  act.appendChild(dlCompare);

  wrap.appendChild(badge);
  wrap.appendChild(img);
  wrap.appendChild(time);
  wrap.appendChild(act);
  return wrap;
}

function renderHistoryPage() {
  const wall = document.getElementById("history-wall");
  const timeline = document.getElementById("history-timeline");
  const countEl = document.getElementById("history-count");
  if (!wall || !timeline || typeof HistoryLocal === "undefined") return;

  const items = HistoryLocal.load().slice().sort((a, b) => (b.at || 0) - (a.at || 0));
  wall.innerHTML = "";
  timeline.innerHTML = "";

  if (countEl) {
    countEl.textContent = items.length ? `共 ${items.length} 条` : "暂无记录";
  }

  if (!items.length) {
    wall.innerHTML = `
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

  const byDay = new Map();
  for (const it of items) {
    const d = new Date(it.at || Date.now());
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    if (!byDay.has(key)) byDay.set(key, []);
    byDay.get(key).push(it);
  }
  const days = Array.from(byDay.keys()).sort((a, b) => b.localeCompare(a));

  function setActiveNode(el) {
    timeline.querySelectorAll(".history-timeline-node").forEach((n) => n.classList.remove("is-active"));
    if (el) el.classList.add("is-active");
  }

  const allBtn = document.createElement("button");
  allBtn.type = "button";
  allBtn.className = "history-timeline-node is-active";
  allBtn.innerHTML = `全部 <span class="history-timeline-count">${items.length}</span>`;
  allBtn.addEventListener("click", () => {
    setActiveNode(allBtn);
    const first = wall.querySelector(".history-wall-day");
    if (first) {
      first.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });
  timeline.appendChild(allBtn);

  for (const day of days) {
    const node = document.createElement("button");
    node.type = "button";
    node.className = "history-timeline-node";
    node.dataset.day = day;
    node.innerHTML = `${formatShortDay(day)} <span class="history-timeline-count">${byDay.get(day).length}</span>`;
    node.addEventListener("click", () => {
      setActiveNode(node);
      document.getElementById(`history-day-${day}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    timeline.appendChild(node);
  }

  for (const day of days) {
    const section = document.createElement("section");
    section.className = "history-wall-day";
    section.id = `history-day-${day}`;

    const h = document.createElement("h3");
    h.className = "history-wall-day-title";
    h.textContent = `${formatDayHeading(day)} · ${byDay.get(day).length} 条`;
    section.appendChild(h);

    const grid = document.createElement("div");
    grid.className = "history-wall-grid";
    for (const item of byDay.get(day)) {
      grid.appendChild(buildWallItem(item));
    }
    section.appendChild(grid);
    wall.appendChild(section);
  }
}

document.addEventListener("DOMContentLoaded", renderHistoryPage);

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

  const qrResultBtn = document.createElement("button");
  qrResultBtn.type = "button";
  qrResultBtn.className = "secondary-btn";
  qrResultBtn.textContent = "图二维码";
  qrResultBtn.title = "生成图下载二维码（手机扫码即可下载）";
  const resultDownloadHref = dlResult.href;
  qrResultBtn.addEventListener("click", async () => {
    await showQrModalForDownload("结果图二维码", resultDownloadHref);
  });

  const compareAttrHref = dlCompare.getAttribute("href") || "";
  const qrCompareBtn = document.createElement("button");
  qrCompareBtn.type = "button";
  qrCompareBtn.className = "secondary-btn";
  qrCompareBtn.textContent = "对比二维码";
  qrCompareBtn.title = "生成对比图下载二维码（手机扫码即可下载）";
  if (compareAttrHref === "#") {
    qrCompareBtn.disabled = true;
    qrCompareBtn.title = "对比下载不可用";
  } else {
    const compareDownloadHref = dlCompare.href;
    qrCompareBtn.addEventListener("click", async () => {
      await showQrModalForDownload("对比图二维码", compareDownloadHref);
    });
  }

  act.appendChild(reuse);
  act.appendChild(view);
  act.appendChild(dlResult);
  act.appendChild(dlCompare);
  act.appendChild(qrResultBtn);
  act.appendChild(qrCompareBtn);

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

/**
 * 原图 | 结果 滑杆对比 + 可拖拽竖线「拉帘」+ 并排切换
 * 依赖：/api/original/{jobId}、结果图 URL
 */
(function (global) {
  function createCompareView(jobId, resultSrc) {
    const origSrc = `/api/original/${jobId}?t=${Date.now()}`;
    const wrap = document.createElement("div");
    wrap.className = "compare-wrap";

    const inner = document.createElement("div");
    inner.className = "compare-inner";

    const base = document.createElement("img");
    base.className = "compare-base";
    base.alt = "原图";
    base.src = origSrc;

    const top = document.createElement("div");
    top.className = "compare-top";
    const topImg = document.createElement("img");
    topImg.className = "compare-top-img";
    topImg.src = resultSrc;
    topImg.alt = "结果";
    top.appendChild(topImg);

    const divider = document.createElement("div");
    divider.className = "compare-divider";
    divider.setAttribute("role", "slider");
    divider.setAttribute("aria-valuemin", "0");
    divider.setAttribute("aria-valuemax", "100");
    divider.setAttribute("aria-orientation", "horizontal");
    divider.setAttribute("aria-label", "拖动对比分界");
    divider.tabIndex = 0;

    const range = document.createElement("input");
    range.type = "range";
    range.min = "0";
    range.max = "100";
    range.value = "50";
    range.className = "compare-slider";
    range.setAttribute("aria-label", "对比位置");

    function setPctFromClientX(clientX) {
      const rect = inner.getBoundingClientRect();
      if (rect.width <= 0) return;
      const pct = ((clientX - rect.left) / rect.width) * 100;
      const v = Math.max(0, Math.min(100, pct));
      range.value = String(Math.round(v));
      sync();
    }

    function sync() {
      const v = Number(range.value);
      const pct = Math.max(0, Math.min(100, v));
      top.style.width = `${pct}%`;
      divider.style.left = `${pct}%`;
      divider.setAttribute("aria-valuenow", String(Math.round(pct)));
      const w = inner.offsetWidth;
      if (w > 0) {
        topImg.style.width = `${w}px`;
      }
    }

    range.addEventListener("input", sync);
    base.addEventListener("load", sync);
    topImg.addEventListener("load", sync);
    if (typeof ResizeObserver !== "undefined") {
      const ro = new ResizeObserver(() => sync());
      ro.observe(inner);
    }

    let dragging = false;
    divider.addEventListener("pointerdown", (e) => {
      if (wrap.classList.contains("compare--side")) return;
      e.preventDefault();
      dragging = true;
      divider.setPointerCapture(e.pointerId);
      inner.classList.add("compare-inner--dragging");
      setPctFromClientX(e.clientX);
    });
    divider.addEventListener("pointermove", (e) => {
      if (!dragging || !divider.hasPointerCapture(e.pointerId)) return;
      setPctFromClientX(e.clientX);
    });
    divider.addEventListener("pointerup", (e) => {
      if (divider.hasPointerCapture(e.pointerId)) {
        divider.releasePointerCapture(e.pointerId);
      }
      dragging = false;
      inner.classList.remove("compare-inner--dragging");
    });
    divider.addEventListener("pointercancel", (e) => {
      if (divider.hasPointerCapture(e.pointerId)) {
        divider.releasePointerCapture(e.pointerId);
      }
      dragging = false;
      inner.classList.remove("compare-inner--dragging");
    });

    divider.addEventListener("keydown", (e) => {
      if (wrap.classList.contains("compare--side")) return;
      const step = e.shiftKey ? 10 : 2;
      let v = Number(range.value);
      if (e.key === "ArrowLeft" || e.key === "ArrowDown") {
        e.preventDefault();
        v = Math.max(0, v - step);
      } else if (e.key === "ArrowRight" || e.key === "ArrowUp") {
        e.preventDefault();
        v = Math.min(100, v + step);
      } else if (e.key === "Home") {
        e.preventDefault();
        v = 0;
      } else if (e.key === "End") {
        e.preventDefault();
        v = 100;
      } else {
        return;
      }
      range.value = String(v);
      sync();
    });

    base.addEventListener("error", () => {
      wrap.classList.add("compare-no-original");
      const fb = document.createElement("p");
      fb.className = "compare-fallback-msg";
      fb.textContent = "无法加载原图，仅显示结果";
      inner.insertBefore(fb, inner.firstChild);
    });

    inner.appendChild(base);
    inner.appendChild(top);
    inner.appendChild(divider);
    wrap.appendChild(inner);
    wrap.appendChild(range);

    const hint = document.createElement("div");
    hint.className = "compare-hint";
    hint.textContent = "拖动竖线或下方滑块：左侧原图，右侧结果（适合截图分享）";
    wrap.appendChild(hint);

    const modeRow = document.createElement("div");
    modeRow.className = "compare-mode-row";
    const modeBtn = document.createElement("button");
    modeBtn.type = "button";
    modeBtn.className = "secondary-btn";
    modeBtn.textContent = "切换并排";
    let side = false;
    modeBtn.addEventListener("click", () => {
      side = !side;
      wrap.classList.toggle("compare--side", side);
      modeBtn.textContent = side ? "切换拉帘对比" : "切换并排";
      range.style.display = side ? "none" : "block";
      divider.style.display = side ? "none" : "block";
      if (!side) sync();
    });
    modeRow.appendChild(modeBtn);

    const lens = document.createElement("div");
    lens.className = "compare-lens";
    lens.style.display = "none";
    lens.style.position = "absolute";
    lens.style.width = "140px";
    lens.style.height = "140px";
    lens.style.borderRadius = "50%";
    lens.style.border = "2px solid rgba(99,102,241,0.8)";
    lens.style.boxShadow = "0 6px 18px rgba(0,0,0,0.25)";
    lens.style.pointerEvents = "none";
    lens.style.backgroundImage = `url(${resultSrc})`;
    lens.style.backgroundRepeat = "no-repeat";
    lens.style.backgroundSize = "250% 250%";
    lens.style.zIndex = "6";
    inner.style.position = "relative";
    inner.appendChild(lens);

    let lensEnabled = false;
    const lensBtn = document.createElement("button");
    lensBtn.type = "button";
    lensBtn.className = "secondary-btn";
    lensBtn.textContent = "放大镜(结果)";
    lensBtn.addEventListener("click", () => {
      lensEnabled = !lensEnabled;
      lens.style.display = lensEnabled ? "block" : "none";
      lensBtn.textContent = lensEnabled ? "关闭放大镜" : "放大镜(结果)";
    });
    modeRow.appendChild(lensBtn);
    inner.addEventListener("pointermove", (e) => {
      if (!lensEnabled) return;
      const rect = inner.getBoundingClientRect();
      const x = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
      const y = Math.max(0, Math.min(rect.height, e.clientY - rect.top));
      lens.style.left = `${x - 70}px`;
      lens.style.top = `${y - 70}px`;
      const bx = (x / Math.max(1, rect.width)) * 100;
      const by = (y / Math.max(1, rect.height)) * 100;
      lens.style.backgroundPosition = `${bx}% ${by}%`;
    });
    inner.addEventListener("pointerleave", () => {
      if (lensEnabled) lens.style.display = "none";
    });
    inner.addEventListener("pointerenter", () => {
      if (lensEnabled) lens.style.display = "block";
    });
    wrap.appendChild(modeRow);

    sync();
    return wrap;
  }

  function downloadCompareUrlForJob(jobId, label) {
    const id = String(jobId == null ? "" : jobId).trim();
    if (!id || id === "undefined" || id === "null") {
      console.warn("downloadCompareUrlForJob: 缺少有效 jobId");
      return "#";
    }
    const p = new URLSearchParams({
      t: String(Date.now()),
      download: "1",
      label: String(label || "compare"),
    });
    return `/api/compare-download/${encodeURIComponent(id)}?${p.toString()}`;
  }

  global.createCompareView = createCompareView;
  global.downloadCompareUrlForJob = downloadCompareUrlForJob;
  if (typeof window !== "undefined") {
    window.createCompareView = createCompareView;
    window.downloadCompareUrlForJob = downloadCompareUrlForJob;
  }
})(typeof window !== "undefined" ? window : globalThis);

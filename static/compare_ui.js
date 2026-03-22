/**
 * 原图 | 结果 滑杆对比 + 并排切换
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
    divider.setAttribute("aria-hidden", "true");

    const range = document.createElement("input");
    range.type = "range";
    range.min = "0";
    range.max = "100";
    range.value = "50";
    range.className = "compare-slider";

    function sync() {
      const v = Number(range.value);
      const pct = Math.max(0, Math.min(100, v));
      top.style.width = `${pct}%`;
      divider.style.left = `${pct}%`;
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
    hint.textContent = "拖动滑块：左侧为原图，右侧为结果";
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
      modeBtn.textContent = side ? "切换滑杆对比" : "切换并排";
      range.style.display = side ? "none" : "block";
      divider.style.display = side ? "none" : "block";
      if (!side) sync();
    });
    modeRow.appendChild(modeBtn);
    wrap.appendChild(modeRow);

    sync();
    return wrap;
  }

  /**
   * 下载服务端生成的「原图 | 结果」左右并排 PNG（/api/compare-download）
   */
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

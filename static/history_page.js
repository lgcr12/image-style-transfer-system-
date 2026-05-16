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

function dateKey(value) {
  const date = new Date(value || Date.now());
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
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
  smoothNavigate(normalizeType(entry.type) === "sd" ? "/sd" : "/");
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
  smoothNavigate(normalizeType(entry.type) === "sd" ? "/sd" : "/");
}

async function goRerun(entry) {
  if (!entry || !entry.jobId) return;
  if (normalizeType(entry.type) !== "sd") {
    alert("当前只支持从本地记录一键重跑 SD 重绘任务。");
    return;
  }
  try {
    const response = await fetch(`/api/rerun/${encodeURIComponent(entry.jobId)}`, { method: "POST" });
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || "重跑失败");
    sessionStorage.setItem("historyPoll", JSON.stringify({ jobId: data.job_id, type: "sd" }));
    smoothNavigate("/sd");
  } catch (error) {
    console.error(error);
    alert(`重跑失败：${error && error.message ? error.message : "未知错误"}`);
  }
}

function smoothNavigate(url) {
  if (!url) return;
  if (document.body.classList.contains("is-page-leaving")) return;
  document.body.classList.add("is-page-leaving");
  const navigate = () => {
    window.location.href = url;
  };
  window.setTimeout(navigate, 1200);
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
    <div class="history-item-info history-card-info">
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
      ${entry.jobId && normalizeType(entry.type) === "sd" ? `<button type="button" class="history-action ghost action-rerun">重跑</button>` : ""}
      ${entry.jobId ? `<a class="history-action ghost" href="${downloadUrlForJob(entry.jobId, normalizeType(entry.type) === "sd" ? "sd-result" : "style-result")}">下载结果</a>` : ""}
    </div>
    <div class="history-card-glint" aria-hidden="true"></div>
  `;

  const image = node.querySelector("img");
  const glint = node.querySelector(".history-card-glint");

  image?.addEventListener("click", () => goViewResult(entry));
  image?.addEventListener("error", () => {
    image.closest(".history-card-image-shell")?.classList.add("is-broken");
  });

  node.querySelector(".action-apply")?.addEventListener("click", () => goApply(entry));
  node.querySelector(".action-view")?.addEventListener("click", () => goViewResult(entry));
  node.querySelector(".action-rerun")?.addEventListener("click", () => void goRerun(entry));

  node.addEventListener("mouseenter", () => {
    if (!glint) return;
    glint.style.opacity = "1";
    glint.style.transform = "translateX(150%) skewX(-18deg)";
  });
  node.addEventListener("mouseleave", () => {
    if (!glint) return;
    glint.style.opacity = "0";
    glint.style.transform = "translateX(-150%) skewX(-18deg)";
  });

  return node;
}

function buildTimeline(items, timelineEl, wall) {
  if (!timelineEl) return;
  timelineEl.innerHTML = "";

  const byDay = new Map();
  items.forEach((entry) => {
    const key = dateKey(entry.at || entry.timestamp);
    if (!byDay.has(key)) byDay.set(key, 0);
    byDay.set(key, byDay.get(key) + 1);
  });

  Array.from(byDay.entries())
    .sort((a, b) => b[0].localeCompare(a[0]))
    .forEach(([key, count]) => {
      const node = document.createElement("button");
      node.type = "button";
      node.className = "timeline-node";
      node.innerHTML = `
        <span class="timeline-label">${key}</span>
        <span class="timeline-count">${count}</span>
      `;
      node.addEventListener("click", () => {
        const target = wall.querySelector(`[data-date-key="${key}"]`);
        target?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
      timelineEl.appendChild(node);
    });
}

function renderHistoryPage() {
  const wall = document.getElementById("history-wall");
  const timelineEl = document.getElementById("history-timeline");
  const modeEl = document.getElementById("history-filter-mode");
  const keywordEl = document.getElementById("history-filter-q");
  const applyEl = document.getElementById("history-filter-apply");
  const resetEl = document.getElementById("history-filter-reset");
  const sampleCountEl = document.getElementById("sample-count");

  if (!wall || typeof HistoryLocal === "undefined") return;

  const sourceItems = HistoryLocal.load()
    .slice()
    .sort((a, b) => Number(b.at || b.timestamp || 0) - Number(a.at || a.timestamp || 0));

  if (sampleCountEl) sampleCountEl.textContent = String(sourceItems.length);
  buildTimeline(sourceItems, timelineEl, wall);

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

    const nodes = items.map((entry) => {
      const node = buildHistoryItem(entry);
      node.dataset.dateKey = dateKey(entry.at || entry.timestamp);
      return node;
    });

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

function bindNavTransitions() {
  document.querySelectorAll(".history-nav-pill, .history-empty a").forEach((link) => {
    link.addEventListener("click", (event) => {
      const targetUrl = link.getAttribute("href");
      if (!targetUrl) return;
      event.preventDefault();
      smoothNavigate(targetUrl);
    });
  });
}

const EcoWeather = {
  config: {
    cacheKey: "eco_weather_cache",
  },

  async init() {
    const forced = this.getPreviewMode();
    if (forced) {
      this.apply(forced);
      return;
    }

    const cached = this.getCache();
    if (cached) {
      this.apply(cached);
      return;
    }

    await this.fetchWeather();
  },

  async fetchWeather() {
    try {
      const response = await fetch("/api/weather/now", { cache: "no-store" });
      const data = await response.json();

      if (response.ok && data.ok) {
        const info = {
          text: data.text,
          temp: data.temp,
          icon: data.icon,
          time: data.fetched_at || Date.now(),
        };
        this.setCache(info);
        this.apply(info);
        return;
      }

      console.warn("天气传感器同步失败，进入默认环境模式", data);
    } catch (error) {
      console.warn("天气传感器同步失败，进入默认环境模式", error);
    }

    this.apply({
      text: "多云",
      temp: "--",
      icon: "☁",
      time: Date.now(),
    });
  },

  apply(info) {
    const body = document.body;
    const textEl = document.getElementById("w-text");
    const tempEl = document.getElementById("w-temp");
    const iconEl = document.getElementById("w-icon");

    let weatherClass = "w-cloudy";
    let icon = "☁";

    if (String(info.text || "").includes("晴")) {
      weatherClass = "w-clear";
      icon = "☀";
    } else if (String(info.text || "").includes("雨")) {
      weatherClass = "w-rain";
      icon = "☂";
    } else if (String(info.text || "").includes("雪")) {
      weatherClass = "w-snow";
      icon = "❄";
    }

    body.classList.remove("w-clear", "w-rain", "w-snow", "w-cloudy");
    body.classList.add(weatherClass);

    if (textEl) textEl.innerText = info.text || "多云";
    if (tempEl) tempEl.innerText = `${info.temp ?? "--"}°C`;
    if (iconEl) iconEl.innerText = icon;

    const rateVal = document.querySelector(".status-value");
    if (rateVal) {
      rateVal.innerText = String(info.text || "").includes("晴") ? "96% (高能)" : "38% (休眠)";
    }

    this.createWeatherParticles(weatherClass);
  },

  setCache(data) {
    localStorage.setItem(this.config.cacheKey, JSON.stringify(data));
  },

  getCache() {
    const raw = localStorage.getItem(this.config.cacheKey);
    if (!raw) return null;
    try {
      const data = JSON.parse(raw);
      if (Date.now() - data.time > 30 * 60 * 1000) return null;
      return data;
    } catch {
      return null;
    }
  },

  getPreviewMode() {
    const params = new URLSearchParams(window.location.search);
    const weather = String(params.get("weather") || "").toLowerCase();
    if (!weather) return null;

    if (weather === "snow") {
      return { text: "雪", temp: "-2", icon: "❄", time: Date.now() };
    }
    if (weather === "rain") {
      return { text: "雨", temp: "12", icon: "☂", time: Date.now() };
    }
    if (weather === "clear") {
      return { text: "晴", temp: "26", icon: "☀", time: Date.now() };
    }
    if (weather === "cloudy") {
      return { text: "多云", temp: "21", icon: "☁", time: Date.now() };
    }
    return null;
  },

  createWeatherParticles(type) {
    const container = document.getElementById("weather-particles");
    if (!container) return;

    container.innerHTML = "";
    if (type !== "w-rain" && type !== "w-snow") return;

    const count = type === "w-rain" ? 160 : 90;
    for (let i = 0; i < count; i += 1) {
      const particle = document.createElement("div");
      particle.className = "weather-particle";
      particle.style.left = `${Math.random() * 100}vw`;
      particle.style.top = `${Math.random() * -140}vh`;

      const duration = type === "w-rain" ? Math.random() * 0.55 + 0.45 : Math.random() * 4 + 4.5;
      particle.style.animationDuration = `${duration}s`;
      particle.style.animationDelay = `${Math.random() * 5}s`;

      if (type === "w-rain") {
        particle.style.height = `${Math.random() * 45 + 70}px`;
        particle.style.opacity = `${Math.random() * 0.35 + 0.45}`;
      } else {
        const size = `${Math.random() * 8 + 5}px`;
        particle.style.width = size;
        particle.style.height = size;
        particle.style.opacity = `${Math.random() * 0.35 + 0.55}`;
      }

      container.appendChild(particle);
    }
  },
};

if (document.readyState === "loading") {
  document.addEventListener(
    "DOMContentLoaded",
    () => {
      renderHistoryPage();
      bindNavTransitions();
      EcoWeather.init();
      requestAnimationFrame(() => {
        document.body.classList.add("is-page-entered");
      });
      window.setTimeout(() => {
        document.body.classList.remove("is-page-entering");
        document.body.classList.remove("is-page-entered");
      }, 1500);
    },
    { once: true }
  );
} else {
  renderHistoryPage();
  bindNavTransitions();
  EcoWeather.init();
  requestAnimationFrame(() => {
    document.body.classList.add("is-page-entered");
  });
  window.setTimeout(() => {
    document.body.classList.remove("is-page-entering");
    document.body.classList.remove("is-page-entered");
  }, 1500);
}


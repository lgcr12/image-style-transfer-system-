/**
 * 浏览器本地历史（localStorage），保存最近 N 条任务参数与 jobId。
 */
(function (global) {
  const KEY = "models_local_history_v1";
  const MAX = 20;

  function load() {
    try {
      const raw = localStorage.getItem(KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed.items) ? parsed.items : [];
    } catch {
      return [];
    }
  }

  function save(items) {
    localStorage.setItem(KEY, JSON.stringify({ version: 1, items }));
  }

  function push(entry) {
    const normalized = {
      ...entry,
      at: entry?.at || entry?.timestamp || Date.now(),
      timestamp: entry?.timestamp || entry?.at || Date.now(),
    };
    const items = load().filter((x) => x.jobId !== normalized.jobId);
    items.unshift(normalized);
    save(items.slice(0, MAX));
  }

  function renderWithEffect(items, container) {
    if (!container) return;
    container.innerHTML = "";
    items.forEach((node, index) => {
      container.appendChild(node);
      node.classList.add("opacity-0", "translate-y-4");
      node.style.transition =
        "opacity 0.6s cubic-bezier(0.23, 1, 0.32, 1), transform 0.6s cubic-bezier(0.23, 1, 0.32, 1)";
      node.style.transitionDelay = `${index * 0.1}s`;
      requestAnimationFrame(() => {
        node.classList.remove("opacity-0", "translate-y-4");
      });
    });
  }

  global.HistoryLocal = { load, save, push, renderWithEffect, MAX, KEY };
})(typeof window !== "undefined" ? window : globalThis);

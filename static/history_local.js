/**
 * 浏览器本地历史（localStorage），最近 N 条任务参数 + jobId，用于缩略图与复用。
 */
(function (global) {
  const KEY = "models_local_history_v1";
  const MAX = 20;

  function load() {
    try {
      const raw = localStorage.getItem(KEY);
      if (!raw) return [];
      const j = JSON.parse(raw);
      return Array.isArray(j.items) ? j.items : [];
    } catch {
      return [];
    }
  }

  function save(items) {
    localStorage.setItem(KEY, JSON.stringify({ version: 1, items }));
  }

  function push(entry) {
    const items = load().filter((x) => x.jobId !== entry.jobId);
    items.unshift(entry);
    save(items.slice(0, MAX));
  }

  global.HistoryLocal = { load, push, MAX, KEY };
})(typeof window !== "undefined" ? window : globalThis);

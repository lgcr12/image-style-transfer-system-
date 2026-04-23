async function renderEvalDashboard() {
  const summary = document.getElementById("eval-summary");
  const tbody = document.querySelector("#eval-table tbody");
  if (!summary || !tbody) return;
  try {
    const resp = await fetch("/api/eval/summary?limit=1600");
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || "加载失败");
    summary.textContent = `总任务 ${data.total || 0}，完成 ${data.finished || 0}，失败 ${data.error || 0}`;
    tbody.innerHTML = "";
    for (const row of data.styles || []) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td style="text-align:left;">${row.style || "-"}</td>
        <td style="text-align:center;">${row.count ?? 0}</td>
        <td style="text-align:center;">${row.avg_score ?? "-"}</td>
        <td style="text-align:center;">${row.max_score ?? "-"}</td>
        <td style="text-align:center;">${row.min_score ?? "-"}</td>
      `;
      tbody.appendChild(tr);
    }
  } catch (e) {
    summary.textContent = `加载失败：${e.message || e}`;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  void renderEvalDashboard();
});

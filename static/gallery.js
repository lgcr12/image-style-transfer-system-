async function renderGallery() {
  const grid = document.getElementById("gallery-grid");
  if (!grid) return;
  grid.innerHTML = "加载中…";
  try {
    const resp = await fetch("/api/gallery/list?limit=120");
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || "加载失败");
    const items = Array.isArray(data.items) ? data.items : [];
    if (!items.length) {
      grid.innerHTML = "<p class='help-text'>暂无已发布作品</p>";
      return;
    }
    grid.innerHTML = "";
    for (const it of items) {
      const card = document.createElement("article");
      card.className = "history-wall-item";
      const img = document.createElement("img");
      img.src = it.preview_url;
      img.alt = "画廊作品";
      img.loading = "lazy";
      const meta = document.createElement("div");
      meta.className = "history-wall-item-time";
      const name = it.anonymous ? "匿名用户" : "本地用户";
      meta.textContent = `${name} · ${it.mode || "-"} · score ${it.score ?? "-"}`;
      const title = document.createElement("div");
      title.className = "history-wall-item-time";
      title.textContent = it.title || "未命名作品";
      card.appendChild(img);
      card.appendChild(title);
      card.appendChild(meta);
      grid.appendChild(card);
    }
  } catch (e) {
    grid.innerHTML = `<p class='help-text'>加载失败：${e.message || e}</p>`;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  void renderGallery();
});

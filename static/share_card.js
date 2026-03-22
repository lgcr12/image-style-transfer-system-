/**
 * Canvas 合成分享卡片：结果图 + 参数文案 + 水印 + 可选二维码（需联网拉 QR 图）
 */
(function (global) {
  async function loadImageCrossOrigin(src) {
    const img = new Image();
    img.crossOrigin = "anonymous";
    const ok = await new Promise((resolve) => {
      img.onload = () => resolve(true);
      img.onerror = () => resolve(false);
      img.src = src;
    });
    return ok ? img : null;
  }

  async function fetchQrImage(text) {
    try {
      const u = `https://api.qrserver.com/v1/create-qr-code/?size=180x180&margin=1&data=${encodeURIComponent(text)}`;
      const r = await fetch(u);
      if (!r.ok) return null;
      const blob = await r.blob();
      const objUrl = URL.createObjectURL(blob);
      const img = await new Promise((resolve) => {
        const im = new Image();
        im.onload = () => {
          URL.revokeObjectURL(objUrl);
          resolve(im);
        };
        im.onerror = () => {
          URL.revokeObjectURL(objUrl);
          resolve(null);
        };
        im.src = objUrl;
      });
      return img;
    } catch (_) {
      return null;
    }
  }

  function drawWrappedLines(ctx, text, x, y, maxWidth, lineHeight, maxLines) {
    if (!text) return y;
    const words = String(text).split(/\s+/).filter(Boolean);
    let line = "";
    let ly = y;
    let n = 0;
    for (let i = 0; i < words.length && n < maxLines; i++) {
      const test = line ? `${line} ${words[i]}` : words[i];
      if (ctx.measureText(test).width > maxWidth && line) {
        ctx.fillText(line, x, ly);
        ly += lineHeight;
        n++;
        line = words[i];
      } else {
        line = test;
      }
    }
    if (line && n < maxLines) {
      const t = line.length > 90 ? line.slice(0, 87) + "…" : line;
      ctx.fillText(t, x, ly);
      ly += lineHeight;
    }
    return ly;
  }

  /**
   * @param {string} jobId
   * @param {string[]} captionLines 已排版好的短行
   * @param {string} [promptSnippet] 可选一行提示词摘要
   */
  async function buildSdShareCard(jobId, captionLines, promptSnippet) {
    const id = String(jobId || "").trim();
    if (!id) {
      alert("缺少任务 ID");
      return;
    }
    const ts = Date.now();
    const resultPath = `/api/result/${encodeURIComponent(id)}?t=${ts}&index=0`;
    const img = await loadImageCrossOrigin(new URL(resultPath, window.location.origin).href);
    if (!img || !img.naturalWidth) {
      alert("无法加载结果图，请稍后重试");
      return;
    }

    const W = 1080;
    const pad = 28;
    const footerH = 200;
    const gap = 16;
    const maxImgH = 920;
    const scale = Math.min((W - 2 * pad) / img.naturalWidth, maxImgH / img.naturalHeight, 1);
    const dw = Math.round(img.naturalWidth * scale);
    const dh = Math.round(img.naturalHeight * scale);
    const H = pad + dh + gap + footerH + pad;

    const canvas = document.createElement("canvas");
    canvas.width = W;
    canvas.height = H;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      alert("浏览器不支持 Canvas");
      return;
    }

    const g = ctx.createLinearGradient(0, 0, W, H);
    g.addColorStop(0, "#1e1b4b");
    g.addColorStop(1, "#0f172a");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, H);

    const ix = (W - dw) / 2;
    ctx.shadowColor = "rgba(244, 114, 182, 0.35)";
    ctx.shadowBlur = 24;
    ctx.fillStyle = "#020617";
    ctx.fillRect(ix - 4, pad - 4, dw + 8, dh + 8);
    ctx.shadowBlur = 0;
    ctx.drawImage(img, ix, pad, dw, dh);

    const fy = pad + dh + gap;
    ctx.fillStyle = "rgba(15, 23, 42, 0.94)";
    ctx.fillRect(0, fy, W, H - fy);
    ctx.strokeStyle = "rgba(244, 114, 182, 0.35)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(pad, fy + 6);
    ctx.lineTo(W - pad, fy + 6);
    ctx.stroke();

    let ty = fy + 36;
    ctx.fillStyle = "#f1f5f9";
    ctx.font = "600 26px system-ui, 'Segoe UI', sans-serif";
    for (const line of captionLines.slice(0, 3)) {
      if (!line) continue;
      ctx.fillText(String(line).slice(0, 48), pad, ty);
      ty += 34;
    }

    if (promptSnippet) {
      ctx.fillStyle = "#94a3b8";
      ctx.font = "400 18px system-ui, 'Segoe UI', sans-serif";
      ty = drawWrappedLines(ctx, promptSnippet, pad, ty + 8, W - pad * 2 - 200, 24, 2);
    }

    ctx.fillStyle = "rgba(244, 114, 182, 0.85)";
    ctx.font = "500 15px system-ui, sans-serif";
    ctx.fillText("SD 动漫风格 · 本地实验室", pad, H - 26);

    const qrLink = `${window.location.origin}/sd`;
    const qrImg = await fetchQrImage(qrLink);
    if (qrImg) {
      const qs = 150;
      ctx.fillStyle = "rgba(255,255,255,0.06)";
      ctx.fillRect(W - pad - qs - 8, fy + 24, qs + 8, qs + 8);
      ctx.drawImage(qrImg, W - pad - qs, fy + 28, qs, qs);
      ctx.fillStyle = "#64748b";
      ctx.font = "11px system-ui, sans-serif";
      ctx.fillText("扫码打开 SD 页", W - pad - qs, fy + qs + 44);
    }

    canvas.toBlob(
      (blob) => {
        if (!blob) {
          alert("导出失败");
          return;
        }
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `sd-share-${id.slice(0, 8)}.png`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 4000);
      },
      "image/png",
      0.95
    );
  }

  global.buildSdShareCard = buildSdShareCard;
})(typeof window !== "undefined" ? window : globalThis);

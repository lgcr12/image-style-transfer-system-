(function () {
  function pollDelayMs() {
    return document.hidden ? 2400 : 700;
  }

  /**
   * 将图片最长边限制在 maxEdge 以内；已更小则原样返回。
   * PNG 输出 PNG，其余默认 JPEG，失败时返回原 File。
   */
  function downscaleImageFile(file, maxEdge) {
    if (!file || !file.type.startsWith("image/") || !maxEdge || maxEdge < 32) {
      return Promise.resolve(file);
    }
    const url = URL.createObjectURL(file);
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => {
        try {
          const w = img.naturalWidth;
          const h = img.naturalHeight;
          const max = Math.max(w, h);
          if (!w || !h || max <= maxEdge) {
            URL.revokeObjectURL(url);
            resolve(file);
            return;
          }
          const scale = maxEdge / max;
          const tw = Math.max(1, Math.round(w * scale));
          const th = Math.max(1, Math.round(h * scale));
          const canvas = document.createElement("canvas");
          canvas.width = tw;
          canvas.height = th;
          const ctx = canvas.getContext("2d");
          if (!ctx) {
            URL.revokeObjectURL(url);
            resolve(file);
            return;
          }
          ctx.drawImage(img, 0, 0, tw, th);
          const usePng = file.type === "image/png";
          const outMime = usePng ? "image/png" : "image/jpeg";
          const quality = usePng ? undefined : 0.92;
          canvas.toBlob(
            (blob) => {
              URL.revokeObjectURL(url);
              if (!blob) {
                resolve(file);
                return;
              }
              const ext = usePng ? ".png" : ".jpg";
              const base = file.name.replace(/\.[^.]+$/, "") || "image";
              resolve(new File([blob], `${base}_resized${ext}`, { type: outMime }));
            },
            outMime,
            quality
          );
        } catch (_) {
          URL.revokeObjectURL(url);
          resolve(file);
        }
      };
      img.onerror = () => {
        URL.revokeObjectURL(url);
        resolve(file);
      };
      img.src = url;
    });
  }

  window.ClientHelpers = { pollDelayMs, downscaleImageFile };
})();

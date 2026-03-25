from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageOps, ImageDraw

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore


def export_nine_grid(images: Iterable[Path], out_path: Path, cell_size: tuple[int, int] = (384, 384)) -> Path:
    ims = [Image.open(p).convert("RGB") for p in images]
    if not ims:
        raise ValueError("没有可用图片")
    while len(ims) < 9:
        ims.append(ims[-1].copy())
    ims = ims[:9]
    w, h = cell_size
    canvas = Image.new("RGB", (w * 3, h * 3), (245, 247, 250))
    for i, im in enumerate(ims):
        fitted = ImageOps.fit(im, (w, h), method=Image.Resampling.LANCZOS)
        x = (i % 3) * w
        y = (i // 3) * h
        canvas.paste(fitted, (x, y))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, format="PNG")
    return out_path


def export_transition_video(
    before: Path,
    after: Path,
    out_path: Path,
    fps: int = 24,
    seconds: float = 3.0,
    hold_before_s: float = 0.8,
    hold_after_s: float = 1.6,
) -> Path:
    a = Image.open(before).convert("RGB")
    b = Image.open(after).convert("RGB")
    if a.size != b.size:
        b = ImageOps.fit(b, a.size, method=Image.Resampling.LANCZOS)
    frames = []
    n = max(24, int(fps * seconds))
    hold_before_n = max(1, int(fps * hold_before_s))
    hold_after_n = max(1, int(fps * hold_after_s))
    arr_a = np.array(a, dtype=np.float32)
    arr_b = np.array(b, dtype=np.float32)
    for _ in range(hold_before_n):
        frames.append(arr_a.astype(np.uint8))
    for i in range(n):
        t = i / float(max(1, n - 1))
        arr = arr_a * (1.0 - t) + arr_b * t
        frames.append(arr.astype(np.uint8))
    for _ in range(hold_after_n):
        frames.append(arr_b.astype(np.uint8))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if cv2 is not None:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        vw = cv2.VideoWriter(str(out_path), fourcc, float(fps), a.size)
        for fr in frames:
            vw.write(cv2.cvtColor(fr, cv2.COLOR_RGB2BGR))
        vw.release()
    else:
        gif_path = out_path.with_suffix(".gif")
        Image.fromarray(frames[0]).save(
            gif_path,
            save_all=True,
            append_images=[Image.fromarray(x) for x in frames[1:]],
            duration=max(1, int(1000 / fps)),
            loop=0,
        )
        return gif_path
    return out_path


def export_compare_batch(compare_pairs: Iterable[tuple[Path, Path]], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_paths: list[Path] = []
    for i, (before, after) in enumerate(compare_pairs, start=1):
        a = Image.open(before).convert("RGB")
        b = Image.open(after).convert("RGB")
        if a.height != b.height:
            b = b.resize((int(b.width * a.height / b.height), a.height), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (a.width + b.width + 8, a.height), (248, 249, 252))
        canvas.paste(a, (0, 0))
        canvas.paste(b, (a.width + 8, 0))
        draw = ImageDraw.Draw(canvas)
        draw.text((10, 8), "Before", fill=(255, 255, 255))
        draw.text((a.width + 16, 8), "After", fill=(255, 255, 255))
        p = out_dir / f"compare_{i:03d}.png"
        canvas.save(p, format="PNG")
        out_paths.append(p)
    return out_paths

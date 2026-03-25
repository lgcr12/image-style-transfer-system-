from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore


@dataclass
class AnalyzeResult:
    portrait_score: float
    scene_score: float
    anime_score: float
    style_suggestion: str
    weight_range: tuple[float, float]
    recommended: dict[str, float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "portrait_score": round(self.portrait_score, 3),
            "scene_score": round(self.scene_score, 3),
            "anime_score": round(self.anime_score, 3),
            "style_suggestion": self.style_suggestion,
            "weight_range": [self.weight_range[0], self.weight_range[1]],
            "recommended": self.recommended,
        }


def _face_score(gray: np.ndarray) -> float:
    if cv2 is None:
        return 0.0
    try:
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(40, 40))
        if len(faces) == 0:
            return 0.0
        # 脸面积占比越高，人像概率越高。
        h, w = gray.shape
        max_area = max((fw * fh for (_, _, fw, fh) in faces), default=0)
        return float(min(1.0, max_area / float(max(1, h * w)) * 8.0))
    except Exception:
        return 0.0


def _anime_score(img_rgb: np.ndarray) -> float:
    # 基于边缘密度 + 饱和度估计二次元程度（轻量启发式）。
    hsv = np.array(Image.fromarray(img_rgb).convert("HSV"), dtype=np.float32)
    sat = hsv[..., 1] / 255.0
    sat_mean = float(np.mean(sat))
    gray = np.array(Image.fromarray(img_rgb).convert("L"), dtype=np.uint8)
    if cv2 is not None:
        edges = cv2.Canny(gray, 80, 160)
        edge_ratio = float(np.mean(edges > 0))
    else:
        gx = np.abs(np.diff(gray.astype(np.float32), axis=1)).mean()
        gy = np.abs(np.diff(gray.astype(np.float32), axis=0)).mean()
        edge_ratio = float(min(1.0, (gx + gy) / 128.0))
    return float(np.clip(0.55 * sat_mean + 0.45 * min(1.0, edge_ratio * 5.0), 0.0, 1.0))


def analyze_image(input_path: Path) -> AnalyzeResult:
    im = Image.open(input_path).convert("RGB")
    arr = np.array(im, dtype=np.uint8)
    gray = np.array(im.convert("L"), dtype=np.uint8)

    portrait = _face_score(gray)
    anime = _anime_score(arr)
    scene = float(np.clip(1.0 - portrait * 0.8, 0.0, 1.0))

    if portrait >= 0.45 and anime >= 0.45:
        suggestion = "shinkai_char"
        w_range = (0.7, 0.9)
        rec = {"lora_weight": 0.8, "denoise": 0.55, "steps": 28.0, "guidance": 7.0}
    elif scene >= 0.55 and anime >= 0.35:
        suggestion = "shinkai_view"
        w_range = (0.6, 0.8)
        rec = {"lora_weight": 0.7, "denoise": 0.5, "steps": 30.0, "guidance": 7.0}
    else:
        suggestion = "shinkai_mix"
        w_range = (0.6, 0.8)
        rec = {"lora_weight": 0.75, "denoise": 0.58, "steps": 32.0, "guidance": 7.5}

    return AnalyzeResult(
        portrait_score=portrait,
        scene_score=scene,
        anime_score=anime,
        style_suggestion=suggestion,
        weight_range=w_range,
        recommended=rec,
    )

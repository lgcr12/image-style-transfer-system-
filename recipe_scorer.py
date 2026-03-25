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
class RecipeScore:
    clarity: float
    face_integrity: float
    noise: float
    total_score: float
    recommendation: dict[str, float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "clarity": round(self.clarity, 3),
            "face_integrity": round(self.face_integrity, 3),
            "noise": round(self.noise, 3),
            "total_score": round(self.total_score, 3),
            "recommendation": self.recommendation,
        }


def _clarity(gray: np.ndarray) -> float:
    if cv2 is not None:
        v = cv2.Laplacian(gray, cv2.CV_64F).var()
    else:
        gx = np.diff(gray.astype(np.float32), axis=1)
        gy = np.diff(gray.astype(np.float32), axis=0)
        v = float(np.var(gx) + np.var(gy))
    return float(np.clip(v / 500.0, 0.0, 1.0))


def _face_integrity(gray: np.ndarray) -> float:
    if cv2 is None:
        return 0.5
    try:
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(40, 40))
        if len(faces) == 0:
            return 0.35
        h, w = gray.shape
        areas = [fw * fh for (_, _, fw, fh) in faces]
        best = max(areas) / float(max(1, h * w))
        return float(np.clip(best * 10.0, 0.5, 1.0))
    except Exception:
        return 0.5


def _noise(gray: np.ndarray) -> float:
    smooth = gray.astype(np.float32)
    if cv2 is not None:
        blur = cv2.GaussianBlur(smooth, (5, 5), 0)
    else:
        blur = (smooth + np.roll(smooth, 1, 0) + np.roll(smooth, -1, 0)) / 3.0
    high = smooth - blur
    # 归一化到 0-1，值越大噪点越重
    return float(np.clip(np.std(high) / 30.0, 0.0, 1.0))


def score_image(image_path: Path) -> RecipeScore:
    gray = np.array(Image.open(image_path).convert("L"), dtype=np.uint8)
    clarity = _clarity(gray)
    face = _face_integrity(gray)
    noise = _noise(gray)
    total = 0.5 * clarity + 0.35 * face + 0.15 * (1.0 - noise)
    recommendation = recommend_next_recipe(clarity=clarity, face_integrity=face, noise=noise)
    return RecipeScore(clarity=clarity, face_integrity=face, noise=noise, total_score=float(total), recommendation=recommendation)


def recommend_next_recipe(*, clarity: float, face_integrity: float, noise: float) -> dict[str, float]:
    denoise = 0.55
    cfg = 7.0
    steps = 28.0
    if noise > 0.65:
        denoise = 0.46
        cfg = 6.2
        steps = 30.0
    elif clarity < 0.4:
        denoise = 0.62
        cfg = 7.2
        steps = 30.0
    elif face_integrity < 0.45:
        denoise = 0.5
        cfg = 6.8
        steps = 32.0
    return {"denoise": denoise, "guidance": cfg, "steps": steps}

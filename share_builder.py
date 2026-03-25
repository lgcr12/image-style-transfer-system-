from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageOps

try:
    import qrcode  # type: ignore
except Exception:  # pragma: no cover
    qrcode = None  # type: ignore


TEMPLATES = {
    "xiaohongshu": (1080, 1440),  # 3:4
    "douyin": (1080, 1920),       # 9:16
}


def build_copywriting(params: dict[str, Any]) -> str:
    return (
        "风格转换结果已生成\n"
        f"风格: {params.get('style', 'unknown')}\n"
        f"参数: steps={params.get('steps')} / cfg={params.get('guidance')} / denoise={params.get('denoise')}\n"
        f"LoRA权重: {params.get('lora_weight', 'auto')}\n"
        f"评分: {params.get('score', 'n/a')}\n"
    )


def build_share_card(image_path: Path, out_path: Path, params: dict[str, Any], result_url: str | None = None) -> Path:
    im = Image.open(image_path).convert("RGB")
    panel_h = 280
    canvas = Image.new("RGB", (im.width, im.height + panel_h), (20, 24, 31))
    canvas.paste(im, (0, 0))
    draw = ImageDraw.Draw(canvas)
    y = im.height + 20
    draw.text((24, y), f"Style: {params.get('style', 'unknown')}", fill=(240, 244, 248))
    draw.text((24, y + 40), f"Steps: {params.get('steps')}  CFG: {params.get('guidance')}", fill=(240, 244, 248))
    draw.text((24, y + 80), f"Denoise: {params.get('denoise')}  Score: {params.get('score', 'n/a')}", fill=(240, 244, 248))

    if result_url and qrcode is not None:
        qr = qrcode.QRCode(border=1, box_size=4)
        qr.add_data(result_url)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        qr_img = ImageOps.fit(qr_img, (140, 140), method=Image.Resampling.NEAREST)
        canvas.paste(qr_img, (canvas.width - 170, y))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, format="PNG")
    return out_path


def build_social_cover(image_path: Path, out_path: Path, template: str = "xiaohongshu") -> Path:
    if template not in TEMPLATES:
        raise ValueError(f"未知模板: {template}")
    w, h = TEMPLATES[template]
    im = Image.open(image_path).convert("RGB")
    cover = ImageOps.fit(im, (w, h), method=Image.Resampling.LANCZOS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cover.save(out_path, format="PNG")
    return out_path

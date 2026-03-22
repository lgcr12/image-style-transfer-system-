from __future__ import annotations

import os

import torch
from diffusers import StableDiffusionImg2ImgPipeline


def main() -> None:
    # 使用国内镜像 + 拉长超时，避免 WinError 10060
    os.environ["HF_ENDPOINT"] = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ["HF_HUB_HTTP_TIMEOUT"] = os.environ.get("HF_HUB_HTTP_TIMEOUT", "600")
    os.environ["HF_HUB_ETAG_TIMEOUT"] = os.environ.get("HF_HUB_ETAG_TIMEOUT", "600")
    os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = os.environ.get(
        "HF_HUB_DOWNLOAD_TIMEOUT", "600"
    )

    out_dir = r"E:\models\sd_base_v1_5"
    os.makedirs(out_dir, exist_ok=True)

    pipe = StableDiffusionImg2ImgPipeline.from_pretrained(
        "runwayml/stable-diffusion-v1-5",
        torch_dtype=torch.float16,
        safety_checker=None,
    )
    pipe.save_pretrained(out_dir)


if __name__ == "__main__":
    main()


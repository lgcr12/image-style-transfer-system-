import json
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Callable

import paramiko


DEFAULT_COMFY_ROOT = "/root/autodl-tmp/ComfyUI"

DEFAULT_BASE_MODELS = {
    "default": "v1-5-pruned-emaonly.safetensors",
    "sd15": "v1-5-pruned-emaonly.safetensors",
    "v1_5": "v1-5-pruned-emaonly.safetensors",
    "v1-5": "v1-5-pruned-emaonly.safetensors",
    "style_bound": "v1-5-pruned-emaonly.safetensors",
    "meinamix_v12": "MeinaMixV12.safetensors",
    "leosam_aiart_sdxl_v2": "leosam_aiart_sdxl_v2.safetensors",
    "animagine_xl_3_1": "leosam_aiart_sdxl_v2.safetensors",
}

DEFAULT_LORAS = {
    "default": "watercolor_ink_v2.safetensors",
    "lora1": "watercolor_ink_v2.safetensors",
    "watercolor": "watercolor_ink_v2.safetensors",
    "watercolor_ink": "watercolor_ink_v2.safetensors",
    "sd_-": "pixel_cute_anime.safetensors",
    "lora_v1_0_3268f4": "japanese_old_manga_v1.safetensors",
    "lora_v1_0_5e98cd": "japanese_old_manga_v1.safetensors",
}

DEFAULT_STYLE_PROMPTS = {
    "default": "watercolor ink wash, soft splashes, layered anime illustration",
    "lora1": "watercolor ink wash, soft splashes",
    "lora2": "midjourney anime aesthetic, ornate colorful details",
    "kyoto": "kyoto animation style, gentle lighting, clean anime lineart",
    "shinkai_char": "makoto shinkai inspired character art, luminous eyes",
    "shinkai_view": "makoto shinkai inspired scenery, cinematic light, sky glow",
    "ukiyo": "ukiyo-e inspired composition, traditional japanese print texture",
    "shinkai_mix": "makoto shinkai cinematic anime, traditional ukiyo-e texture",
    "jojo": "dramatic jojo inspired pose, bold ink shadows, fashion anime",
    "xl_-lora_v1": "cute anime avatar, big head portrait, clean white background",
    "lora_v1_0_3268f4": "classic japanese manga style, expressive line art",
    "sd_-": "cute anime pixel art, crisp pixel details",
}

DEFAULT_LORA_STRENGTH = {
    "default": 0.65,
    "lora1": 0.75,
    "watercolor": 0.75,
    "watercolor_ink": 0.75,
    "sd_-": 0.8,
    "lora_v1_0_3268f4": 0.9,
    "lora_v1_0_5e98cd": 0.9,
}


def _read_config(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return {
        "host": data["host"],
        "port": int(data.get("port") or 22),
        "username": data.get("username") or "root",
        "password": data["password"],
        "comfy_root": data.get("comfy_root") or DEFAULT_COMFY_ROOT,
    }


def _connect(config: dict):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        config["host"],
        port=int(config.get("port") or 22),
        username=config.get("username") or "root",
        password=config["password"],
        timeout=25,
        banner_timeout=30,
        auth_timeout=30,
    )
    client.get_transport().set_keepalive(15)
    return client


def _remote_python_json(client, code: str, timeout: int = 300) -> dict:
    cmd = f"/root/miniconda3/bin/python - <<'PY'\n{code}\nPY"
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    if err and not out:
        raise RuntimeError(err)
    try:
        return json.loads(out.splitlines()[-1])
    except Exception as exc:
        raise RuntimeError(f"Invalid remote response: {out[-1000:]} {err[-1000:]}") from exc


def load_cloud_mappings(mapping_path: Path | None = None) -> dict:
    data = {
        "base_models": dict(DEFAULT_BASE_MODELS),
        "loras": dict(DEFAULT_LORAS),
        "style_prompts": dict(DEFAULT_STYLE_PROMPTS),
        "lora_strength": dict(DEFAULT_LORA_STRENGTH),
    }
    if mapping_path and mapping_path.is_file():
        try:
            custom = json.loads(mapping_path.read_text(encoding="utf-8-sig"))
        except Exception:
            custom = {}
        if isinstance(custom, dict):
            for key in ("base_models", "loras", "style_prompts", "lora_strength"):
                value = custom.get(key)
                if isinstance(value, dict):
                    data[key].update({str(k): v for k, v in value.items() if v not in (None, "")})
    return data


def get_cloud_model_capabilities(mapping_path: Path | None = None) -> dict:
    mappings = load_cloud_mappings(mapping_path)
    return {
        **mappings,
        "uploaded_checkpoints": sorted(set(str(v) for v in mappings["base_models"].values() if v)),
        "uploaded_loras": sorted(set(str(v) for v in mappings["loras"].values() if v)),
    }


def ensure_comfyui(config_path: Path) -> dict:
    config = _read_config(config_path)
    comfy_root = config["comfy_root"]
    client = _connect(config)
    try:
        cmd = f"""
set -e
cd {comfy_root}
if curl -s --max-time 3 http://127.0.0.1:8188/system_stats >/tmp/comfy_stats.json; then
  echo already
else
  if [ -f comfyui.pid ] && kill -0 $(cat comfyui.pid) 2>/dev/null; then kill $(cat comfyui.pid) || true; sleep 2; fi
  nohup /root/miniconda3/bin/python main.py --listen 0.0.0.0 --port 8188 > comfyui.log 2>&1 &
  echo $! > comfyui.pid
fi
if ! /root/miniconda3/bin/python - <<'PY'
import sys, time, urllib.request
for _ in range(90):
    try:
        urllib.request.urlopen('http://127.0.0.1:8188/system_stats', timeout=3).read()
        sys.exit(0)
    except Exception:
        time.sleep(1)
print('ComfyUI did not become ready within 90 seconds', file=sys.stderr)
sys.exit(1)
PY
then
  tail -n 120 comfyui.log >&2 || true
  exit 1
fi
/root/miniconda3/bin/python - <<'PY'
import json, urllib.request
data=json.load(urllib.request.urlopen('http://127.0.0.1:8188/system_stats', timeout=10))
print(json.dumps({{"ok": True, "devices": data.get("devices", [])}}, ensure_ascii=False))
PY
"""
        stdin, stdout, stderr = client.exec_command(cmd, timeout=130)
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        if err and not out:
            raise RuntimeError(err)
        return json.loads(out.splitlines()[-1])
    finally:
        client.close()


def _resolve_cloud_names(sd_style_name: str, base_model_key: str, mappings: dict) -> tuple[str, str | None]:
    base_models = mappings["base_models"]
    loras = mappings["loras"]
    base = base_models.get(base_model_key) or base_models.get("default")
    if base_model_key == "leosam_aiart_sdxl_v2" or sd_style_name in {"sd_-", "xl_-lora_v1"}:
        base = base_models.get("leosam_aiart_sdxl_v2") or base
    if base_model_key == "meinamix_v12":
        base = base_models.get("meinamix_v12") or base
    lora = loras.get(sd_style_name)
    return str(base), str(lora) if lora else None


def run_cloud_img2img(
    *,
    config_path: Path,
    mapping_path: Path | None = None,
    sd_style_name: str,
    base_model_key: str,
    content_path: Path,
    output_path: Path,
    denoising_strength: float,
    guidance_scale: float,
    num_inference_steps: int,
    prompt: str,
    negative_prompt: str,
    quick_mode: bool,
    progress_callback: Callable[[int], None] | None = None,
    phase_callback: Callable[[str, str | None], None] | None = None,
) -> Path:
    def progress(value: int) -> None:
        if progress_callback:
            progress_callback(value)

    def phase(name: str, detail: str | None = None) -> None:
        if phase_callback:
            phase_callback(name, detail)

    config = _read_config(config_path)
    comfy_root = config["comfy_root"]
    mappings = load_cloud_mappings(mapping_path)
    ckpt_name, lora_name = _resolve_cloud_names(sd_style_name, base_model_key, mappings)
    style_prompt = str(mappings["style_prompts"].get(sd_style_name) or "")
    lora_strength = float(mappings["lora_strength"].get(sd_style_name) or 0.75)
    steps = int(num_inference_steps)
    if quick_mode:
        steps = min(steps, 18)
    is_xl = "xl" in ckpt_name.lower() or "sdxl" in ckpt_name.lower()
    width = 768 if is_xl else 512
    height = 768 if is_xl else 512

    client = _connect(config)
    try:
        phase("uploading", "上传输入图到云端")
        progress(5)
        remote_input = f"{comfy_root}/input/codex_{uuid.uuid4().hex}.png"
        sftp = client.open_sftp()
        try:
            sftp.put(str(content_path), remote_input)
        finally:
            sftp.close()

        phase("running", "云端 ComfyUI 生成中")
        progress(10)
        workflow_code = json.dumps(
            {
                "comfy_root": comfy_root,
                "ckpt_name": ckpt_name,
                "lora_name": lora_name,
                "remote_input": remote_input,
                "prompt": ", ".join([x for x in [prompt, style_prompt, "masterpiece, best quality, anime style"] if x]),
                "negative_prompt": negative_prompt or "low quality, blurry, watermark, bad anatomy",
                "denoise": float(denoising_strength),
                "cfg": float(guidance_scale),
                "steps": steps,
                "width": width,
                "height": height,
                "lora_strength": lora_strength,
            },
            ensure_ascii=False,
        )
        code = f"""
import json, urllib.error, urllib.request, time, uuid
cfg = json.loads({workflow_code!r})
client_id = str(uuid.uuid4())
model_node = ["1", 0]
clip_node = ["1", 1]
prompt = {{
 "1": {{"class_type": "CheckpointLoaderSimple", "inputs": {{"ckpt_name": cfg["ckpt_name"]}}}},
 "2": {{"class_type": "LoadImage", "inputs": {{"image": cfg["remote_input"].split('/input/', 1)[-1]}}}},
 "3": {{"class_type": "VAEEncode", "inputs": {{"pixels": ["2", 0], "vae": ["1", 2]}}}},
 "4": {{"class_type": "CLIPTextEncode", "inputs": {{"clip": clip_node, "text": cfg["prompt"]}}}},
 "5": {{"class_type": "CLIPTextEncode", "inputs": {{"clip": clip_node, "text": cfg["negative_prompt"]}}}},
 "6": {{"class_type": "KSampler", "inputs": {{"model": model_node, "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["3", 0], "seed": int(time.time()*1000) % 2147483647, "steps": cfg["steps"], "cfg": cfg["cfg"], "sampler_name": "euler", "scheduler": "normal", "denoise": cfg["denoise"]}}}},
 "7": {{"class_type": "VAEDecode", "inputs": {{"samples": ["6", 0], "vae": ["1", 2]}}}},
 "8": {{"class_type": "SaveImage", "inputs": {{"images": ["7", 0], "filename_prefix": "codex_cloud"}}}},
}}
if cfg.get("lora_name"):
    prompt["9"] = {{"class_type": "LoraLoader", "inputs": {{"model": ["1", 0], "clip": ["1", 1], "lora_name": cfg["lora_name"], "strength_model": cfg["lora_strength"], "strength_clip": cfg["lora_strength"]}}}}
    prompt["4"]["inputs"]["clip"] = ["9", 1]
    prompt["5"]["inputs"]["clip"] = ["9", 1]
    prompt["6"]["inputs"]["model"] = ["9", 0]
req=urllib.request.Request('http://127.0.0.1:8188/prompt', data=json.dumps({{"prompt": prompt, "client_id": client_id}}).encode(), headers={{'Content-Type':'application/json'}})
try:
    resp=json.load(urllib.request.urlopen(req, timeout=30))
except urllib.error.HTTPError as exc:
    body=exc.read().decode('utf-8', errors='replace')
    raise RuntimeError(f"ComfyUI HTTP {{exc.code}}: {{body}}") from exc
pid=resp["prompt_id"]
for _ in range(600):
    hist=json.load(urllib.request.urlopen(f'http://127.0.0.1:8188/history/{{pid}}', timeout=30))
    if pid in hist:
        outputs=hist[pid].get("outputs", {{}})
        images=outputs.get("8", {{}}).get("images", [])
        if not images:
            raise RuntimeError("ComfyUI finished without output image")
        img=images[0]
        print(json.dumps({{"ok": True, "prompt_id": pid, "file": cfg["comfy_root"] + "/output/" + img["filename"]}}, ensure_ascii=False))
        break
    time.sleep(1)
else:
    raise TimeoutError("ComfyUI generation timeout")
"""
        result = _remote_python_json(client, code, timeout=900)
        remote_output = result["file"]
        phase("downloading", "下载云端结果")
        progress(92)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sftp = client.open_sftp()
        try:
            sftp.get(remote_output, str(output_path))
        finally:
            sftp.close()
        progress(100)
        return output_path
    finally:
        client.close()

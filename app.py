import io
import uuid
import traceback
import re
import sys
import json
import asyncio
import time
import os
import gzip
import glob
import socket
import threading
import urllib.parse
import urllib.request
from html import escape
from pathlib import Path
from typing import Dict

import onnxruntime as ort
from safetensors import safe_open
from fastapi import FastAPI, UploadFile, File, Form, Query
from fastapi import HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request

from PIL import Image
import paramiko

from style_transfer import load_model, run_style_transfer, AVAILABLE_MODELS
import style_transfer as style_transfer_module
from sd_style_transfer import (
    run_sd_style_transfer,
    run_sd_style_transfer_candidates,
    warmup_pipeline,
    get_warmup_status,
    get_sd_style_config,
    get_sd_base_models,
    get_active_base_model_key,
    AVAILABLE_SD_STYLES,
)
import sd_style_transfer as sd_style_transfer_module
from image_analyzer import analyze_image
from recipe_scorer import score_image
from job_queue import JobQueue, QueueJob
from exporter import export_compare_batch, export_nine_grid, export_transition_video
from share_builder import build_share_card, build_copywriting, build_social_cover
from job_store import JobStore
from cloud_comfyui import (
    DEFAULT_COMFY_ROOT,
    ensure_comfyui,
    get_cloud_model_capabilities,
    load_cloud_mappings,
    run_cloud_img2img,
)

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
RESULT_DIR = BASE_DIR / "results"
META_DIR = RESULT_DIR / "meta"
EXPORT_DIR = RESULT_DIR / "exports"
SHARE_DIR = RESULT_DIR / "share"
IMPORTED_MODEL_DIR = BASE_DIR / "imported_models"

UPLOAD_DIR.mkdir(exist_ok=True)
RESULT_DIR.mkdir(exist_ok=True)
META_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR.mkdir(parents=True, exist_ok=True)
SHARE_DIR.mkdir(parents=True, exist_ok=True)
IMPORTED_MODEL_DIR.mkdir(parents=True, exist_ok=True)
DB_DIR = BASE_DIR / "data"
DB_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI()

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

QWEATHER_KEY = os.getenv("QWEATHER_API_KEY", "")
QWEATHER_API_HOST = os.getenv("QWEATHER_API_HOST", "nq5egn2wpt.re.qweatherapi.com")
QWEATHER_LOCATION_ID = os.getenv("QWEATHER_LOCATION_ID", "101010100")
STYLE_MODEL_CONFIG_PATH = BASE_DIR / "config" / "style_models.json"
SD_STYLE_CONFIG_PATH = BASE_DIR / "config" / "sd_styles.json"
CLOUD_UPLOAD_CONFIG_PATH = DB_DIR / "cloud_upload_config.local.json"
CLOUD_COMFY_MAPPING_PATH = DB_DIR / "cloud_comfyui_mappings.local.json"
CLOUD_COMFY_ROOT = DEFAULT_COMFY_ROOT


def _find_file_by_size(base: Path, size: int, suffix: str = "*.safetensors") -> Path | None:
    for item in base.glob(suffix):
        try:
            if item.is_file() and item.stat().st_size == size:
                return item
        except OSError:
            continue
    return None


def _first_glob(base: Path, pattern: str) -> Path | None:
    hits = sorted(base.glob(pattern), key=lambda p: p.stat().st_size if p.is_file() else 0, reverse=True)
    return hits[0] if hits else None


def _cloud_upload_manifest() -> list[dict]:
    candidates: list[tuple[Path | None, str, str]] = [
        (
            BASE_DIR / "v1-5-pruned-emaonly.safetensors",
            f"{CLOUD_COMFY_ROOT}/models/checkpoints/v1-5-pruned-emaonly.safetensors",
            "SD 1.5 基础模型",
        ),
        (
            BASE_DIR / "MeinaMixV12.safetensors",
            f"{CLOUD_COMFY_ROOT}/models/checkpoints/MeinaMixV12.safetensors",
            "MeinaMix V12",
        ),
        (
            _find_file_by_size(IMPORTED_MODEL_DIR, 340782308),
            f"{CLOUD_COMFY_ROOT}/models/loras/pixel_cute_anime.safetensors",
            "像素动漫 LoRA",
        ),
        (
            _find_file_by_size(IMPORTED_MODEL_DIR, 151119112),
            f"{CLOUD_COMFY_ROOT}/models/loras/japanese_old_manga_v1.safetensors",
            "日本旧漫 LoRA",
        ),
        (
            _find_file_by_size(BASE_DIR, 151113728),
            f"{CLOUD_COMFY_ROOT}/models/loras/watercolor_ink_v2.safetensors",
            "水彩泼墨 LoRA",
        ),
        (
            _find_file_by_size(IMPORTED_MODEL_DIR, 202701676),
            f"{CLOUD_COMFY_ROOT}/models/loras/cute_anime_head_xl.safetensors",
            "可爱动漫大头像 XL LoRA",
        ),
        (
            BASE_DIR / "jojo.safetensors",
            f"{CLOUD_COMFY_ROOT}/models/loras/jojo.safetensors",
            "JoJo LoRA",
        ),
        (
            _find_file_by_size(BASE_DIR, 151111468),
            f"{CLOUD_COMFY_ROOT}/models/loras/baihua_midjourney_anime.safetensors",
            "百花缭乱 Midjourney LoRA",
        ),
        (
            BASE_DIR / "kyoto_anime.safetensors",
            f"{CLOUD_COMFY_ROOT}/models/loras/kyoto_anime.safetensors",
            "京阿尼 Kyoto LoRA",
        ),
        (
            BASE_DIR / "shinkai__Character_v1.0.safetensors",
            f"{CLOUD_COMFY_ROOT}/models/loras/shinkai_character_v1.safetensors",
            "新海诚 Character LoRA",
        ),
        (
            BASE_DIR / "shinkai_view_V1.0.safetensors",
            f"{CLOUD_COMFY_ROOT}/models/loras/shinkai_view_v1.safetensors",
            "新海诚 View LoRA",
        ),
        (
            BASE_DIR / "ukiyo.safetensors",
            f"{CLOUD_COMFY_ROOT}/models/loras/ukiyo.safetensors",
            "浮世绘 LoRA",
        ),
        (
            _find_file_by_size(BASE_DIR, 236117024),
            f"{CLOUD_COMFY_ROOT}/models/loras/ink_wash_v1.safetensors",
            "水墨 LoRA",
        ),
    ]
    leosam = _first_glob(IMPORTED_MODEL_DIR, "LEOSAM*.safetensors")
    if leosam:
        candidates.append(
            (
                leosam,
                f"{CLOUD_COMFY_ROOT}/models/checkpoints/leosam_aiart_sdxl_v2.safetensors",
                "LEOSAM AIArt SDXL",
            )
        )
    illustrious = _first_glob(IMPORTED_MODEL_DIR, "Illustrious-XL-v2.0.safetensors")
    if illustrious:
        candidates.append(
            (
                illustrious,
                f"{CLOUD_COMFY_ROOT}/models/checkpoints/Illustrious-XL-v2.0.safetensors",
                "Illustrious XL v2.0",
            )
        )

    try:
        sd_cfg = _read_json_file(SD_STYLE_CONFIG_PATH, {"styles": {}, "adapters": {}, "base_models": {}})
        for key, item in (sd_cfg.get("base_models") or {}).items():
            if not isinstance(item, dict) or item.get("disabled"):
                continue
            local_path = Path(str(item.get("path") or ""))
            if local_path.is_file():
                candidates.append(
                    (
                        local_path,
                        f"{CLOUD_COMFY_ROOT}/models/checkpoints/{local_path.name}",
                        f"基础模型：{item.get('label') or key}",
                    )
                )
        for key, item in (sd_cfg.get("adapters") or {}).items():
            if not isinstance(item, dict) or item.get("disabled"):
                continue
            local_path = Path(str(item.get("default_path") or ""))
            if local_path.is_file():
                candidates.append(
                    (
                        local_path,
                        f"{CLOUD_COMFY_ROOT}/models/loras/{local_path.name}",
                        f"LoRA：{key}",
                    )
                )
    except Exception:
        pass

    manifest = []
    seen_remote: set[str] = set()
    seen_local: set[str] = set()
    for local_path, remote_path, label in candidates:
        if not local_path or not local_path.is_file():
            continue
        local_key = str(local_path.resolve()).lower()
        if remote_path in seen_remote or local_key in seen_local:
            continue
        seen_remote.add(remote_path)
        seen_local.add(local_key)
        size = local_path.stat().st_size
        manifest.append(
            {
                "label": label,
                "local": str(local_path),
                "remote": remote_path,
                "part": f"{remote_path}.part",
                "size": size,
                "kind": "lora" if "/loras/" in remote_path else "checkpoint",
            }
        )
    return manifest


def _sync_cloud_mappings_from_sd_config() -> dict:
    mappings = load_cloud_mappings(CLOUD_COMFY_MAPPING_PATH)
    sd_cfg = _read_json_file(SD_STYLE_CONFIG_PATH, {"styles": {}, "adapters": {}, "base_models": {}})
    base_models = dict(mappings.get("base_models") or {})
    loras = dict(mappings.get("loras") or {})
    style_prompts = dict(mappings.get("style_prompts") or {})
    lora_strength = dict(mappings.get("lora_strength") or {})

    for key, item in (sd_cfg.get("base_models") or {}).items():
        if not isinstance(item, dict) or item.get("disabled"):
            continue
        local_path = Path(str(item.get("path") or ""))
        if local_path.is_file():
            base_models.setdefault(str(key), local_path.name)

    adapters = sd_cfg.get("adapters") or {}
    for style_key, style in (sd_cfg.get("styles") or {}).items():
        if not isinstance(style, dict) or style.get("disabled"):
            continue
        adapter_keys = [str(x) for x in (style.get("adapters") or []) if x]
        if adapter_keys:
            adapter = adapters.get(adapter_keys[0])
            if isinstance(adapter, dict):
                local_path = Path(str(adapter.get("default_path") or ""))
                if local_path.is_file():
                    loras.setdefault(str(style_key), local_path.name)
        if style.get("prompt"):
            style_prompts[str(style_key)] = str(style.get("prompt"))
        weights = style.get("weights") or []
        if weights:
            try:
                lora_strength[str(style_key)] = float(weights[0])
            except (TypeError, ValueError):
                pass

    clean = {
        "base_models": base_models,
        "loras": loras,
        "style_prompts": style_prompts,
        "lora_strength": lora_strength,
    }
    CLOUD_COMFY_MAPPING_PATH.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    return clean


def _read_cloud_upload_config() -> dict:
    config = {
        "host": os.getenv("CLOUD_SSH_HOST", ""),
        "port": int(os.getenv("CLOUD_SSH_PORT", "22") or "22"),
        "username": os.getenv("CLOUD_SSH_USER", "root"),
        "password": os.getenv("CLOUD_SSH_PASSWORD", ""),
        "comfy_root": os.getenv("CLOUD_COMFY_ROOT", CLOUD_COMFY_ROOT),
    }
    try:
        if CLOUD_UPLOAD_CONFIG_PATH.is_file():
            local_cfg = json.loads(CLOUD_UPLOAD_CONFIG_PATH.read_text(encoding="utf-8-sig"))
            if isinstance(local_cfg, dict):
                config.update({k: v for k, v in local_cfg.items() if v not in (None, "")})
                config["port"] = int(config.get("port") or 22)
    except Exception:
        pass
    return config


class CloudUploadManager:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.state: dict = {
            "running": False,
            "error": "",
            "message": "等待开始",
            "current_remote": "",
            "current_label": "",
            "current_sent": 0,
            "current_total": 0,
            "overall_sent": 0,
            "overall_total": 0,
            "speed_bps": 0,
            "started_at": None,
            "updated_at": None,
            "logs": [],
        }

    def _set(self, **kwargs) -> None:
        with self.lock:
            self.state.update(kwargs)
            self.state["updated_at"] = time.time()

    def _log(self, text: str) -> None:
        with self.lock:
            logs = list(self.state.get("logs") or [])
            logs.append({"time": time.time(), "text": text})
            self.state["logs"] = logs[-80:]
            self.state["message"] = text
            self.state["updated_at"] = time.time()

    def snapshot(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.state, ensure_ascii=False))

    def start(self) -> bool:
        with self.lock:
            if self.thread and self.thread.is_alive():
                return False
            self.stop_event.clear()
            self.state.update(
                {
                    "running": True,
                    "error": "",
                    "message": "准备连接远端",
                    "started_at": time.time(),
                    "updated_at": time.time(),
                    "speed_bps": 0,
                    "logs": [],
                }
            )
            self.thread = threading.Thread(target=self._worker, daemon=True)
            self.thread.start()
            return True

    def stop(self) -> None:
        self.stop_event.set()
        self._log("收到停止请求，当前块写完后暂停")

    def _connect(self):
        cfg = _read_cloud_upload_config()
        if not cfg.get("host") or not cfg.get("password"):
            raise RuntimeError("缺少云端 SSH 配置，请设置 data/cloud_upload_config.local.json")
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            str(cfg["host"]),
            port=int(cfg.get("port") or 22),
            username=str(cfg.get("username") or "root"),
            password=str(cfg["password"]),
            timeout=25,
            banner_timeout=30,
            auth_timeout=30,
        )
        client.get_transport().set_keepalive(15)
        return client, client.open_sftp()

    @staticmethod
    def _remote_size(sftp, path: str) -> int | None:
        try:
            return int(sftp.stat(path).st_size)
        except FileNotFoundError:
            return None

    def _worker(self) -> None:
        try:
            manifest = _cloud_upload_manifest()
            total = sum(int(item["size"]) for item in manifest)
            self._set(overall_total=total, overall_sent=0)
            self._log(f"上传队列 {len(manifest)} 个文件")

            client, sftp = self._connect()
            try:
                client.exec_command(
                    f"mkdir -p {CLOUD_COMFY_ROOT}/models/checkpoints {CLOUD_COMFY_ROOT}/models/loras"
                )[1].read()
            finally:
                sftp.close()
                client.close()

            completed_before = 0
            for item in manifest:
                if self.stop_event.is_set():
                    break
                local = Path(str(item["local"]))
                remote = str(item["remote"])
                part = str(item["part"])
                size = int(item["size"])
                label = str(item["label"])

                while not self.stop_event.is_set():
                    client, sftp = self._connect()
                    try:
                        done = self._remote_size(sftp, remote)
                        if done == size:
                            completed_before += size
                            self._set(overall_sent=completed_before)
                            self._log(f"已存在：{label}")
                            break
                        part_size = self._remote_size(sftp, part) or 0
                        if part_size > size:
                            sftp.remove(part)
                            part_size = 0
                        self._set(
                            current_remote=remote,
                            current_label=label,
                            current_sent=part_size,
                            current_total=size,
                            overall_sent=completed_before + part_size,
                        )
                        self._log(f"续传：{label}")
                        with local.open("rb") as local_file:
                            local_file.seek(part_size)
                            remote_file = sftp.open(part, "ab")
                            remote_file.set_pipelined(False)
                            sent = part_size
                            last_time = time.time()
                            last_sent = sent
                            try:
                                while sent < size and not self.stop_event.is_set():
                                    chunk = local_file.read(512 * 1024)
                                    if not chunk:
                                        break
                                    remote_file.write(chunk)
                                    sent += len(chunk)
                                    now = time.time()
                                    if now - last_time >= 1.0 or sent >= size:
                                        speed = (sent - last_sent) / max(now - last_time, 0.001)
                                        self._set(
                                            current_sent=sent,
                                            current_total=size,
                                            overall_sent=completed_before + sent,
                                            speed_bps=speed,
                                        )
                                        last_time = now
                                        last_sent = sent
                            finally:
                                remote_file.close()
                        if sent >= size:
                            existing = self._remote_size(sftp, remote)
                            if existing is not None and existing != size:
                                sftp.remove(remote)
                            sftp.rename(part, remote)
                            completed_before += size
                            self._set(overall_sent=completed_before)
                            self._log(f"完成：{label}")
                            break
                    except (EOFError, OSError, socket.error, paramiko.SSHException) as exc:
                        self._log(f"连接中断，5 秒后重试：{type(exc).__name__}")
                        time.sleep(5)
                    finally:
                        try:
                            sftp.close()
                            client.close()
                        except Exception:
                            pass

            self._set(running=False, speed_bps=0)
            self._log("上传已暂停" if self.stop_event.is_set() else "上传队列完成")
        except Exception as exc:
            self._set(running=False, error=str(exc), speed_bps=0)
            self._log(f"上传失败：{exc}")


cloud_upload_manager = CloudUploadManager()


def _slugify_model_key(value: str, *, prefix: str = "custom") -> str:
    raw = (value or "").strip().lower()
    raw = re.sub(r"[^a-z0-9_\-]+", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("_")
    if not raw:
        raw = f"{prefix}_{uuid.uuid4().hex[:8]}"
    if not re.match(r"^[a-z]", raw):
        raw = f"{prefix}_{raw}"
    return raw[:64]


def _read_json_file(path: Path, fallback: dict) -> dict:
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return json.loads(json.dumps(fallback, ensure_ascii=False))


def _write_json_file(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _safe_import_filename(filename: str, allowed_suffixes: set[str]) -> str:
    name = Path(filename or "").name
    suffix = Path(name).suffix.lower()
    if suffix not in allowed_suffixes:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的模型文件类型：{suffix or '无扩展名'}",
        )
    stem = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]+", "_", Path(name).stem).strip("_")
    if not stem:
        stem = f"model_{uuid.uuid4().hex[:8]}"
    return f"{stem}{suffix}"


async def _save_import_file(upload: UploadFile, allowed_suffixes: set[str]) -> Path:
    safe_name = _safe_import_filename(upload.filename or "", allowed_suffixes)
    target = IMPORTED_MODEL_DIR / safe_name
    if target.exists():
        target = IMPORTED_MODEL_DIR / f"{target.stem}_{uuid.uuid4().hex[:6]}{target.suffix}"
    target.write_bytes(await upload.read())
    return target


def _is_imported_model_path(path_value: str | None) -> bool:
    if not path_value:
        return False
    try:
        target = Path(path_value).resolve()
        imported_root = IMPORTED_MODEL_DIR.resolve()
        return target == imported_root or imported_root in target.parents
    except Exception:
        return False


def _delete_imported_file(path_value: str | None) -> bool:
    if not _is_imported_model_path(path_value):
        return False
    target = Path(str(path_value))
    if target.is_file():
        target.unlink()
        return True
    return False


def _validate_safetensors(path: Path) -> None:
    try:
        with safe_open(str(path), framework="pt", device="cpu") as f:
            if not list(f.keys()):
                raise ValueError("safetensors 中没有 tensor")
    except Exception as exc:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=f"LoRA 文件校验失败：{exc}") from exc


def _validate_onnx(path: Path) -> None:
    try:
        ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    except Exception as exc:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=f"ONNX 文件校验失败：{exc}") from exc


def _refresh_style_models() -> None:
    AVAILABLE_MODELS.clear()
    AVAILABLE_MODELS.update(style_transfer_module._load_model_labels())


def _refresh_sd_styles(cfg: dict | None = None) -> None:
    live_cfg = get_sd_style_config()
    if cfg is not None:
        live_cfg.clear()
        live_cfg.update(cfg)
    AVAILABLE_SD_STYLES.clear()
    AVAILABLE_SD_STYLES.update(
        {
            k: str(v.get("label") or k)
            for k, v in (live_cfg.get("styles") or {}).items()
            if isinstance(v, dict) and not bool(v.get("disabled"))
        }
    )
    pipe = getattr(sd_style_transfer_module, "_PIPELINE", None)
    if pipe is not None:
        setattr(pipe, "_lora_loaded", False)
        setattr(pipe, "_lora_loaded_key", None)


@app.on_event("startup")
async def on_startup():
    await job_queue.start()
    asyncio.create_task(asyncio.to_thread(warmup_pipeline))


class _SafeStderr:
    """Windows 某些终端句柄异常时，屏蔽 stderr.flush 的 Errno 22。"""

    def __init__(self, wrapped):
        self._wrapped = wrapped

    def write(self, data):
        try:
            return self._wrapped.write(data)
        except OSError:
            return 0

    def flush(self):
        try:
            return self._wrapped.flush()
        except OSError:
            return None

    def isatty(self):
        try:
            return self._wrapped.isatty()
        except Exception:
            return False

    def __getattr__(self, name):
        return getattr(self._wrapped, name)


if sys.platform.startswith("win"):
    sys.stderr = _SafeStderr(sys.stderr)


class JobStatus:
    def __init__(self):
        self.progress: int = 0
        self.status: str = "queued"
        # 阶段：pending | downloading | loading_model | running | done | error
        self.phase: str = "pending"
        self.phase_detail: str | None = "任务已创建，等待开始"
        self.mode: str | None = None  # style-transfer | sd
        self.result_path: Path | None = None
        self.result_paths: list[Path] = []
        self.error: str | None = None
        self.score: dict | None = None
        self.next_recipe: dict | None = None
        self.requested_base_model: str | None = None
        self.effective_base_model: str | None = None
        self.effective_base_label: str | None = None
        self.effective_base_type: str | None = None
        self.created_at_ms: int = int(time.time() * 1000)


jobs: Dict[str, JobStatus] = {}
job_queue = JobQueue(concurrency=1)
job_store = JobStore(DB_DIR / "jobs.db")
cloud_runtime_cache: dict = {"ts": 0.0, "payload": None}
cloud_runtime_lock = threading.Lock()


def _diagnose_error(err: str | None) -> dict | None:
    if not err:
        return None
    t = str(err).lower()
    if "no devices were found" in t or "no cuda gpus are available" in t or "cuda is not available" in t:
        return {
            "code": "cloud_no_gpu",
            "title": "云端 GPU 不可用",
            "advice": "当前云端实例没有挂载 GPU。请先在云平台把实例从无卡模式切回 RTX 4090，再重新提交任务。",
        }
    if "connection refused" in t or "system_stats" in t or ("comfyui" in t and "timeout" in t):
        return {
            "code": "comfyui_unreachable",
            "title": "ComfyUI 未运行或不可访问",
            "advice": "请在云端配置页测试连接，确认 ComfyUI 已启动，或重新提交时让系统自动启动远端服务。",
        }
    if (
        "prompt_outputs_failed_validation" in t
        or "value not in list" in t
        or "comfyui http 400" in t
        or "http error 400" in t
        or "failed to validate prompt" in t
    ):
        return {
            "code": "comfyui_prompt_validation",
            "title": "云端工作流校验失败",
            "advice": "当前选择的基础模型或 LoRA 名称与云端 ComfyUI 可用列表不一致。请刷新云端模型列表，确认模型已上传，并重新提交任务。",
        }
    if ("no such file" in t or "does not exist" in t or "not found" in t) and (
        "safetensors" in t or "ckpt" in t or "lora" in t
    ):
        return {
            "code": "remote_model_missing",
            "title": "远端模型文件缺失",
            "advice": "请进入云端接入 / 模型绑定页，同步远端模型列表，并确认当前风格绑定的 checkpoint 与 LoRA 已上传完成。",
        }
    if "outofmemory" in t or "cuda out of memory" in t or "cudnn" in t:
        return {
            "code": "oom",
            "title": "显存不足",
            "advice": "建议开启 quick_mode、降低图片分辨率，或调低步数与重绘强度后重试。",
        }
    if "model" in t and ("not found" in t or "load" in t or "missing" in t):
        return {
            "code": "model_load_failed",
            "title": "模型加载失败",
            "advice": "请检查模型文件是否完整，或先等待预热完成后再重试。",
        }
    if "size" in t or "dimension" in t or "shape" in t:
        return {
            "code": "invalid_image_size",
            "title": "输入尺寸异常",
            "advice": "建议将图片最长边缩小到 2048 以内再提交。",
        }
    return {
        "code": "unknown",
        "title": "未知错误",
        "advice": "请尝试点击重跑；如果仍失败，建议降低步数、分辨率或重绘强度后重试。",
    }


def _base_model_public_info(base_key: str) -> dict:
    info = sd_style_transfer_module.get_sd_base_model_info(base_key)
    model_type = str(info.get("model_type") or info.get("type") or "").lower()
    if not model_type:
        model_type = "sdxl" if sd_style_transfer_module.is_sd_base_model_sdxl(base_key) else "sd15"
    return {
        "key": base_key,
        "label": str(info.get("label") or base_key or "default"),
        "type": model_type,
        "recommended_steps": info.get("recommended_steps"),
        "recommended_cfg": info.get("recommended_cfg"),
        "recommended_width": info.get("recommended_width"),
        "recommended_height": info.get("recommended_height"),
    }


def _style_bound_base_key(sd_style_name: str) -> str:
    style_def = (get_sd_style_config().get("styles") or {}).get(sd_style_name)
    if isinstance(style_def, dict):
        return str(style_def.get("base_model") or "").strip()
    return ""


def _resolve_sd_request_base(sd_style_name: str, requested_base: str | None) -> dict:
    requested = str(requested_base or "default").strip() or "default"
    effective = sd_style_transfer_module.resolve_sd_base_model_key(sd_style_name, requested)
    requested_effective = sd_style_transfer_module.resolve_sd_base_model_key(sd_style_name, requested)
    bound = _style_bound_base_key(sd_style_name)

    # If the user explicitly chooses a concrete base model that conflicts with
    # the LoRA-bound model family, fail before queueing instead of wasting time.
    if requested not in {"", "default", "style_bound"} and bound:
        requested_is_xl = sd_style_transfer_module.is_sd_base_model_sdxl(requested_effective)
        bound_is_xl = sd_style_transfer_module.is_sd_base_model_sdxl(bound)
        if requested_is_xl != bound_is_xl:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"当前 LoRA 绑定的是 {'SDXL' if bound_is_xl else 'SD1.5'} 底模，"
                    f"不能手动改用 {'SDXL' if requested_is_xl else 'SD1.5'}。请选择“跟随当前 LoRA 绑定”。"
                ),
            )

    info = _base_model_public_info(effective)
    return {
        "requested": requested,
        "effective": effective,
        "label": info["label"],
        "type": info["type"],
        "preset": info,
        "style_bound": bound,
    }


def _persist_job(job_id: str, params: dict | None = None) -> None:
    j = jobs.get(job_id)
    if not j:
        return
    content_path = str(UPLOAD_DIR / f"{job_id}_content.png")
    style_path = str(UPLOAD_DIR / f"{job_id}_style.png")
    if not Path(content_path).is_file():
        content_path = None  # type: ignore[assignment]
    if not Path(style_path).is_file():
        style_path = None  # type: ignore[assignment]
    result_path = str(j.result_path) if j.result_path else None
    result_paths = [str(p) for p in (j.result_paths or [])]
    payload = {
        "job_id": job_id,
        "mode": j.mode or "unknown",
        "status": j.status,
        "phase": j.phase,
        "phase_detail": j.phase_detail,
        "progress": j.progress,
        "error": j.error,
        "score": j.score,
        "next_recipe": j.next_recipe,
        "requested_base_model": j.requested_base_model,
        "effective_base_model": j.effective_base_model,
        "effective_base_label": j.effective_base_label,
        "effective_base_type": j.effective_base_type,
        "params": params,
        "content_path": content_path,
        "style_path": style_path,
        "result_path": result_path,
        "result_paths": result_paths,
        "created_at_ms": j.created_at_ms,
    }
    try:
        old = job_store.get_job(job_id)
        if old and not params:
            payload["params"] = old.get("params")
        job_store.upsert_job(payload)
    except Exception:
        pass


def _safe_download_label(label: str | None) -> str:
    """仅允许 ASCII 字母数字与连字符，避免 Content-Disposition 注入。"""
    if not label:
        return "result"
    s = re.sub(r"[^\w\-]+", "", label, flags=re.ASCII)
    return (s[:40] or "result")


def _safe_job_id_segment(job_id: str) -> bool:
    """防止路径穿越；仅允许常见 UUID / 字母数字与连字符。"""
    if not job_id or len(job_id) > 80:
        return False
    return bool(re.fullmatch(r"^[a-zA-Z0-9\-]{8,80}$", job_id))


def _disk_result_path(job_id: str) -> Path | None:
    """优先磁盘上的标准结果文件；服务重启后 jobs 内存为空仍可用。"""
    if not _safe_job_id_segment(job_id):
        return None
    p = RESULT_DIR / f"{job_id}_result.png"
    if p.is_file():
        return p
    job = jobs.get(job_id)
    if job and job.result_path and job.result_path.is_file():
        return job.result_path
    return None


def _disk_orig_path(job_id: str) -> Path | None:
    """原图（内容图）上传保存路径。"""
    if not _safe_job_id_segment(job_id):
        return None
    p = UPLOAD_DIR / f"{job_id}_content.png"
    if p.is_file():
        return p
    return None


def _meta_path(job_id: str) -> Path:
    return META_DIR / f"{job_id}.json"


def _save_job_meta(job_id: str, payload: dict) -> None:
    try:
        _meta_path(job_id).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _build_side_by_side_png_bytes(
    original_path: Path, result_path: Path, max_height: int = 1024, gap: int = 12
) -> bytes:
    """左：原图，右：结果，统一高度后横向拼接为 PNG。"""
    im_o = Image.open(original_path).convert("RGBA")
    im_r = Image.open(result_path).convert("RGBA")
    h_o, h_r = im_o.height, im_r.height
    target_h = min(max(h_o, h_r), max_height)

    def fit_height(im: Image.Image, h: int) -> Image.Image:
        w0, h0 = im.size
        if h0 == h:
            return im
        nw = max(1, int(round(w0 * h / h0)))
        return im.resize((nw, h), Image.Resampling.LANCZOS)

    im_o2 = fit_height(im_o, target_h)
    im_r2 = fit_height(im_r, target_h)
    total_w = im_o2.width + gap + im_r2.width
    bg = (248, 249, 252, 255)
    canvas = Image.new("RGBA", (total_w, target_h), bg)
    canvas.paste(im_o2, (0, 0), im_o2)
    canvas.paste(im_r2, (im_o2.width + gap, 0), im_r2)
    buf = io.BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\u4e00-\u9fff\- ]+", "", text).strip().lower()
    slug = re.sub(r"\s+", "-", slug)
    return slug or "section"


def _render_prompt_markdown(md_text: str) -> tuple[str, str]:
    lines = md_text.splitlines()
    content_parts: list[str] = []
    toc_items: list[tuple[int, str, str]] = []

    in_code = False
    code_buf: list[str] = []
    list_open = False

    def close_list():
        nonlocal list_open
        if list_open:
            content_parts.append("</ul>")
            list_open = False

    for line in lines:
        if line.strip().startswith("```"):
            close_list()
            if in_code:
                content_parts.append(
                    f"<pre><code>{escape(chr(10).join(code_buf))}</code></pre>"
                )
                code_buf = []
                in_code = False
            else:
                in_code = True
            continue

        if in_code:
            code_buf.append(line)
            continue

        if not line.strip():
            close_list()
            continue

        h = re.match(r"^(#{1,6})\s+(.*)$", line)
        if h:
            close_list()
            level = len(h.group(1))
            title = h.group(2).strip()
            anchor = _slugify(title)
            content_parts.append(
                f'<h{level} id="{anchor}">{escape(title)}</h{level}>'
            )
            if level <= 3:
                toc_items.append((level, title, anchor))
            continue

        if line.lstrip().startswith("- "):
            if not list_open:
                content_parts.append("<ul>")
                list_open = True
            item = line.lstrip()[2:].strip()
            content_parts.append(f"<li>{escape(item)}</li>")
            continue

        close_list()
        content_parts.append(f"<p>{escape(line.strip())}</p>")

    close_list()
    if in_code and code_buf:
        content_parts.append(f"<pre><code>{escape(chr(10).join(code_buf))}</code></pre>")

    toc_html = "".join(
        [
            f'<a class="toc-item level-{lv}" href="#{anchor}">{escape(title)}</a>'
            for lv, title, anchor in toc_items
        ]
    )
    return toc_html, "".join(content_parts)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "models": AVAILABLE_MODELS,
            "sd_styles": AVAILABLE_SD_STYLES,
        },
    )


@app.get("/sd", response_class=HTMLResponse)
async def sd_page(request: Request):
    return templates.TemplateResponse(
        "sd.html",
        {
            "request": request,
            "sd_styles": AVAILABLE_SD_STYLES,
        },
    )


@app.get("/__model-import", response_class=HTMLResponse)
async def model_import_page(request: Request):
    return templates.TemplateResponse(
        "model_import.html",
        {
            "request": request,
            "models": AVAILABLE_MODELS,
            "sd_styles": AVAILABLE_SD_STYLES,
        },
    )


@app.get("/api/model-import/config")
async def api_model_import_config():
    style_cfg = _read_json_file(STYLE_MODEL_CONFIG_PATH, {"models": {}})
    sd_cfg = get_sd_style_config()
    return {
        "style_models": AVAILABLE_MODELS,
        "style_model_config": style_cfg.get("models") or {},
        "sd_base_models": get_sd_base_models(),
        "active_sd_base_model": get_active_base_model_key(),
        "sd_styles": sd_cfg.get("styles") or {},
        "sd_adapters": sd_cfg.get("adapters") or {},
        "import_dir": str(IMPORTED_MODEL_DIR),
    }


@app.post("/api/model-import/sd-lora")
async def api_model_import_sd_lora(
    model_file: UploadFile = File(...),
    key: str = Form(""),
    label: str = Form(""),
    weight: float = Form(0.8),
    base_model: str = Form(""),
):
    saved_path = await _save_import_file(model_file, {".safetensors"})
    _validate_safetensors(saved_path)
    style_key = _slugify_model_key(key or saved_path.stem, prefix="sd")
    adapter_key = f"{style_key}_adapter"
    label = (label or saved_path.stem).strip()
    weight_f = max(0.0, min(2.0, float(weight)))
    base_model = (base_model or get_active_base_model_key()).strip()

    cfg = _read_json_file(SD_STYLE_CONFIG_PATH, {"styles": {}, "adapters": {}})
    base_models = cfg.setdefault("base_models", {})
    if base_model and base_model not in base_models:
        raise HTTPException(status_code=400, detail=f"找不到要绑定的基础模型：{base_model}")
    styles = cfg.setdefault("styles", {})
    adapters = cfg.setdefault("adapters", {})
    if style_key in styles:
        raise HTTPException(status_code=409, detail=f"SD 风格 key 已存在：{style_key}")

    adapters[adapter_key] = {
        "env": f"SD_IMPORTED_{style_key.upper()}_PATH",
        "default_path": saved_path.as_posix(),
    }
    styles[style_key] = {
        "label": label,
        "adapters": [adapter_key],
        "weights": [weight_f],
        "base_model": base_model or "default",
    }
    _write_json_file(SD_STYLE_CONFIG_PATH, cfg)
    _refresh_sd_styles(cfg)

    return {
        "ok": True,
        "type": "sd_lora",
        "key": style_key,
        "label": label,
        "path": saved_path.as_posix(),
        "base_model": base_model or "default",
    }


@app.post("/api/model-import/sd-base")
async def api_model_import_sd_base(
    model_file: UploadFile = File(...),
    key: str = Form(""),
    label: str = Form(""),
    config_dir: str = Form(""),
    recommended_steps: int = Form(30),
    recommended_cfg: float = Form(5.5),
    recommended_width: int = Form(768),
    recommended_height: int = Form(768),
    set_active: bool = Form(True),
):
    saved_path = await _save_import_file(model_file, {".safetensors", ".ckpt"})
    if saved_path.suffix.lower() == ".safetensors":
        _validate_safetensors(saved_path)

    base_key = _slugify_model_key(key or saved_path.stem, prefix="base")
    label = (label or saved_path.stem).strip()
    config_dir = (config_dir or str(sd_style_transfer_module.DEFAULT_SD_DIFFUSERS_DIR)).strip()
    cfg = _read_json_file(SD_STYLE_CONFIG_PATH, {"styles": {}, "adapters": {}})
    base_models = cfg.setdefault("base_models", {})
    if base_key in base_models:
        raise HTTPException(status_code=409, detail=f"基础模型 key 已存在：{base_key}")

    base_models[base_key] = {
        "label": label,
        "type": "single_file",
        "path": saved_path.as_posix(),
        "config_dir": config_dir,
        "recommended_steps": max(1, min(150, int(recommended_steps))),
        "recommended_cfg": max(0.0, min(30.0, float(recommended_cfg))),
        "recommended_width": max(64, min(2048, int(recommended_width))),
        "recommended_height": max(64, min(2048, int(recommended_height))),
    }
    cfg.setdefault("active_base_model", get_active_base_model_key())
    if set_active:
        cfg["active_base_model"] = base_key

    _write_json_file(SD_STYLE_CONFIG_PATH, cfg)
    _refresh_sd_styles(cfg)
    if set_active:
        sd_style_transfer_module.reset_pipeline()

    return {
        "ok": True,
        "type": "sd_base",
        "key": base_key,
        "label": label,
        "path": saved_path.as_posix(),
        "active": bool(set_active),
    }


@app.post("/api/model-import/sd-base-active")
async def api_model_import_sd_base_active(key: str = Form(...)):
    key = key.strip()
    cfg = _read_json_file(SD_STYLE_CONFIG_PATH, {"styles": {}, "adapters": {}})
    base_models = cfg.setdefault("base_models", {})
    item = base_models.get(key)
    if not isinstance(item, dict):
        raise HTTPException(status_code=404, detail=f"找不到基础模型：{key}")
    if bool(item.get("disabled")):
        raise HTTPException(status_code=400, detail=f"基础模型已停用：{key}")
    cfg["active_base_model"] = key
    _write_json_file(SD_STYLE_CONFIG_PATH, cfg)
    _refresh_sd_styles(cfg)
    sd_style_transfer_module.reset_pipeline()
    return {"ok": True, "key": key}


@app.post("/api/model-import/sd-style-base")
async def api_model_import_sd_style_base(
    style_key: str = Form(...),
    base_model: str = Form(...),
):
    style_key = style_key.strip()
    base_model = base_model.strip()
    cfg = _read_json_file(SD_STYLE_CONFIG_PATH, {"styles": {}, "adapters": {}})
    styles = cfg.setdefault("styles", {})
    base_models = cfg.setdefault("base_models", {})
    style = styles.get(style_key)
    if not isinstance(style, dict):
        raise HTTPException(status_code=404, detail=f"找不到 SD 风格：{style_key}")
    if base_model not in base_models:
        raise HTTPException(status_code=404, detail=f"找不到基础模型：{base_model}")
    style["base_model"] = base_model
    _write_json_file(SD_STYLE_CONFIG_PATH, cfg)
    _refresh_sd_styles(cfg)
    return {"ok": True, "style_key": style_key, "base_model": base_model}


@app.post("/api/model-import/style-onnx")
async def api_model_import_style_onnx(
    model_file: UploadFile = File(...),
    key: str = Form(""),
    label: str = Form(""),
):
    saved_path = await _save_import_file(model_file, {".onnx"})
    _validate_onnx(saved_path)
    model_key = _slugify_model_key(key or saved_path.stem, prefix="style")
    label = (label or saved_path.stem).strip()

    cfg = _read_json_file(STYLE_MODEL_CONFIG_PATH, {"models": {}})
    models = cfg.setdefault("models", {})
    if model_key in models:
        raise HTTPException(status_code=409, detail=f"风格模型 key 已存在：{model_key}")

    models[model_key] = {
        "label": label,
        "type": "animegan_onnx",
        "path": saved_path.as_posix(),
    }
    _write_json_file(STYLE_MODEL_CONFIG_PATH, cfg)
    _refresh_style_models()
    cache = getattr(style_transfer_module.load_model, "_cache", None)
    if isinstance(cache, dict):
        cache.pop(model_key, None)

    return {
        "ok": True,
        "type": "style_onnx",
        "key": model_key,
        "label": label,
        "path": saved_path.as_posix(),
    }


@app.post("/api/model-import/toggle")
async def api_model_import_toggle(
    target: str = Form(...),
    key: str = Form(...),
    enabled: bool = Form(...),
):
    target = target.strip().lower()
    key = key.strip()
    if target == "sd":
        cfg = _read_json_file(SD_STYLE_CONFIG_PATH, {"styles": {}, "adapters": {}})
        styles = cfg.setdefault("styles", {})
        item = styles.get(key)
        if not isinstance(item, dict):
            raise HTTPException(status_code=404, detail=f"找不到 SD 风格：{key}")
        if enabled:
            item.pop("disabled", None)
        else:
            item["disabled"] = True
        _write_json_file(SD_STYLE_CONFIG_PATH, cfg)
        _refresh_sd_styles(cfg)
        return {"ok": True, "target": target, "key": key, "enabled": enabled}

    if target == "base":
        cfg = _read_json_file(SD_STYLE_CONFIG_PATH, {"styles": {}, "adapters": {}})
        base_models = cfg.setdefault("base_models", {})
        item = base_models.get(key)
        if not isinstance(item, dict):
            raise HTTPException(status_code=404, detail=f"找不到基础模型：{key}")
        if enabled:
            item.pop("disabled", None)
        else:
            if str(cfg.get("active_base_model") or "default") == key:
                raise HTTPException(status_code=400, detail="当前基础模型不能直接停用，请先切换到其他基础模型")
            item["disabled"] = True
        _write_json_file(SD_STYLE_CONFIG_PATH, cfg)
        _refresh_sd_styles(cfg)
        return {"ok": True, "target": target, "key": key, "enabled": enabled}

    if target == "style":
        cfg = _read_json_file(STYLE_MODEL_CONFIG_PATH, {"models": {}})
        models = cfg.setdefault("models", {})
        item = models.get(key)
        if item is None:
            raise HTTPException(status_code=404, detail=f"找不到风格模型：{key}")
        if isinstance(item, dict):
            if enabled:
                item.pop("disabled", None)
            else:
                item["disabled"] = True
        else:
            models[key] = {"label": str(item), "disabled": not enabled}
        _write_json_file(STYLE_MODEL_CONFIG_PATH, cfg)
        _refresh_style_models()
        cache = getattr(style_transfer_module.load_model, "_cache", None)
        if isinstance(cache, dict):
            cache.pop(key, None)
        return {"ok": True, "target": target, "key": key, "enabled": enabled}

    raise HTTPException(status_code=400, detail="target 只能是 sd、base 或 style")


@app.post("/api/model-import/delete")
async def api_model_import_delete(
    target: str = Form(...),
    key: str = Form(...),
    delete_file: bool = Form(False),
):
    target = target.strip().lower()
    key = key.strip()
    deleted_files: list[str] = []

    if target == "sd":
        cfg = _read_json_file(SD_STYLE_CONFIG_PATH, {"styles": {}, "adapters": {}})
        styles = cfg.setdefault("styles", {})
        adapters = cfg.setdefault("adapters", {})
        item = styles.pop(key, None)
        if not isinstance(item, dict):
            raise HTTPException(status_code=404, detail=f"找不到 SD 风格：{key}")

        adapter_keys = list(item.get("adapters") or [])
        used_elsewhere = {
            adapter
            for name, style in styles.items()
            if name != key and isinstance(style, dict)
            for adapter in (style.get("adapters") or [])
        }
        for adapter_key in adapter_keys:
            if adapter_key in used_elsewhere:
                continue
            adapter_info = adapters.pop(adapter_key, None)
            if delete_file and isinstance(adapter_info, dict):
                path_value = str(adapter_info.get("default_path") or "")
                if _delete_imported_file(path_value):
                    deleted_files.append(path_value)

        _write_json_file(SD_STYLE_CONFIG_PATH, cfg)
        _refresh_sd_styles(cfg)
        return {"ok": True, "target": target, "key": key, "deleted_files": deleted_files}

    if target == "base":
        cfg = _read_json_file(SD_STYLE_CONFIG_PATH, {"styles": {}, "adapters": {}})
        base_models = cfg.setdefault("base_models", {})
        item = base_models.pop(key, None)
        if not isinstance(item, dict):
            raise HTTPException(status_code=404, detail=f"找不到基础模型：{key}")
        if str(cfg.get("active_base_model") or "default") == key:
            cfg["active_base_model"] = "default"
            sd_style_transfer_module.reset_pipeline()
        if delete_file:
            path_value = str(item.get("path") or "")
            if _delete_imported_file(path_value):
                deleted_files.append(path_value)
        _write_json_file(SD_STYLE_CONFIG_PATH, cfg)
        _refresh_sd_styles(cfg)
        return {"ok": True, "target": target, "key": key, "deleted_files": deleted_files}

    if target == "style":
        cfg = _read_json_file(STYLE_MODEL_CONFIG_PATH, {"models": {}})
        models = cfg.setdefault("models", {})
        item = models.pop(key, None)
        if item is None:
            raise HTTPException(status_code=404, detail=f"找不到风格模型：{key}")
        if delete_file and isinstance(item, dict):
            path_value = str(item.get("path") or "")
            if _delete_imported_file(path_value):
                deleted_files.append(path_value)
        _write_json_file(STYLE_MODEL_CONFIG_PATH, cfg)
        _refresh_style_models()
        cache = getattr(style_transfer_module.load_model, "_cache", None)
        if isinstance(cache, dict):
            cache.pop(key, None)
        return {"ok": True, "target": target, "key": key, "deleted_files": deleted_files}

    raise HTTPException(status_code=400, detail="target 只能是 sd、base 或 style")


@app.get("/local-history", response_class=HTMLResponse)
async def local_history_page(request: Request):
    return templates.TemplateResponse(
        "local_history.html",
        {"request": request},
    )


@app.get("/cloud-upload-monitor", response_class=HTMLResponse)
async def cloud_upload_monitor_page(request: Request):
    return templates.TemplateResponse(
        "cloud_upload_monitor.html",
        {"request": request},
    )


@app.get("/cloud-settings", response_class=HTMLResponse)
async def cloud_settings_page(request: Request):
    return templates.TemplateResponse(
        "cloud_settings.html",
        {
            "request": request,
            "sd_styles": AVAILABLE_SD_STYLES,
            "base_models": get_sd_base_models(),
        },
    )


def _human_bytes(value: int | float | None) -> str:
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)}B"
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


def _sanitize_cloud_config(config: dict) -> dict:
    return {
        "host": str(config.get("host") or ""),
        "port": int(config.get("port") or 22),
        "username": str(config.get("username") or "root"),
        "comfy_root": str(config.get("comfy_root") or CLOUD_COMFY_ROOT),
        "has_password": bool(config.get("password")),
    }


def _write_cloud_upload_config(update: dict) -> dict:
    current = _read_cloud_upload_config()
    next_config = {
        "host": str(update.get("host") or current.get("host") or "").strip(),
        "port": int(update.get("port") or current.get("port") or 22),
        "username": str(update.get("username") or current.get("username") or "root").strip(),
        "password": str(update.get("password") or current.get("password") or ""),
        "comfy_root": str(update.get("comfy_root") or current.get("comfy_root") or CLOUD_COMFY_ROOT).rstrip("/"),
    }
    if not next_config["host"]:
        raise HTTPException(status_code=400, detail="缺少 SSH Host")
    if not next_config["password"]:
        raise HTTPException(status_code=400, detail="缺少 SSH 密码")
    CLOUD_UPLOAD_CONFIG_PATH.write_text(
        json.dumps(next_config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return next_config


def _cloud_connect_from_config(config: dict):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        str(config["host"]),
        port=int(config.get("port") or 22),
        username=str(config.get("username") or "root"),
        password=str(config["password"]),
        timeout=15,
        banner_timeout=25,
        auth_timeout=25,
    )
    client.get_transport().set_keepalive(15)
    return client


def _cloud_exec_text(client, command: str, timeout: int = 30) -> tuple[str, str, int]:
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    code = stdout.channel.recv_exit_status()
    return out, err, int(code)


def _list_cloud_remote_models() -> dict:
    config = _read_cloud_upload_config()
    if not config.get("host") or not config.get("password"):
        raise HTTPException(status_code=400, detail="缺少云端 SSH 配置")
    comfy_root = str(config.get("comfy_root") or CLOUD_COMFY_ROOT).rstrip("/")
    client = _cloud_connect_from_config(config)
    try:
        code = f"""
import glob, json, os
root={json.dumps(comfy_root)}
def items(kind):
    base=os.path.join(root, 'models', kind)
    rows=[]
    for p in sorted(glob.glob(os.path.join(base, '*'))):
        if not os.path.isfile(p):
            continue
        if not p.lower().endswith(('.safetensors','.ckpt','.pt','.bin')):
            continue
        rows.append({{'name': os.path.basename(p), 'path': p, 'size': os.path.getsize(p)}})
    return rows
print(json.dumps({{'checkpoints': items('checkpoints'), 'loras': items('loras')}}, ensure_ascii=False))
"""
        out, err, status = _cloud_exec_text(client, f"/root/miniconda3/bin/python - <<'PY'\n{code}\nPY", timeout=60)
        if status != 0:
            raise RuntimeError(err or out or f"remote command failed: {status}")
        data = json.loads(out.splitlines()[-1])
        for group in ("checkpoints", "loras"):
            for item in data.get(group, []):
                item["size_human"] = _human_bytes(item.get("size"))
        return {"ok": True, **data}
    finally:
        client.close()


def _test_cloud_config() -> dict:
    config = _read_cloud_upload_config()
    if not config.get("host") or not config.get("password"):
        raise HTTPException(status_code=400, detail="缺少云端 SSH 配置")
    comfy_root = str(config.get("comfy_root") or CLOUD_COMFY_ROOT).rstrip("/")
    client = _cloud_connect_from_config(config)
    try:
        command = (
            "set +e; "
            "echo HOST=$(hostname); "
            "if command -v nvidia-smi >/dev/null 2>&1; then nvidia-smi --query-gpu=name,memory.total --format=csv,noheader; else echo NO_NVIDIA_SMI; fi; "
            f"test -d {comfy_root!r} && echo COMFY_ROOT_OK || echo COMFY_ROOT_MISSING"
        )
        out, err, status = _cloud_exec_text(client, command, timeout=35)
        return {"ok": status == 0, "stdout": out, "stderr": err, "status": status}
    finally:
        client.close()


def _cloud_runtime_status(force: bool = False) -> dict:
    now = time.time()
    with cloud_runtime_lock:
        cached = cloud_runtime_cache.get("payload")
        if cached and not force and now - float(cloud_runtime_cache.get("ts") or 0) < 20:
            return {**cached, "cached": True}

    config = _read_cloud_upload_config()
    if not config.get("host") or not config.get("password"):
        payload = {
            "ok": False,
            "configured": False,
            "ssh": False,
            "gpu": False,
            "comfyui": False,
            "message": "缺少云端 SSH 配置",
        }
    else:
        comfy_root = str(config.get("comfy_root") or CLOUD_COMFY_ROOT).rstrip("/")
        client = None
        try:
            client = _cloud_connect_from_config(config)
            command = (
                "set +e; "
                "echo __HOST__; hostname; "
                "echo __GPU__; "
                "if command -v nvidia-smi >/dev/null 2>&1; then "
                "nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv,noheader,nounits; "
                "else echo NO_NVIDIA_SMI; fi; "
                "echo __COMFY__; "
                "curl -s --max-time 3 http://127.0.0.1:8188/system_stats >/tmp/codex_comfy_stats.json && echo RUNNING || echo STOPPED; "
                "echo __ROOT__; "
                f"test -d {comfy_root!r} && echo OK || echo MISSING"
            )
            out, err, status = _cloud_exec_text(client, command, timeout=35)
            lines = [line.strip() for line in out.splitlines() if line.strip()]
            gpu_lines = []
            section = ""
            comfyui = False
            root_ok = False
            host = ""
            for line in lines:
                if line.startswith("__") and line.endswith("__"):
                    section = line
                    continue
                if section == "__HOST__" and not host:
                    host = line
                elif section == "__GPU__":
                    gpu_lines.append(line)
                elif section == "__COMFY__":
                    comfyui = line == "RUNNING"
                elif section == "__ROOT__":
                    root_ok = line == "OK"
            gpu_available = bool(gpu_lines) and not any("no devices" in x.lower() or "no_nvidia" in x.lower() for x in gpu_lines)
            payload = {
                "ok": status == 0 and gpu_available and root_ok,
                "configured": True,
                "ssh": True,
                "gpu": gpu_available,
                "gpu_lines": gpu_lines,
                "comfyui": comfyui,
                "comfy_root_ok": root_ok,
                "host": host,
                "stderr": err,
                "message": "云端 GPU 可用" if gpu_available else "SSH 正常，但当前未检测到 GPU",
            }
        except Exception as exc:
            payload = {
                "ok": False,
                "configured": True,
                "ssh": False,
                "gpu": False,
                "comfyui": False,
                "message": str(exc),
                "diagnosis": _diagnose_error(str(exc)),
            }
        finally:
            if client is not None:
                client.close()

    with cloud_runtime_lock:
        cloud_runtime_cache["ts"] = now
        cloud_runtime_cache["payload"] = payload
    return payload


def _cloud_remote_snapshot() -> dict:
    cfg = _read_cloud_upload_config()
    if not cfg.get("host") or not cfg.get("password"):
        return {
            "ok": False,
            "error": "missing_config",
            "message": "缺少 data/cloud_upload_config.local.json 或环境变量 CLOUD_SSH_*",
        }
    manifest = _cloud_upload_manifest()
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            str(cfg["host"]),
            port=int(cfg.get("port") or 22),
            username=str(cfg.get("username") or "root"),
            password=str(cfg["password"]),
            timeout=10,
            banner_timeout=20,
            auth_timeout=20,
        )
        stat_cmd = (
            "/root/miniconda3/bin/python - <<'PY'\n"
            "import os,json,subprocess\n"
            f"paths={json.dumps([item['remote'] for item in manifest] + [item['part'] for item in manifest])}\n"
            "out={}\n"
            "for p in paths:\n"
            "    try: out[p]=os.path.getsize(p)\n"
            "    except OSError: out[p]=None\n"
            "try:\n"
            "    df=subprocess.check_output(['df','-B1','/root/autodl-tmp'], text=True).splitlines()[-1].split()\n"
            "    disk={'size':int(df[1]),'used':int(df[2]),'avail':int(df[3]),'use_percent':df[4]}\n"
            "except Exception as e:\n"
            "    disk={'error':str(e)}\n"
            "print(json.dumps({'sizes':out,'disk':disk}, ensure_ascii=False))\n"
            "PY"
        )
        stdin, stdout, stderr = client.exec_command(stat_cmd, timeout=15)
        raw = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        client.close()
        payload = json.loads(raw or "{}")
        remote_sizes = payload.get("sizes") or {}
        disk = payload.get("disk") or {}
        files = []
        completed = 0
        total = 0
        for item in manifest:
            size = int(item["size"])
            total += size
            final_size = remote_sizes.get(item["remote"])
            part_size = remote_sizes.get(item["part"])
            uploaded = size if final_size == size else int(part_size or 0)
            completed += min(uploaded, size)
            files.append(
                {
                    **item,
                    "uploaded": uploaded,
                    "uploaded_human": _human_bytes(uploaded),
                    "size_human": _human_bytes(size),
                    "percent": round((uploaded / size) * 100, 2) if size else 0,
                    "status": "done" if final_size == size else ("partial" if uploaded else "pending"),
                }
            )
        return {
            "ok": True,
            "files": files,
            "completed": completed,
            "completed_human": _human_bytes(completed),
            "total": total,
            "total_human": _human_bytes(total),
            "percent": round((completed / total) * 100, 2) if total else 0,
            "disk": {
                **disk,
                "size_human": _human_bytes(disk.get("size")),
                "used_human": _human_bytes(disk.get("used")),
                "avail_human": _human_bytes(disk.get("avail")),
            },
            "stderr": err,
        }
    except Exception as exc:
        return {"ok": False, "error": "ssh_failed", "message": str(exc)}


@app.get("/api/cloud-upload/status")
async def api_cloud_upload_status():
    state = cloud_upload_manager.snapshot()
    remote = _cloud_remote_snapshot()
    return {"ok": True, "state": state, "remote": remote}


@app.post("/api/cloud-upload/start")
async def api_cloud_upload_start():
    _sync_cloud_mappings_from_sd_config()
    started = cloud_upload_manager.start()
    return {"ok": True, "started": started, "state": cloud_upload_manager.snapshot()}


@app.post("/api/cloud-upload/stop")
async def api_cloud_upload_stop():
    cloud_upload_manager.stop()
    return {"ok": True, "state": cloud_upload_manager.snapshot()}


@app.get("/api/cloud-settings/config")
async def api_cloud_settings_config():
    capabilities = get_cloud_model_capabilities(CLOUD_COMFY_MAPPING_PATH)
    return {
        "ok": True,
        "config": _sanitize_cloud_config(_read_cloud_upload_config()),
        "mappings": capabilities,
        "style_options": AVAILABLE_SD_STYLES,
        "base_options": get_sd_base_models(),
    }


@app.post("/api/cloud-settings/config")
async def api_cloud_settings_save_config(request: Request):
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="请求体必须是 JSON 对象")
    config = _write_cloud_upload_config(payload)
    return {"ok": True, "config": _sanitize_cloud_config(config)}


@app.post("/api/cloud-settings/test")
async def api_cloud_settings_test():
    return _cloud_runtime_status(force=True)


@app.get("/api/cloud-settings/remote-models")
async def api_cloud_settings_remote_models():
    return _list_cloud_remote_models()


@app.get("/api/cloud-runtime/status")
async def api_cloud_runtime_status(force: bool = Query(False)):
    return _cloud_runtime_status(force=force)


@app.post("/api/cloud-settings/mappings")
async def api_cloud_settings_save_mappings(request: Request):
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="请求体必须是 JSON 对象")
    clean: dict[str, dict] = {}
    for section in ("base_models", "loras", "style_prompts", "lora_strength"):
        value = payload.get(section) or {}
        if not isinstance(value, dict):
            raise HTTPException(status_code=400, detail=f"{section} 必须是对象")
        if section == "lora_strength":
            next_section = {}
            for key, raw in value.items():
                if raw in (None, ""):
                    continue
                try:
                    next_section[str(key)] = float(raw)
                except (TypeError, ValueError):
                    raise HTTPException(status_code=400, detail=f"{key} 的 LoRA 权重不是数字")
            clean[section] = next_section
        else:
            clean[section] = {str(k): str(v) for k, v in value.items() if v not in (None, "")}
    CLOUD_COMFY_MAPPING_PATH.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "mappings": load_cloud_mappings(CLOUD_COMFY_MAPPING_PATH)}


@app.get("/api/cloud-comfyui/capabilities")
async def api_cloud_comfyui_capabilities():
    _sync_cloud_mappings_from_sd_config()
    return {"ok": True, **get_cloud_model_capabilities(CLOUD_COMFY_MAPPING_PATH)}


@app.get("/api/weather/now")
async def api_weather_now():
    if not QWEATHER_KEY:
        return JSONResponse(
            {
                "ok": False,
                "error": "missing_api_key",
                "message": "请设置 QWEATHER_API_KEY 环境变量",
            },
            status_code=503,
        )

    params = urllib.parse.urlencode({"location": QWEATHER_LOCATION_ID})
    url = f"https://{QWEATHER_API_HOST}/v2/weather/now?{params}"

    try:
        request = urllib.request.Request(
            url.replace("/v2/", "/v7/"),
            headers={
                "X-QW-Api-Key": QWEATHER_KEY,
                "Accept-Encoding": "gzip",
                "User-Agent": "models-local-history/1.0",
            },
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            if response.headers.get("Content-Encoding", "").lower() == "gzip":
                raw = gzip.decompress(raw)
            body = raw.decode("utf-8", errors="replace")
            if not body.strip():
                return JSONResponse(
                    {
                        "ok": False,
                        "error": "empty_response",
                        "message": "天气服务返回空响应",
                    },
                    status_code=502,
                )
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                return JSONResponse(
                    {
                        "ok": False,
                        "error": "invalid_json",
                        "message": "天气服务返回了非 JSON 内容",
                        "raw": body[:300],
                    },
                    status_code=502,
                )

            if str(data.get("code")) != "200" or not data.get("now"):
                return JSONResponse(
                    {
                        "ok": False,
                        "error": "upstream_error",
                        "message": "天气服务未返回有效天气数据",
                        "upstream": data,
                    },
                    status_code=502,
                )

            now = data["now"]
            return {
                "ok": True,
                "text": now.get("text", "多云"),
                "temp": now.get("temp", "--"),
                "icon": now.get("icon", ""),
                "fetched_at": int(time.time() * 1000),
                "location": QWEATHER_LOCATION_ID,
            }
    except Exception as exc:
        return JSONResponse(
            {
                "ok": False,
                "error": "request_failed",
                "message": str(exc),
                "host": QWEATHER_API_HOST,
            },
            status_code=502,
        )


@app.get("/gallery", response_class=HTMLResponse)
async def gallery_page(request: Request):
    return templates.TemplateResponse("gallery.html", {"request": request})


@app.get("/eval-dashboard", response_class=HTMLResponse)
async def eval_dashboard_page(request: Request):
    return templates.TemplateResponse("eval_dashboard.html", {"request": request})


@app.get("/prompt-guide")
async def prompt_guide(request: Request):
    guide_path = BASE_DIR / "PROMPT_GUIDE.md"
    if not guide_path.exists():
        return JSONResponse({"error": "提示词帮助档案不存在"}, status_code=404)
    md_text = guide_path.read_text(encoding="utf-8")
    toc_html, content_html = _render_prompt_markdown(md_text)
    return templates.TemplateResponse(
        "prompt_guide.html",
        {
            "request": request,
            "toc_html": toc_html,
            "content_html": content_html,
        },
    )


@app.post("/api/style-transfer")
async def api_style_transfer(
    content_image: UploadFile = File(...),
    style_image: UploadFile | None = File(default=None),
    model_name: str = Form(...),
    strength: float = Form(1.5),
):
    if model_name not in AVAILABLE_MODELS:
        return JSONResponse({"error": "未知模型类型"}, status_code=400)

    job_id = str(uuid.uuid4())
    job = JobStatus()
    job.mode = "style-transfer"
    jobs[job_id] = job
    submit_params = {
        "model_name": model_name,
        "strength": strength,
        "has_style_image": style_image is not None,
    }

    content_path = UPLOAD_DIR / f"{job_id}_content.png"
    style_path = (
        UPLOAD_DIR / f"{job_id}_style.png" if style_image is not None else None
    )
    result_path = RESULT_DIR / f"{job_id}_result.png"

    content_bytes = await content_image.read()
    with open(content_path, "wb") as f:
        f.write(content_bytes)

    if style_image is not None:
        style_bytes = await style_image.read()
        with open(style_path, "wb") as f:  # type: ignore[arg-type]
            f.write(style_bytes)

    def progress_callback(p: int):
        job.progress = p

    def phase_callback(phase: str, detail: str | None = None):
        job.phase = phase
        job.phase_detail = detail

    async def run():
        try:
            # 将“加载模型+推理”放到后台线程，避免阻塞事件循环
            job.status = "running"
            job.progress = max(job.progress, 1)
            job.error = None
            phase_callback("loading_model", "正在加载风格迁移模型…")

            model = load_model(model_name)
            phase_callback("running", "正在执行风格迁移…")
            import asyncio

            await asyncio.to_thread(
                run_style_transfer,
                model_name,
                model,
                content_path,
                style_path,
                result_path,
                strength,
                progress_callback,
                phase_callback,
            )
            job.status = "finished"
            job.result_path = result_path
            job.progress = 100
            phase_callback("done", "处理完成")
            _persist_job(job_id, submit_params)
        except Exception as e:  # pragma: no cover - defensive
            job.status = "error"
            job.phase = "error"
            job.phase_detail = str(e)[:240]
            tb_lines = traceback.format_exc().splitlines()
            job.error = f"{type(e).__name__}: {e}\n" + "\n".join(tb_lines[-15:])
            _persist_job(job_id, submit_params)

    # 在后台任务中运行，避免阻塞请求
    import asyncio

    asyncio.create_task(run())
    _persist_job(job_id, submit_params)

    return {"job_id": job_id}


@app.get("/api/status/{job_id}")
async def api_status(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        disk = job_store.get_job(job_id)
        if not disk:
            return JSONResponse({"error": "无效的任务 ID"}, status_code=404)
        diagnosis = _diagnose_error(disk.get("error"))
        return {
            "status": disk.get("status"),
            "progress": disk.get("progress") or 0,
            "phase": disk.get("phase"),
            "phase_detail": disk.get("phase_detail"),
            "mode": disk.get("mode"),
            "error": disk.get("error"),
            "has_result": bool(disk.get("result_path")),
            "result_count": len(disk.get("result_paths") or []),
            "score": disk.get("score"),
            "next_recipe": disk.get("next_recipe"),
            "requested_base_model": disk.get("requested_base_model"),
            "effective_base_model": disk.get("effective_base_model"),
            "effective_base_label": disk.get("effective_base_label"),
            "effective_base_type": disk.get("effective_base_type"),
            "diagnosis": diagnosis,
        }
    qj = job_queue.get(job_id)
    if qj is not None and job.status not in {"finished", "error", "cancelled"}:
        if qj.status == "queued":
            job.status = "queued"
            job.phase = "pending"
            job.phase_detail = "任务排队中"
        elif qj.status == "running":
            job.status = "running"
        elif qj.status == "paused":
            job.status = "paused"
            job.phase = "pending"
            job.phase_detail = "任务已暂停"
        elif qj.status == "cancelled":
            job.status = "cancelled"

    return {
        "status": job.status,
        "progress": job.progress,
        "phase": job.phase,
        "phase_detail": job.phase_detail,
        "mode": job.mode,
        "error": job.error,
        "has_result": job.result_path is not None,
        "result_count": len(job.result_paths) if job.result_paths else (1 if job.result_path else 0),
        "score": job.score,
        "next_recipe": job.next_recipe,
        "requested_base_model": job.requested_base_model,
        "effective_base_model": job.effective_base_model,
        "effective_base_label": job.effective_base_label,
        "effective_base_type": job.effective_base_type,
        "diagnosis": _diagnose_error(job.error),
    }


@app.get("/api/result/{job_id}")
async def api_result(
    job_id: str,
    index: int = Query(0, ge=0, description="多图任务时的序号（当前单文件任务可忽略）"),
    download: bool = Query(False, description="为 true 时以附件形式下载 PNG"),
    label: str | None = Query(
        None,
        max_length=48,
        description="下载文件名前缀，如 style-transfer、sd-img2img",
    ),
):
    job = jobs.get(job_id)
    path = _disk_result_path(job_id)
    if job and job.result_paths and 0 <= index < len(job.result_paths):
        path = job.result_paths[index]
    if path is None:
        return JSONResponse({"error": "结果未就绪"}, status_code=404)

    if download:
        prefix = _safe_download_label(label)
        fname = f"{prefix}-{job_id[:8]}.png"
        return FileResponse(
            path=str(path),
            media_type="image/png",
            filename=fname,
            content_disposition_type="attachment",
        )

    return FileResponse(path=str(path), media_type="image/png")


@app.get("/api/original/{job_id}")
async def api_original_image(job_id: str):
    """返回任务上传的原始内容图（用于前端对比视图）。"""
    path = _disk_orig_path(job_id)
    if path is None:
        return JSONResponse({"error": "原图不可用或已过期"}, status_code=404)
    return FileResponse(path=str(path), media_type="image/png")


def _compare_download_missing_response():
    return JSONResponse(
        {
            "error": "路径不完整",
            "hint": "对比图下载地址应为：/api/compare-download/<任务ID>?download=1&label=style-transfer",
        },
        status_code=400,
    )


@app.get("/api/compare-download")
@app.get("/api/compare-download/")
async def api_compare_download_missing_id():
    """避免访问无任务 ID 时出现 FastAPI 默认 {\"detail\":\"Not Found\"}。"""
    return _compare_download_missing_response()


@app.get("/api/compare-download/{job_id}")
@app.get("/api/compare-download/{job_id}/")
async def api_compare_download(
    job_id: str,
    download: bool = Query(False, description="为 true 时以附件形式下载 PNG"),
    label: str | None = Query(
        None,
        max_length=48,
        description="下载文件名前缀",
    ),
):
    """
    生成「原图 | 结果」左右并排对比图（PNG）。
    需要磁盘上仍存在上传的原图与结果文件（服务重启后也可，只要文件未删）。
    同时注册尾部斜杠，避免部分浏览器/代理访问 .../uuid/ 时 404。
    """
    result_path = _disk_result_path(job_id)
    if result_path is None:
        return JSONResponse({"error": "结果未就绪"}, status_code=404)

    orig_path = _disk_orig_path(job_id)
    if orig_path is None:
        return JSONResponse(
            {"error": "无原图，无法生成对比图（uploads 中内容图已缺失）"},
            status_code=404,
        )

    try:
        png_bytes = _build_side_by_side_png_bytes(orig_path, result_path)
    except Exception as e:  # pragma: no cover - 图片损坏等
        return JSONResponse({"error": f"生成对比图失败: {e!s}"}, status_code=500)

    prefix = _safe_download_label(label)
    fname = f"compare-{prefix}-{job_id[:8]}.png"
    if download:
        return Response(
            content=png_bytes,
            media_type="image/png",
            headers={
                "Content-Disposition": f'attachment; filename="{fname}"',
            },
        )
    return Response(content=png_bytes, media_type="image/png")


@app.post("/api/rerun/{job_id}")
async def api_rerun(job_id: str):
    src = job_store.get_job(job_id)
    if not src:
        return JSONResponse({"error": "历史任务不存在，无法重跑"}, status_code=404)
    mode = src.get("mode")
    params = src.get("params") or {}
    content_path = Path(str(src.get("content_path") or ""))
    if not content_path.is_file():
        return JSONResponse({"error": "原图已缺失，无法重跑"}, status_code=404)

    new_job_id = str(uuid.uuid4())
    new_job = JobStatus()
    new_job.mode = mode
    jobs[new_job_id] = new_job
    new_content_path = UPLOAD_DIR / f"{new_job_id}_content.png"
    new_content_path.write_bytes(content_path.read_bytes())
    new_result_path = RESULT_DIR / f"{new_job_id}_result.png"

    def progress_callback(p: int):
        new_job.progress = p

    def phase_callback(phase: str, detail: str | None = None):
        new_job.phase = phase
        new_job.phase_detail = detail

    if mode == "style-transfer":
        model_name = str(params.get("model_name") or "adain")
        strength = float(params.get("strength") or 1.5)
        style_old = Path(str(src.get("style_path") or ""))
        style_new: Path | None = None
        if style_old.is_file():
            style_new = UPLOAD_DIR / f"{new_job_id}_style.png"
            style_new.write_bytes(style_old.read_bytes())
        rerun_params = {
            "model_name": model_name,
            "strength": strength,
            "has_style_image": style_new is not None,
            "rerun_from": job_id,
        }

        async def run():
            try:
                new_job.status = "running"
                new_job.progress = 1
                phase_callback("loading_model", "正在加载风格迁移模型…")
                model = load_model(model_name)
                phase_callback("running", "正在执行风格迁移…")
                await asyncio.to_thread(
                    run_style_transfer,
                    model_name,
                    model,
                    new_content_path,
                    style_new,
                    new_result_path,
                    strength,
                    progress_callback,
                    phase_callback,
                )
                new_job.status = "finished"
                new_job.result_path = new_result_path
                new_job.progress = 100
                phase_callback("done", "处理完成")
            except Exception as e:
                new_job.status = "error"
                new_job.phase = "error"
                new_job.phase_detail = str(e)[:240]
                new_job.error = f"{type(e).__name__}: {e}"
            finally:
                _persist_job(new_job_id, rerun_params)

        asyncio.create_task(run())
        _persist_job(new_job_id, rerun_params)
        return {"job_id": new_job_id, "status": "running", "rerun_from": job_id}

    if mode == "sd":
        sd_style_name = str(params.get("sd_style_name") or "default")
        base_model = str(params.get("base_model") or "default")
        try:
            base_resolution = _resolve_sd_request_base(sd_style_name, base_model)
        except HTTPException as exc:
            return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
        effective_base_model = str(base_resolution["effective"])
        effective_base_label = str(base_resolution["label"])
        effective_base_type = str(base_resolution["type"])
        new_job.requested_base_model = base_model
        new_job.effective_base_model = effective_base_model
        new_job.effective_base_label = effective_base_label
        new_job.effective_base_type = effective_base_type
        denoise = float(params.get("denoising_strength") or 0.65)
        guidance = float(params.get("guidance_scale") or 5.5)
        steps = int(params.get("num_inference_steps") or 30)
        prompt = str(params.get("prompt") or "")
        negative_prompt = str(params.get("negative_prompt") or "")
        quick_mode = bool(params.get("quick_mode") or False)
        rerun_params = {
            "sd_style_name": sd_style_name,
            "base_model": base_model,
            "effective_base_model": effective_base_model,
            "effective_base_label": effective_base_label,
            "effective_base_type": effective_base_type,
            "denoising_strength": denoise,
            "guidance_scale": guidance,
            "num_inference_steps": steps,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "quick_mode": quick_mode,
            "candidate_count": 1,
            "rerun_from": job_id,
        }

        async def run():
            try:
                new_job.status = "running"
                new_job.progress = 1
                await asyncio.to_thread(
                    run_sd_style_transfer,
                    sd_style_name=sd_style_name,
                    base_model_key=effective_base_model,
                    content_path=new_content_path,
                    output_path=new_result_path,
                    denoising_strength=denoise,
                    guidance_scale=guidance,
                    num_inference_steps=steps,
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    quick_mode=quick_mode,
                    progress_callback=progress_callback,
                    phase_callback=phase_callback,
                )
                new_job.result_path = new_result_path
                new_job.result_paths = [new_result_path]
                s = score_image(new_result_path).as_dict()
                new_job.score = s
                new_job.next_recipe = s.get("recommendation")
                new_job.status = "finished"
                new_job.progress = 100
                phase_callback("done", "处理完成")
            except Exception as e:
                new_job.status = "error"
                new_job.phase = "error"
                new_job.phase_detail = str(e)[:240]
                new_job.error = f"{type(e).__name__}: {e}"
            finally:
                _persist_job(new_job_id, rerun_params)

        q_job = QueueJob(job_id=new_job_id, mode="sd", run_coro_factory=run)
        await job_queue.submit(q_job)
        _persist_job(new_job_id, rerun_params)
        return {"job_id": new_job_id, "status": "queued", "rerun_from": job_id}

    return JSONResponse({"error": f"暂不支持该任务模式重跑：{mode}"}, status_code=400)


@app.get("/bg/{filename}")
async def api_bg_gif(filename: str):
    """
    为页面背景提供动态图资源（例如：/bg/re_0.gif）。
    只允许从 BASE_DIR 读取 .gif，避免目录穿越。
    """
    safe_name = Path(filename).name
    if safe_name.lower().endswith(".gif") is False:
        raise HTTPException(status_code=400, detail="Only .gif background is supported")

    path = BASE_DIR / safe_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Background gif not found")

    return FileResponse(path=str(path), media_type="image/gif")


@app.post("/api/sd-style-transfer")
async def api_sd_style_transfer(
    content_image: UploadFile = File(...),
    sd_style_name: str = Form("default"),
    base_model: str = Form("default"),
    denoising_strength: float = Form(0.65),
    guidance_scale: float = Form(5.5),
    num_inference_steps: int = Form(30),
    prompt: str = Form(""),
    negative_prompt: str = Form(""),
    quick_mode: bool = Form(False),
    candidate_count: int = Form(1),
    render_backend: str = Form("local"),
):
    """
    使用 Stable Diffusion (img2img) + LoRA 做“动漫风格水彩化”。
    约定：prompt / negative_prompt 默认为空字符串（尽量贴合你要的“零提示词”风格控制）。
    """
    if sd_style_name not in AVAILABLE_SD_STYLES:
        return JSONResponse({"error": "未知 SD 风格"}, status_code=400)

    try:
        base_resolution = _resolve_sd_request_base(sd_style_name, base_model)
    except HTTPException as exc:
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
    effective_base_model = str(base_resolution["effective"])
    effective_base_label = str(base_resolution["label"])
    effective_base_type = str(base_resolution["type"])

    job_id = str(uuid.uuid4())
    job = JobStatus()
    job.mode = "sd"
    job.requested_base_model = base_model
    job.effective_base_model = effective_base_model
    job.effective_base_label = effective_base_label
    job.effective_base_type = effective_base_type
    jobs[job_id] = job
    submit_params = {
        "sd_style_name": sd_style_name,
        "base_model": base_model,
        "effective_base_model": effective_base_model,
        "effective_base_label": effective_base_label,
        "effective_base_type": effective_base_type,
        "denoising_strength": denoising_strength,
        "guidance_scale": guidance_scale,
        "num_inference_steps": num_inference_steps,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "quick_mode": quick_mode,
        "candidate_count": candidate_count,
        "render_backend": render_backend,
    }

    content_path = UPLOAD_DIR / f"{job_id}_content.png"
    result_path = RESULT_DIR / f"{job_id}_result.png"

    content_bytes = await content_image.read()
    with open(content_path, "wb") as f:
        f.write(content_bytes)

    def progress_callback(p: int):
        job.progress = p

    def phase_callback(phase: str, detail: str | None = None):
        job.phase = phase
        job.phase_detail = detail

    async def run():
        try:
            job.status = "running"
            job.progress = max(job.progress, 1)
            job.error = None

            qj = job_queue.get(job_id)

            def should_cancel() -> bool:
                return bool(qj and qj.cancel_flag)

            def wait_if_paused() -> None:
                while qj and qj.pause_flag and not qj.cancel_flag:
                    time.sleep(0.2)

            if render_backend == "cloud_comfyui":
                if int(candidate_count) > 1:
                    raise ValueError("云端 ComfyUI 模式暂不支持候选图批量生成")
                await asyncio.to_thread(
                    ensure_comfyui,
                    CLOUD_UPLOAD_CONFIG_PATH,
                )
                await asyncio.to_thread(
                    run_cloud_img2img,
                    config_path=CLOUD_UPLOAD_CONFIG_PATH,
                    mapping_path=CLOUD_COMFY_MAPPING_PATH,
                    sd_style_name=sd_style_name,
                    base_model_key=effective_base_model,
                    content_path=content_path,
                    output_path=result_path,
                    denoising_strength=denoising_strength,
                    guidance_scale=guidance_scale,
                    num_inference_steps=num_inference_steps,
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    quick_mode=quick_mode,
                    progress_callback=progress_callback,
                    phase_callback=phase_callback,
                )
                job.result_path = result_path
                job.result_paths = [result_path]
                s = score_image(result_path).as_dict()
                job.score = s
                job.next_recipe = s.get("recommendation")
            elif int(candidate_count) > 1:
                out_dir = RESULT_DIR / f"{job_id}_cands"
                paths = await asyncio.to_thread(
                    run_sd_style_transfer_candidates,
                    candidate_count=int(candidate_count),
                    output_dir=out_dir,
                    output_prefix=job_id,
                    sd_style_name=sd_style_name,
                    base_model_key=effective_base_model,
                    content_path=content_path,
                    denoising_strength=denoising_strength,
                    guidance_scale=guidance_scale,
                    num_inference_steps=num_inference_steps,
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    quick_mode=quick_mode,
                    progress_callback=progress_callback,
                    phase_callback=phase_callback,
                    should_cancel=should_cancel,
                    wait_if_paused=wait_if_paused,
                )
                scored = [(p, score_image(p).as_dict()) for p in paths]
                scored = sorted(scored, key=lambda x: x[1]["total_score"], reverse=True)
                best = scored[0]
                job.result_path = best[0]
                job.result_paths = [x[0] for x in scored]
                job.score = best[1]
                job.next_recipe = best[1].get("recommendation")
                best[0].replace(result_path)
            else:
                await asyncio.to_thread(
                    run_sd_style_transfer,
                    sd_style_name=sd_style_name,
                    base_model_key=effective_base_model,
                    content_path=content_path,
                    output_path=result_path,
                    denoising_strength=denoising_strength,
                    guidance_scale=guidance_scale,
                    num_inference_steps=num_inference_steps,
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    quick_mode=quick_mode,
                    progress_callback=progress_callback,
                    phase_callback=phase_callback,
                    should_cancel=should_cancel,
                    wait_if_paused=wait_if_paused,
                )
                job.result_path = result_path
                job.result_paths = [result_path]
                s = score_image(result_path).as_dict()
                job.score = s
                job.next_recipe = s.get("recommendation")

            if should_cancel():
                job.status = "cancelled"
                phase_callback("error", "任务已取消")
            else:
                job.status = "finished"
                job.progress = 100
                phase_callback("done", "处理完成")
            _save_job_meta(
                job_id,
                {
                    "job_id": job_id,
                    "style": sd_style_name,
                    "params": {
                        "base_model": base_model,
                        "effective_base_model": effective_base_model,
                        "effective_base_label": effective_base_label,
                        "effective_base_type": effective_base_type,
                        "render_backend": render_backend,
                        "denoise": denoising_strength,
                        "guidance": guidance_scale,
                        "steps": num_inference_steps,
                        "quick_mode": quick_mode,
                    },
                    "score": job.score,
                    "next_recipe": job.next_recipe,
                    "results": [str(p) for p in job.result_paths],
                },
            )
            _persist_job(job_id, submit_params)
        except Exception as e:  # pragma: no cover - defensive
            job.status = "error"
            job.phase = "error"
            job.phase_detail = str(e)[:240]
            tb_lines = traceback.format_exc().splitlines()
            job.error = f"{type(e).__name__}: {e}\n" + "\n".join(tb_lines[-15:])
            _persist_job(job_id, submit_params)

    q_job = QueueJob(job_id=job_id, mode="sd", run_coro_factory=run)
    await job_queue.submit(q_job)
    _persist_job(job_id, submit_params)
    return {
        "job_id": job_id,
        "status": "queued",
        "requested_base_model": base_model,
        "effective_base_model": effective_base_model,
        "effective_base_label": effective_base_label,
        "effective_base_type": effective_base_type,
    }


@app.get("/api/warmup-status")
async def api_warmup_status():
    return get_warmup_status()


@app.post("/api/analyze-input")
async def api_analyze_input(content_image: UploadFile = File(...)):
    temp_id = str(uuid.uuid4())
    p = UPLOAD_DIR / f"{temp_id}_analyze.png"
    p.write_bytes(await content_image.read())
    result = analyze_image(p)
    return result.as_dict()


@app.get("/api/jobs")
async def api_list_jobs():
    payload = []
    for j in job_queue.list_jobs():
        payload.append(
            {
                "job_id": j.job_id,
                "mode": j.mode,
                "status": j.status,
                "created_at": j.created_at,
                "updated_at": j.updated_at,
                "error": j.error,
            }
        )
    return {"jobs": payload}


@app.get("/api/history")
async def api_history(
    mode: str | None = Query(None, description="style-transfer | sd"),
    score_min: float | None = Query(None),
    score_max: float | None = Query(None),
    start_ms: int | None = Query(None),
    end_ms: int | None = Query(None),
    q: str | None = Query(None, max_length=120),
    limit: int = Query(200, ge=1, le=1000),
):
    rows = job_store.search_jobs(
        mode=mode,
        score_min=score_min,
        score_max=score_max,
        start_ms=start_ms,
        end_ms=end_ms,
        q=q,
        limit=limit,
    )
    return {"items": rows}


@app.get("/api/system-stats")
async def api_system_stats():
    queued = 0
    running = 0
    paused = 0
    for qj in job_queue.list_jobs():
        if qj.status == "queued":
            queued += 1
        elif qj.status == "running":
            running += 1
        elif qj.status == "paused":
            paused += 1
    warmup = get_warmup_status()
    return {
        "queue": {"queued": queued, "running": running, "paused": paused},
        "warmup": warmup,
        "uptime_hint": "可结合队列长度估算等待时间",
        "pid": os.getpid(),
    }


@app.get("/api/plugins/sd-styles")
async def api_sd_style_plugins():
    cfg = get_sd_style_config()
    return {
        "styles": cfg.get("styles") or {},
        "adapters": cfg.get("adapters") or {},
        "base_models": get_sd_base_models(),
        "active_base_model": get_active_base_model_key(),
    }


@app.get("/api/eval/summary")
async def api_eval_summary(limit: int = Query(1200, ge=1, le=5000)):
    return job_store.eval_summary(limit=limit)


@app.post("/api/gallery/publish")
async def api_gallery_publish(
    job_id: str = Form(...),
    title: str | None = Form(default=None),
    anonymous: bool = Form(default=False),
):
    src = job_store.get_job(job_id)
    if not src:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    if not src.get("result_path"):
        return JSONResponse({"error": "任务尚无结果图，不能发布"}, status_code=400)
    job_store.publish_gallery(job_id=job_id, title=title, anonymous=anonymous)
    return {"ok": True}


@app.get("/api/gallery/list")
async def api_gallery_list(limit: int = Query(100, ge=1, le=500)):
    items = job_store.list_gallery(limit=limit)
    out = []
    for it in items:
        jid = str(it.get("job_id"))
        out.append(
            {
                "job_id": jid,
                "title": it.get("title") or "",
                "anonymous": bool(it.get("anonymous")),
                "created_at_ms": it.get("created_at_ms"),
                "mode": it.get("mode"),
                "score": ((it.get("score") or {}).get("total_score")),
                "preview_url": f"/api/result/{jid}?t={int(time.time()*1000)}",
            }
        )
    return {"items": out}


@app.get("/api/jobs/{job_id}")
async def api_get_job(job_id: str):
    qj = job_queue.get(job_id)
    if qj is None:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    return {
        "job_id": qj.job_id,
        "status": qj.status,
        "pause_flag": qj.pause_flag,
        "cancel_flag": qj.cancel_flag,
        "error": qj.error,
    }


@app.post("/api/jobs/{job_id}/pause")
async def api_pause_job(job_id: str):
    if not job_queue.pause(job_id):
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    job = jobs.get(job_id)
    if job:
        job.status = "paused"
        job.phase = "pending"
        job.phase_detail = "任务已暂停"
        _persist_job(job_id)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/resume")
async def api_resume_job(job_id: str):
    if not job_queue.resume(job_id):
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    job = jobs.get(job_id)
    if job and job.status == "paused":
        job.status = "queued"
        job.phase = "pending"
        job.phase_detail = "任务已恢复，等待执行"
        _persist_job(job_id)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/cancel")
async def api_cancel_job(job_id: str):
    if not job_queue.cancel(job_id):
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    job = jobs.get(job_id)
    if job:
        job.status = "cancelled"
        job.phase = "error"
        job.phase_detail = "任务已取消"
        _persist_job(job_id)
    return {"ok": True}


@app.post("/api/cancel/{job_id}")
async def api_cancel_job_compat(job_id: str):
    return await api_cancel_job(job_id)


@app.post("/api/batch-submit")
async def api_batch_submit(
    content_images: list[UploadFile] = File(...),
    sd_style_name: str = Form("default"),
    base_model: str = Form("default"),
    denoising_strength: float = Form(0.65),
    guidance_scale: float = Form(5.5),
    num_inference_steps: int = Form(30),
    prompt: str = Form(""),
    negative_prompt: str = Form(""),
    quick_mode: bool = Form(False),
    top_n: int = Form(3),
):
    batch_id = str(uuid.uuid4())
    job_ids: list[str] = []
    for upload in content_images:
        resp = await api_sd_style_transfer(
            content_image=upload,
            sd_style_name=sd_style_name,
            base_model=base_model,
            denoising_strength=denoising_strength,
            guidance_scale=guidance_scale,
            num_inference_steps=num_inference_steps,
            prompt=prompt,
            negative_prompt=negative_prompt,
            quick_mode=quick_mode,
            candidate_count=1,
        )
        job_ids.append(resp["job_id"])
    return {"batch_id": batch_id, "job_ids": job_ids, "top_n": max(1, int(top_n))}


@app.get("/api/batch/{batch_id}")
async def api_batch_status(batch_id: str, job_ids: str = Query("")):
    _ = batch_id
    ids = [x for x in job_ids.split(",") if x]
    rows = []
    for jid in ids:
        j = jobs.get(jid)
        if j is None:
            continue
        rows.append(
            {
                "job_id": jid,
                "status": j.status,
                "score": (j.score or {}).get("total_score"),
                "result": str(j.result_path) if j.result_path else None,
            }
        )
    rows = sorted(rows, key=lambda x: (x["score"] if x["score"] is not None else -1), reverse=True)
    return {"items": rows}


@app.post("/api/export/compare-batch")
async def api_export_compare_batch(job_ids: str = Form(...)):
    ids = [x for x in job_ids.split(",") if x]
    pairs: list[tuple[Path, Path]] = []
    for jid in ids:
        o = _disk_orig_path(jid)
        r = _disk_result_path(jid)
        if o and r:
            pairs.append((o, r))
    out = export_compare_batch(pairs, EXPORT_DIR / f"compare_{int(time.time())}")
    return {"files": [str(p) for p in out]}


@app.post("/api/export/nine-grid")
async def api_export_nine_grid(job_ids: str = Form(...)):
    ids = [x for x in job_ids.split(",") if x]
    imgs: list[Path] = []
    for jid in ids:
        r = _disk_result_path(jid)
        if r:
            imgs.append(r)
    out = export_nine_grid(imgs, EXPORT_DIR / f"nine_grid_{int(time.time())}.png")
    return {"file": str(out)}


@app.post("/api/export/batch-report")
async def api_export_batch_report(job_ids: str = Form(...)):
    ids = [x for x in job_ids.split(",") if x]
    rows = []
    for jid in ids:
        j = jobs.get(jid)
        if not j:
            disk = job_store.get_job(jid)
            if not disk:
                rows.append({"job_id": jid, "status": "missing"})
                continue
            rows.append(
                {
                    "job_id": jid,
                    "status": disk.get("status"),
                    "score": (disk.get("score") or {}).get("total_score"),
                    "params": disk.get("params") or {},
                    "result": disk.get("result_path"),
                    "error": disk.get("error"),
                }
            )
            continue
        rows.append(
            {
                "job_id": jid,
                "status": j.status,
                "score": (j.score or {}).get("total_score"),
                "params": (job_store.get_job(jid) or {}).get("params") or {},
                "result": str(j.result_path) if j.result_path else None,
                "error": j.error,
            }
        )
    rows = sorted(rows, key=lambda x: (x.get("score") if x.get("score") is not None else -1), reverse=True)
    best = rows[0] if rows else None
    report_path = EXPORT_DIR / f"batch_report_{int(time.time())}.md"
    lines = ["# 批处理报告", ""]
    if best:
        lines.append(f"- 最佳任务: `{best.get('job_id')}`")
        lines.append(f"- 最佳分数: `{best.get('score')}`")
        lines.append("")
    lines.append("## 明细")
    for r in rows:
        lines.append(
            f"- {r.get('job_id')} | status={r.get('status')} | score={r.get('score')} | result={r.get('result')} | error={r.get('error') or '-'}"
        )
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return {"best": best, "items": rows, "report_file": str(report_path)}


@app.post("/api/export/transition-video")
async def api_export_transition(job_id: str = Form(...)):
    before = _disk_orig_path(job_id)
    after = _disk_result_path(job_id)
    if not before or not after:
        return JSONResponse({"error": "图片不存在"}, status_code=404)
    out = export_transition_video(before, after, EXPORT_DIR / f"transition_{job_id[:8]}.mp4")
    return {"file": str(out)}


@app.post("/api/share/build")
async def api_share_build(job_id: str = Form(...), template: str = Form("xiaohongshu")):
    r = _disk_result_path(job_id)
    if r is None:
        return JSONResponse({"error": "结果不存在"}, status_code=404)
    meta = jobs.get(job_id)
    params = {
        "style": "sd",
        "steps": None,
        "guidance": None,
        "denoise": None,
        "score": (meta.score or {}).get("total_score") if meta else None,
    }
    card = build_share_card(
        r,
        SHARE_DIR / f"card_{job_id[:8]}.png",
        params=params,
        result_url=f"/api/result/{job_id}",
    )
    cover = build_social_cover(r, SHARE_DIR / f"cover_{template}_{job_id[:8]}.png", template=template)
    copy_text = build_copywriting(params)
    return {"card": str(card), "cover": str(cover), "copywriting": copy_text}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8001, reload=False)

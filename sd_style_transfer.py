from __future__ import annotations

import os
import sys
import contextlib
import threading
import io
import time
import json
from pathlib import Path
from typing import Callable, Dict, Optional, Any

import torch
from safetensors.torch import load_file as load_safetensors_file

from diffusers import (
    DPMSolverMultistepScheduler,
    StableDiffusionImg2ImgPipeline,
)


STYLE_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "sd_styles.json"


def _load_style_config() -> dict[str, Any]:
    default = {
        "styles": {
            "default": {"label": "两个 LoRA 都用（0.8 / 0.7）", "adapters": ["lora1", "lora2"], "weights": [0.8, 0.7]},
            "lora1": {"label": "水彩泼墨画", "adapters": ["lora1"], "weights": [1.0]},
            "lora2": {"label": "百花缭乱 Midjourney", "adapters": ["lora2"], "weights": [1.0]},
            "kyoto": {"label": "京阿尼Kyoto Anime", "adapters": ["kyoto"], "weights": [1.0]},
            "shinkai_char": {"label": "新海诚Character（0.8）", "adapters": ["shinkai_char"], "weights": [0.8]},
            "shinkai_view": {"label": "新海诚 View（0.7）", "adapters": ["shinkai_view"], "weights": [0.7]},
            "ukiyo": {"label": "浮世绘（0.8）", "adapters": ["ukiyo"], "weights": [0.8]},
            "shinkai_mix": {
                "label": "Shinkai View + Character + Ukiyo",
                "adapters": ["shinkai_view", "shinkai_char", "ukiyo"],
                "weights": [0.7, 0.8, 0.8],
            },
            "jojo": {"label": "JoJo（推荐 0.6~0.8）", "adapters": ["jojo"], "weights": [0.7]},
        },
        "adapters": {},
    }
    try:
        if STYLE_CONFIG_PATH.is_file():
            return json.loads(STYLE_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


SD_STYLE_CONFIG = _load_style_config()
AVAILABLE_SD_STYLES: Dict[str, str] = {
    k: str(v.get("label") or k) for k, v in (SD_STYLE_CONFIG.get("styles") or {}).items()
}


def get_sd_style_config() -> dict[str, Any]:
    return SD_STYLE_CONFIG


_PIPELINE_LOCK = threading.Lock()
_PIPELINE: Optional[StableDiffusionImg2ImgPipeline] = None
_TQDM_PATCHED = False
_DIFFUSERS_TQDM_PATCHED = False
_DIFFUSERS_PROGRESS_PATCHED = False
_SAFE_PROGRESS_FILE = None
_WARMUP_STATUS: dict[str, Any] = {
    "ready": False,
    "running": False,
    "last_elapsed_ms": None,
    "last_error": None,
}
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_SD_SINGLE_FILE = BASE_DIR / "MeinaMixV12.safetensors"
DEFAULT_SD_DIFFUSERS_DIR = BASE_DIR / "sd_base_v1_5"


def _get_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _round_to_multiple(x: int, base: int = 64) -> int:
    return int(round(x / base) * base)


def _patch_tqdm_stderr_once() -> None:
    """
    在部分 Windows 终端环境里，tqdm 初始化时会对 sys.stderr.flush() 抛 OSError(22)。
    这里对 tqdm 的 status_printer 做一次安全补丁，避免任务被中断。
    """
    global _TQDM_PATCHED
    if _TQDM_PATCHED:
        return
    try:
        import tqdm.std as tqdm_std

        def _safe_status_printer(file):
            fp = file

            def _printer(status: str):
                try:
                    fp.write(status)
                    fp.flush()
                except Exception:
                    pass

            return _printer

        tqdm_std.tqdm.status_printer = staticmethod(_safe_status_printer)  # type: ignore[attr-defined]
        _TQDM_PATCHED = True
    except Exception:
        # 补丁失败时不阻塞主流程，仍然尝试正常推理
        pass


class _SafeConsoleIO(io.StringIO):
    """用于屏蔽异常终端句柄的安全输出流。"""

    def flush(self) -> None:  # type: ignore[override]
        try:
            super().flush()
        except Exception:
            pass

    def isatty(self) -> bool:  # pragma: no cover - compatibility
        return False


class _SafeStderr:
    """屏蔽异常终端句柄下的 stderr.flush OSError(22)。"""

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


class _NullProgressBar:
    """兼容 diffusers `with self.progress_bar(...) as pb` 调用的空进度条。"""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def update(self, n: int = 1) -> None:
        return None

    def __iter__(self):
        return iter(())


def _patch_diffusers_tqdm_once() -> None:
    """
    直接替换 diffusers.pipeline_utils 的 tqdm 引用，避免进入 tqdm 初始化逻辑。
    """
    global _DIFFUSERS_TQDM_PATCHED
    if _DIFFUSERS_TQDM_PATCHED:
        return
    try:
        from diffusers.pipelines import pipeline_utils as _pu
        
        def _safe_tqdm(iterable=None, *args, **kwargs):
            # 兼容 from_pretrained 内部 `for ... in tqdm(iterable, ...)` 的调用
            if iterable is not None:
                return iterable
            return _NullProgressBar()

        _pu.tqdm = _safe_tqdm  # type: ignore[assignment]
        _DIFFUSERS_TQDM_PATCHED = True
    except Exception:
        pass


def _patch_diffusers_progress_bar_once() -> None:
    """
    直接替换 DiffusionPipeline.progress_bar，彻底绕开 tqdm。
    """
    global _DIFFUSERS_PROGRESS_PATCHED
    if _DIFFUSERS_PROGRESS_PATCHED:
        return
    try:
        from diffusers.pipelines.pipeline_utils import DiffusionPipeline

        def _safe_progress_bar(self, iterable=None, total=None):
            if iterable is not None:
                return iterable
            return _NullProgressBar()

        DiffusionPipeline.progress_bar = _safe_progress_bar  # type: ignore[assignment]
        _DIFFUSERS_PROGRESS_PATCHED = True
    except Exception:
        pass


def _resize_for_img2img(pil_img, max_side: int = 768, base: int = 64):
    w, h = pil_img.size
    if max(w, h) <= max_side:
        new_w = _round_to_multiple(w, base)
        new_h = _round_to_multiple(h, base)
        new_w = max(base, new_w)
        new_h = max(base, new_h)
        return pil_img.resize((new_w, new_h))

    scale = max_side / float(max(w, h))
    new_w = _round_to_multiple(int(w * scale), base)
    new_h = _round_to_multiple(int(h * scale), base)
    new_w = max(base, new_w)
    new_h = max(base, new_h)
    return pil_img.resize((new_w, new_h))


def _load_pipeline_if_needed(
    phase_callback: Optional[Callable[[str, Optional[str]], None]] = None,
) -> StableDiffusionImg2ImgPipeline:
    global _PIPELINE
    _patch_tqdm_stderr_once()
    _patch_diffusers_tqdm_once()
    _patch_diffusers_progress_bar_once()
    if _PIPELINE is not None:
        return _PIPELINE

    with _PIPELINE_LOCK:
        if _PIPELINE is not None:
            return _PIPELINE

        env_model = os.environ.get("SD_BASE_MODEL_ID_OR_PATH", "").strip()
        if env_model:
            model_id_or_path = env_model
        elif DEFAULT_SD_SINGLE_FILE.exists():
            # 精简路径：优先本地单文件模型，减少 from_pretrained 组件拉取
            model_id_or_path = str(DEFAULT_SD_SINGLE_FILE)
        else:
            model_id_or_path = "runwayml/stable-diffusion-v1-5"

        allow_download = os.environ.get("SD_ALLOW_DOWNLOAD", "0").strip() == "1"
        is_single_file = isinstance(model_id_or_path, str) and (
            model_id_or_path.endswith(".safetensors") or model_id_or_path.endswith(".ckpt")
        )
        path_exists = Path(model_id_or_path).exists()
        looks_remote = model_id_or_path.startswith("runwayml/") or (
            not path_exists and "/" in model_id_or_path and not Path(model_id_or_path).is_absolute()
        )
        if phase_callback:
            if allow_download and looks_remote:
                phase_callback(
                    "downloading",
                    "正在从网络下载或更新模型缓存（Hugging Face，首次可能较慢）…",
                )
            elif is_single_file:
                phase_callback(
                    "loading_model",
                    "正在从本地权重与 diffusers 配置加载 SD 管线…",
                )
            else:
                phase_callback(
                    "loading_model",
                    "正在加载 Stable Diffusion（UNet / VAE / 文本编码器）…",
                )

        device = _get_device()
        # 速度优先：CUDA 上使用 fp16，CPU 保持 fp32
        dtype = torch.float16 if device.type == "cuda" else torch.float32

        local_files_only = not allow_download

        # 允许本地离线加载：
        # - 如果 SD_BASE_MODEL_ID_OR_PATH 指向 .safetensors/.ckpt 单文件权重，
        #   则需要同时提供 SD_BASE_DIFFUSERS_DIR（本地 diffusers 格式目录，包含 model_index.json）。
        #
        # - 如果 SD_BASE_MODEL_ID_OR_PATH 指向 diffusers 格式目录，则直接 from_pretrained。
        if is_single_file:
            local_diffusers_dir = os.environ.get("SD_BASE_DIFFUSERS_DIR", "").strip()
            if not local_diffusers_dir:
                if DEFAULT_SD_DIFFUSERS_DIR.exists():
                    local_diffusers_dir = str(DEFAULT_SD_DIFFUSERS_DIR)
                else:
                    raise RuntimeError(
                        "SD_BASE_MODEL_ID_OR_PATH 指向单文件权重，但缺少离线配置目录："
                        "请设置 SD_BASE_DIFFUSERS_DIR（本地 diffusers 格式目录，包含 model_index.json）。"
                    )
            if not Path(local_diffusers_dir).exists():
                raise FileNotFoundError(
                    f"找不到 SD_BASE_DIFFUSERS_DIR：{local_diffusers_dir}"
                )

            try:
                pipe = StableDiffusionImg2ImgPipeline.from_single_file(
                    model_id_or_path,
                    config=local_diffusers_dir,
                    torch_dtype=dtype,
                    safety_checker=None,
                    local_files_only=local_files_only,
                )
            except TypeError:
                # diffusers 版本对参数名有差异时兜底
                pipe = StableDiffusionImg2ImgPipeline.from_single_file(
                    model_id_or_path,
                    config=local_diffusers_dir,
                    torch_dtype=dtype,
                    safety_checker=None,
                )
        else:
            # diffusers 不同版本对 from_pretrained 的参数兼容性略有差异，这里做保护性处理。
            try:
                pipe = StableDiffusionImg2ImgPipeline.from_pretrained(
                    model_id_or_path,
                    torch_dtype=dtype,
                    safety_checker=None,  # 关闭安全检查，避免额外开销/依赖
                    local_files_only=local_files_only,
                )
            except TypeError:
                pipe = StableDiffusionImg2ImgPipeline.from_pretrained(
                    model_id_or_path,
                    torch_dtype=dtype,
                )
                # 兜底：如果安全检查仍存在则关闭
                if hasattr(pipe, "safety_checker"):
                    pipe.safety_checker = None
                if local_files_only and not allow_download:
                    # 这里没法强制 local_files_only（因为 diffusers 版本不支持该参数）
                    # 仍然保持默认行为，但尽量让报错更可读。
                    pass
            except OSError as e:
                raise RuntimeError(
                    "SD 基础模型加载失败：可能未下载/未在本地缓存。"
                    "请先把 SD 基础模型下载到本地目录，并把环境变量 "
                    "`SD_BASE_MODEL_ID_OR_PATH` 指向该目录；或设置 `SD_ALLOW_DOWNLOAD=1` "
                    "允许联网下载（可能会因网络超时失败）。"
                ) from e

        # 强制关闭安全检查器：部分版本/模型组合会把输出替换为黑图
        if hasattr(pipe, "safety_checker"):
            pipe.safety_checker = None
        if hasattr(pipe, "requires_safety_checker"):
            pipe.requires_safety_checker = False
        # 关闭/重定向 diffusers 进度条输出，避免某些终端环境触发 stderr Invalid argument
        global _SAFE_PROGRESS_FILE
        if _SAFE_PROGRESS_FILE is None:
            _SAFE_PROGRESS_FILE = _SafeConsoleIO()
        if hasattr(pipe, "set_progress_bar_config"):
            pipe.set_progress_bar_config(disable=True, leave=False, file=_SAFE_PROGRESS_FILE)
        # 双保险：直接写入内部配置字典
        pipe._progress_bar_config = {  # type: ignore[attr-defined]
            "disable": True,
            "leave": False,
            "file": _SAFE_PROGRESS_FILE,
        }
        # 根因修复：直接替换 progress_bar，彻底绕开 tqdm 初始化/flush
        pipe.progress_bar = lambda total=None: _NullProgressBar()

        # 使用更稳定的采样器（不同环境效果略有差异）。
        # 某些环境下 scipy 损坏会导致 scheduler 兼容类导入失败；
        # 这里做兜底：失败时保留 pipeline 默认 scheduler，避免整条推理链路报错中断。
        try:
            pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config)
        except Exception:
            pass
        pipe.to(device)
        _PIPELINE = pipe
        return pipe


def get_warmup_status() -> dict[str, Any]:
    return dict(_WARMUP_STATUS)


def warmup_pipeline() -> dict[str, Any]:
    if _WARMUP_STATUS["running"]:
        return get_warmup_status()
    t0 = time.time()
    _WARMUP_STATUS["running"] = True
    _WARMUP_STATUS["last_error"] = None
    try:
        pipe = _load_pipeline_if_needed()
        from PIL import Image

        dummy = Image.new("RGB", (256, 256), (127, 127, 127))
        safe_io = _SafeConsoleIO()
        with contextlib.redirect_stderr(safe_io), contextlib.redirect_stdout(safe_io):
            _ = pipe(
                prompt="anime style",
                negative_prompt="low quality, blurry",
                image=dummy,
                strength=0.45,
                guidance_scale=5.0,
                num_inference_steps=4,
            )
        _WARMUP_STATUS["ready"] = True
    except Exception as e:  # pragma: no cover
        _WARMUP_STATUS["last_error"] = f"{type(e).__name__}: {e}"
    finally:
        _WARMUP_STATUS["running"] = False
        _WARMUP_STATUS["last_elapsed_ms"] = int((time.time() - t0) * 1000)
    return get_warmup_status()


def run_sd_style_transfer(
    *,
    sd_style_name: str,
    content_path: Path,
    output_path: Path,
    denoising_strength: float,
    guidance_scale: float,
    num_inference_steps: int,
    prompt: str,
    negative_prompt: str,
    quick_mode: bool,
    progress_callback: Callable[[int], None],
    phase_callback: Optional[Callable[[str, Optional[str]], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    wait_if_paused: Optional[Callable[[], None]] = None,
):
    """
    实现目标：
    - LoRA + 可选 prompt/negative_prompt 做风格控制
    - img2img：输入是一张“内容图”（可为建筑/人物）
    """
    if sd_style_name not in AVAILABLE_SD_STYLES:
        raise ValueError(f"未知 sd_style_name: {sd_style_name}")

    def _ph(phase: str, detail: Optional[str] = None) -> None:
        if phase_callback is not None:
            phase_callback(phase, detail)

    def _check_control() -> None:
        if wait_if_paused is not None:
            wait_if_paused()
        if should_cancel is not None and should_cancel():
            raise RuntimeError("任务已取消")

    def _safe_load_lora_weights(
        pipe_obj: StableDiffusionImg2ImgPipeline,
        lora_path: Path,
        *,
        adapter_name: Optional[str] = None,
    ) -> None:
        """
        兼容部分 LoRA 在旧版 diffusers 下 text-encoder 键不匹配导致的 KeyError。
        失败时回退为“仅加载 UNet LoRA”。
        """
        kwargs = {"adapter_name": adapter_name} if adapter_name is not None else {}
        try:
            pipe_obj.load_lora_weights(str(lora_path), **kwargs)
            return
        except KeyError:
            # 回退：过滤掉 text encoder 相关键，保留 UNet 相关键再加载。
            raw_state = load_safetensors_file(str(lora_path))
            unet_only = {k: v for k, v in raw_state.items() if k.startswith("lora_unet_")}
            if not unet_only:
                raise
            pipe_obj.load_lora_weights(unet_only, **kwargs)

    # 强制在推理入口执行一次补丁（不依赖 pipeline 初始化路径）
    sys.stderr = _SafeStderr(sys.stderr)
    _patch_tqdm_stderr_once()
    _patch_diffusers_tqdm_once()
    _patch_diffusers_progress_bar_once()

    pipe = _load_pipeline_if_needed(phase_callback=_ph)
    _ph("running", "LoRA 与 img2img 采样中（步进进度见下方）…")

    adapter_cfg = SD_STYLE_CONFIG.get("adapters") or {}
    adapter_to_file: dict[str, Path] = {}
    for adapter_name, cfg in adapter_cfg.items():
        env_key = str(cfg.get("env") or "").strip()
        default_path = str(cfg.get("default_path") or "").strip()
        resolved = (os.environ.get(env_key, default_path) if env_key else default_path).strip()
        if resolved:
            adapter_to_file[adapter_name] = Path(resolved)

    # 只加载一次 LoRA（每次 set_adapters 只切换权重）
    # diffusers 的 LoRA 在内部是以 adapter_name 注册的，我们固定命名。
    with _PIPELINE_LOCK:
        # 避免重复 load：通过在模型上挂一个标记判断
        if not getattr(pipe, "_lora_loaded", False):
            # 仅加载存在的 LoRA，避免本地文件不全时阻塞所有风格。
            for aname, apath in adapter_to_file.items():
                if apath.exists():
                    _safe_load_lora_weights(pipe, apath, adapter_name=aname)
            setattr(pipe, "_lora_loaded", True)

    from PIL import Image

    content_img = Image.open(content_path).convert("RGB")
    max_side = 640 if quick_mode else 768
    content_img = _resize_for_img2img(content_img, max_side=max_side, base=64)

    # 使用 diffusers callback 按采样步更新进度（兼容 0.21.x）
    # 注意：progress_callback 内部如果抛异常（例如取消），这里会中止推理。
    def _callback(step: int, timestep: int, latents: "torch.FloatTensor"):
        _check_control()
        # step: 从 0 开始，映射到 10..95
        total = max(1, int(num_inference_steps))
        p = int((step + 1) / total * 85) + 10
        progress_callback(min(95, max(0, p)))

    _check_control()
    progress_callback(5)

    prompt_text = (prompt or "").strip()
    negative_prompt_text = (negative_prompt or "").strip()
    steps_i = int(num_inference_steps)
    denoise_f = float(denoising_strength)
    guidance_f = float(guidance_scale)
    if quick_mode:
        # 快速模式：减少步数和重绘幅度，优先保证响应速度
        steps_i = max(12, min(24, steps_i))
        denoise_f = max(0.35, min(0.55, denoise_f))
        # default 在旧兼容路径下可能双次生成，快速模式下改为单 LoRA 提速
        if sd_style_name == "default":
            sd_style_name = "lora1"
    elif sd_style_name == "jojo":
        # JoJo 风格建议重绘幅度低于 0.8，后端做硬限制避免过度重绘。
        denoise_f = min(denoise_f, 0.79)

    # 根据选择启用不同 LoRA 组合：
    # - 新版 diffusers: 使用 set_adapters 做多 LoRA 混合
    # - 旧版 diffusers: 回退到单 LoRA / 双次生成后融合，避免版本不兼容直接失败
    style_def = (SD_STYLE_CONFIG.get("styles") or {}).get(sd_style_name) or {}
    adapters = list(style_def.get("adapters") or [])
    adapter_weights = [float(x) for x in (style_def.get("weights") or [])]
    if not adapters or len(adapters) != len(adapter_weights):
        raise RuntimeError(f"风格配置无效：{sd_style_name}")
    missing_files = [a for a in adapters if a not in adapter_to_file or not adapter_to_file[a].exists()]
    if missing_files:
        missing_info = ", ".join(f"{a} -> {adapter_to_file[a]}" for a in missing_files)
        raise FileNotFoundError(f"所选风格缺少 LoRA 文件：{missing_info}")

    def _run_pipe_once(callback_fn=None):
        # 兜底：某些 Windows 终端环境下 tqdm 会对 stderr.flush() 抛 Errno 22
        # 这里在推理调用期间把 stdout/stderr 重定向到安全内存流，避免触发无效句柄。
        safe_io = _SafeConsoleIO()
        with contextlib.redirect_stderr(safe_io), contextlib.redirect_stdout(safe_io):
            return pipe(
                prompt=prompt_text,
                negative_prompt=negative_prompt_text,
                image=content_img,
                strength=denoise_f,
                guidance_scale=guidance_f,
                num_inference_steps=steps_i,
                callback=callback_fn,
                callback_steps=1,
            )

    image_out = None
    if hasattr(pipe, "set_adapters"):
        _check_control()
        pipe.set_adapters(adapters, adapter_weights=adapter_weights)
        result = _run_pipe_once(_callback)
        image_out = result.images[0]
        progress_callback(100)
    else:
        # 旧版 diffusers 回退路径
        # 1) 如果只选一个 LoRA，直接单次生成
        if sd_style_name in {
            "lora1",
            "lora2",
            "kyoto",
            "shinkai_char",
            "jojo",
            "shinkai_view",
            "ukiyo",
        }:
            target_path = adapter_to_file[adapters[0]]
            if not target_path.exists():
                raise FileNotFoundError(f"找不到 LoRA：{target_path}")
            with _PIPELINE_LOCK:
                _check_control()
                if hasattr(pipe, "unload_lora_weights"):
                    try:
                        pipe.unload_lora_weights()
                    except Exception:
                        pass
                _safe_load_lora_weights(pipe, target_path)
            result = _run_pipe_once(_callback)
            image_out = result.images[0]
            progress_callback(100)
        else:
            # 2) 旧版 diffusers 不支持 set_adapters 时，回退为“逐 LoRA 生成再加权融合”。
            #    目前覆盖 default 与 shinkai_mix 两种多 LoRA 组合。
            blend_targets = [(adapter_to_file[a], w) for a, w in zip(adapters, adapter_weights)]

            blend_images = []
            total = max(1, len(blend_targets))
            for i, (target_file, _) in enumerate(blend_targets, start=1):
                with _PIPELINE_LOCK:
                    _check_control()
                    if hasattr(pipe, "unload_lora_weights"):
                        try:
                            pipe.unload_lora_weights()
                        except Exception:
                            pass
                _safe_load_lora_weights(pipe, target_file)
                result_i = _run_pipe_once(None)
                blend_images.append(result_i.images[0])
                progress_callback(min(96, int(15 + i / total * 80)))

            total_w = sum(w for _, w in blend_targets)
            out = blend_images[0]
            acc = blend_targets[0][1]
            for img_i, (_, w_i) in zip(blend_images[1:], blend_targets[1:]):
                alpha = w_i / max(1e-6, (acc + w_i))
                out = Image.blend(out, img_i, alpha=alpha)
                acc += w_i
            image_out = out
            progress_callback(100)

    image_out.save(output_path)


def run_sd_style_transfer_candidates(
    *,
    candidate_count: int,
    output_dir: Path,
    output_prefix: str,
    **kwargs,
) -> list[Path]:
    c = max(1, int(candidate_count))
    output_dir.mkdir(parents=True, exist_ok=True)
    base_denoise = float(kwargs.get("denoising_strength", 0.6))
    paths: list[Path] = []
    for i in range(c):
        jitter = (i - (c - 1) / 2.0) * 0.03
        denoise_i = max(0.2, min(0.9, base_denoise + jitter))
        p = output_dir / f"{output_prefix}_{i:02d}.png"
        run_sd_style_transfer(output_path=p, denoising_strength=denoise_i, **kwargs)
        paths.append(p)
    return paths


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
import urllib.parse
import urllib.request
from html import escape
from pathlib import Path
from typing import Dict

from fastapi import FastAPI, UploadFile, File, Form, Query
from fastapi import HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request

from PIL import Image

from style_transfer import load_model, run_style_transfer, AVAILABLE_MODELS
from sd_style_transfer import (
    run_sd_style_transfer,
    run_sd_style_transfer_candidates,
    warmup_pipeline,
    get_warmup_status,
    get_sd_style_config,
    AVAILABLE_SD_STYLES,
)
from image_analyzer import analyze_image
from recipe_scorer import score_image
from job_queue import JobQueue, QueueJob
from exporter import export_compare_batch, export_nine_grid, export_transition_video
from share_builder import build_share_card, build_copywriting, build_social_cover
from job_store import JobStore

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
RESULT_DIR = BASE_DIR / "results"
META_DIR = RESULT_DIR / "meta"
EXPORT_DIR = RESULT_DIR / "exports"
SHARE_DIR = RESULT_DIR / "share"

UPLOAD_DIR.mkdir(exist_ok=True)
RESULT_DIR.mkdir(exist_ok=True)
META_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR.mkdir(parents=True, exist_ok=True)
SHARE_DIR.mkdir(parents=True, exist_ok=True)
DB_DIR = BASE_DIR / "data"
DB_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI()

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

QWEATHER_KEY = os.getenv("QWEATHER_API_KEY", "")
QWEATHER_API_HOST = os.getenv("QWEATHER_API_HOST", "nq5egn2wpt.re.qweatherapi.com")
QWEATHER_LOCATION_ID = os.getenv("QWEATHER_LOCATION_ID", "101010100")


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
        self.created_at_ms: int = int(time.time() * 1000)


jobs: Dict[str, JobStatus] = {}
job_queue = JobQueue(concurrency=1)
job_store = JobStore(DB_DIR / "jobs.db")


def _diagnose_error(err: str | None) -> dict | None:
    if not err:
        return None
    t = str(err).lower()
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
        "advice": "请尝试点击重跑；若仍失败，建议降低参数并重试。",
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


@app.get("/local-history", response_class=HTMLResponse)
async def local_history_page(request: Request):
    return templates.TemplateResponse(
        "local_history.html",
        {"request": request},
    )


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
        denoise = float(params.get("denoising_strength") or 0.65)
        guidance = float(params.get("guidance_scale") or 5.5)
        steps = int(params.get("num_inference_steps") or 30)
        prompt = str(params.get("prompt") or "")
        negative_prompt = str(params.get("negative_prompt") or "")
        quick_mode = bool(params.get("quick_mode") or False)
        rerun_params = {
            "sd_style_name": sd_style_name,
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
    denoising_strength: float = Form(0.65),
    guidance_scale: float = Form(5.5),
    num_inference_steps: int = Form(30),
    prompt: str = Form(""),
    negative_prompt: str = Form(""),
    quick_mode: bool = Form(False),
    candidate_count: int = Form(1),
):
    """
    使用 Stable Diffusion (img2img) + LoRA 做“动漫风格水彩化”。
    约定：prompt / negative_prompt 默认为空字符串（尽量贴合你要的“零提示词”风格控制）。
    """
    if sd_style_name not in AVAILABLE_SD_STYLES:
        return JSONResponse({"error": "未知 SD 风格"}, status_code=400)

    job_id = str(uuid.uuid4())
    job = JobStatus()
    job.mode = "sd"
    jobs[job_id] = job
    submit_params = {
        "sd_style_name": sd_style_name,
        "denoising_strength": denoising_strength,
        "guidance_scale": guidance_scale,
        "num_inference_steps": num_inference_steps,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "quick_mode": quick_mode,
        "candidate_count": candidate_count,
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

            if int(candidate_count) > 1:
                out_dir = RESULT_DIR / f"{job_id}_cands"
                paths = await asyncio.to_thread(
                    run_sd_style_transfer_candidates,
                    candidate_count=int(candidate_count),
                    output_dir=out_dir,
                    output_prefix=job_id,
                    sd_style_name=sd_style_name,
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
    return {"job_id": job_id, "status": "queued"}


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
    return {"styles": cfg.get("styles") or {}, "adapters": cfg.get("adapters") or {}}


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

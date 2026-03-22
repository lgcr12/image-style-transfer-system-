import io
import uuid
import traceback
import re
import sys
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
from sd_style_transfer import run_sd_style_transfer, AVAILABLE_SD_STYLES

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
RESULT_DIR = BASE_DIR / "results"

UPLOAD_DIR.mkdir(exist_ok=True)
RESULT_DIR.mkdir(exist_ok=True)

app = FastAPI()

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


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
        self.status: str = "pending"
        # 阶段：pending | downloading | loading_model | running | done | error
        self.phase: str = "pending"
        self.phase_detail: str | None = "任务已创建，等待开始"
        self.mode: str | None = None  # style-transfer | sd
        self.result_path: Path | None = None
        self.error: str | None = None


jobs: Dict[str, JobStatus] = {}


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
        except Exception as e:  # pragma: no cover - defensive
            job.status = "error"
            job.phase = "error"
            job.phase_detail = str(e)[:240]
            tb_lines = traceback.format_exc().splitlines()
            job.error = f"{type(e).__name__}: {e}\n" + "\n".join(tb_lines[-15:])

    # 在后台任务中运行，避免阻塞请求
    import asyncio

    asyncio.create_task(run())

    return {"job_id": job_id}


@app.get("/api/status/{job_id}")
async def api_status(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        return JSONResponse({"error": "无效的任务 ID"}, status_code=404)

    return {
        "status": job.status,
        "progress": job.progress,
        "phase": job.phase,
        "phase_detail": job.phase_detail,
        "mode": job.mode,
        "error": job.error,
        "has_result": job.result_path is not None,
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
    path = _disk_result_path(job_id)
    if path is None:
        return JSONResponse({"error": "结果未就绪"}, status_code=404)
    _ = index  # 预留批量结果按序号取不同文件

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
async def api_rerun_not_implemented(job_id: str):
    """
    前端 main.js / sd.js 预留了「重跑」调用，但当前后端尚未实现该逻辑。
    注册此路由可避免误请求时返回 FastAPI 默认的 {\"detail\":\"Not Found\"}。
    """
    _ = job_id
    return JSONResponse(
        {"error": "当前版本未实现「重跑」接口，请重新上传图片并提交任务"},
        status_code=501,
    )


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

            # run_sd_style_transfer 是同步函数；用线程避免阻塞事件循环
            import asyncio

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
            )

            job.status = "finished"
            job.result_path = result_path
            job.progress = 100
            phase_callback("done", "处理完成")
        except Exception as e:  # pragma: no cover - defensive
            job.status = "error"
            job.phase = "error"
            job.phase_detail = str(e)[:240]
            tb_lines = traceback.format_exc().splitlines()
            job.error = f"{type(e).__name__}: {e}\n" + "\n".join(tb_lines[-15:])

    import asyncio

    asyncio.create_task(run())
    return {"job_id": job_id}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8001, reload=False)

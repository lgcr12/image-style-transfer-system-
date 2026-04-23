from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class JobStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._lock = threading.Lock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    phase TEXT,
                    phase_detail TEXT,
                    progress INTEGER DEFAULT 0,
                    error TEXT,
                    score_json TEXT,
                    next_recipe_json TEXT,
                    params_json TEXT,
                    content_path TEXT,
                    style_path TEXT,
                    result_path TEXT,
                    result_paths_json TEXT,
                    created_at_ms INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at_ms DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_mode_status ON jobs(mode, status)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS gallery_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL UNIQUE,
                    title TEXT,
                    anonymous INTEGER NOT NULL DEFAULT 0,
                    created_at_ms INTEGER NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_gallery_created ON gallery_items(created_at_ms DESC)")

    def upsert_job(self, payload: dict[str, Any]) -> None:
        now_ms = int(time.time() * 1000)
        payload = dict(payload)
        payload.setdefault("created_at_ms", now_ms)
        payload["updated_at_ms"] = now_ms
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, mode, status, phase, phase_detail, progress, error,
                    score_json, next_recipe_json, params_json,
                    content_path, style_path, result_path, result_paths_json,
                    created_at_ms, updated_at_ms
                ) VALUES (
                    :job_id, :mode, :status, :phase, :phase_detail, :progress, :error,
                    :score_json, :next_recipe_json, :params_json,
                    :content_path, :style_path, :result_path, :result_paths_json,
                    :created_at_ms, :updated_at_ms
                )
                ON CONFLICT(job_id) DO UPDATE SET
                    mode=excluded.mode,
                    status=excluded.status,
                    phase=excluded.phase,
                    phase_detail=excluded.phase_detail,
                    progress=excluded.progress,
                    error=excluded.error,
                    score_json=excluded.score_json,
                    next_recipe_json=excluded.next_recipe_json,
                    params_json=excluded.params_json,
                    content_path=excluded.content_path,
                    style_path=excluded.style_path,
                    result_path=excluded.result_path,
                    result_paths_json=excluded.result_paths_json,
                    updated_at_ms=excluded.updated_at_ms
                """,
                {
                    "job_id": payload.get("job_id"),
                    "mode": payload.get("mode", "unknown"),
                    "status": payload.get("status", "queued"),
                    "phase": payload.get("phase"),
                    "phase_detail": payload.get("phase_detail"),
                    "progress": int(payload.get("progress") or 0),
                    "error": payload.get("error"),
                    "score_json": _to_json(payload.get("score")),
                    "next_recipe_json": _to_json(payload.get("next_recipe")),
                    "params_json": _to_json(payload.get("params")),
                    "content_path": payload.get("content_path"),
                    "style_path": payload.get("style_path"),
                    "result_path": payload.get("result_path"),
                    "result_paths_json": _to_json(payload.get("result_paths") or []),
                    "created_at_ms": int(payload.get("created_at_ms") or now_ms),
                    "updated_at_ms": now_ms,
                },
            )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not row:
            return None
        return _row_to_dict(row)

    def list_jobs(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at_ms DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def search_jobs(
        self,
        mode: str | None = None,
        score_min: float | None = None,
        score_max: float | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        q: str | None = None,
        limit: int = 300,
    ) -> list[dict[str, Any]]:
        jobs = self.list_jobs(limit=max(200, limit * 2))
        out: list[dict[str, Any]] = []
        ql = (q or "").strip().lower()
        for job in jobs:
            if mode and job.get("mode") != mode:
                continue
            at = int(job.get("created_at_ms") or 0)
            if start_ms is not None and at < int(start_ms):
                continue
            if end_ms is not None and at > int(end_ms):
                continue
            score = ((job.get("score") or {}).get("total_score"))
            if score_min is not None and (score is None or float(score) < float(score_min)):
                continue
            if score_max is not None and (score is None or float(score) > float(score_max)):
                continue
            if ql:
                params = job.get("params") or {}
                style_name = str(params.get("sd_style_name") or params.get("model_name") or "")
                prompt = str(params.get("prompt") or "")
                neg = str(params.get("negative_prompt") or "")
                if ql not in style_name.lower() and ql not in prompt.lower() and ql not in neg.lower():
                    continue
            out.append(job)
            if len(out) >= limit:
                break
        return out

    def publish_gallery(self, job_id: str, title: str | None = None, anonymous: bool = False) -> None:
        now_ms = int(time.time() * 1000)
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                INSERT INTO gallery_items (job_id, title, anonymous, created_at_ms)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    title=excluded.title,
                    anonymous=excluded.anonymous
                """,
                (job_id, title, 1 if anonymous else 0, now_ms),
            )

    def list_gallery(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT g.id, g.job_id, g.title, g.anonymous, g.created_at_ms,
                       j.mode, j.score_json, j.params_json, j.result_path
                FROM gallery_items g
                LEFT JOIN jobs j ON j.job_id = g.job_id
                ORDER BY g.created_at_ms DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            out.append(
                {
                    "id": d.get("id"),
                    "job_id": d.get("job_id"),
                    "title": d.get("title") or "",
                    "anonymous": bool(d.get("anonymous")),
                    "created_at_ms": d.get("created_at_ms"),
                    "mode": d.get("mode"),
                    "score": _from_json(d.get("score_json")),
                    "params": _from_json(d.get("params_json")),
                    "result_path": d.get("result_path"),
                }
            )
        return out

    def eval_summary(self, limit: int = 1000) -> dict[str, Any]:
        rows = self.list_jobs(limit=limit)
        by_style: dict[str, list[float]] = {}
        done = 0
        errors = 0
        for r in rows:
            st = r.get("status")
            if st == "finished":
                done += 1
            if st == "error":
                errors += 1
            score = ((r.get("score") or {}).get("total_score"))
            params = r.get("params") or {}
            style = str(params.get("sd_style_name") or params.get("model_name") or "unknown")
            if score is None:
                continue
            by_style.setdefault(style, []).append(float(score))
        style_rows = []
        for style, vals in by_style.items():
            if not vals:
                continue
            style_rows.append(
                {
                    "style": style,
                    "count": len(vals),
                    "avg_score": round(sum(vals) / len(vals), 3),
                    "max_score": round(max(vals), 3),
                    "min_score": round(min(vals), 3),
                }
            )
        style_rows.sort(key=lambda x: x["avg_score"], reverse=True)
        return {"total": len(rows), "finished": done, "error": errors, "styles": style_rows}


def _to_json(v: Any) -> str | None:
    if v is None:
        return None
    try:
        return json.dumps(v, ensure_ascii=False)
    except Exception:
        return None


def _from_json(v: str | None) -> Any:
    if not v:
        return None
    try:
        return json.loads(v)
    except Exception:
        return None


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["score"] = _from_json(d.pop("score_json", None))
    d["next_recipe"] = _from_json(d.pop("next_recipe_json", None))
    d["params"] = _from_json(d.pop("params_json", None))
    d["result_paths"] = _from_json(d.pop("result_paths_json", None)) or []
    return d

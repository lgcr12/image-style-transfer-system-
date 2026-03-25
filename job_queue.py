from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable


@dataclass
class QueueJob:
    job_id: str
    mode: str
    run_coro_factory: Callable[[], Awaitable[None]]
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    error: str | None = None
    pause_flag: bool = False
    cancel_flag: bool = False


class JobQueue:
    def __init__(self, concurrency: int = 1):
        self._queue: asyncio.Queue[QueueJob] = asyncio.Queue()
        self._jobs: dict[str, QueueJob] = {}
        self._workers: list[asyncio.Task] = []
        self._concurrency = max(1, int(concurrency))

    async def start(self) -> None:
        if self._workers:
            return
        for i in range(self._concurrency):
            self._workers.append(asyncio.create_task(self._worker_loop(i)))

    async def _worker_loop(self, _index: int) -> None:
        while True:
            job = await self._queue.get()
            if job.cancel_flag:
                job.status = "cancelled"
                job.updated_at = time.time()
                self._queue.task_done()
                continue
            while job.pause_flag and not job.cancel_flag:
                await asyncio.sleep(0.2)
            if job.cancel_flag:
                job.status = "cancelled"
                job.updated_at = time.time()
                self._queue.task_done()
                continue
            job.status = "running"
            job.updated_at = time.time()
            try:
                await job.run_coro_factory()
                if job.cancel_flag:
                    job.status = "cancelled"
                else:
                    job.status = "finished"
            except asyncio.CancelledError:
                job.status = "cancelled"
            except Exception as e:
                job.status = "error"
                job.error = f"{type(e).__name__}: {e}"
            finally:
                job.updated_at = time.time()
                self._queue.task_done()

    async def submit(self, job: QueueJob) -> None:
        self._jobs[job.job_id] = job
        await self._queue.put(job)

    def get(self, job_id: str) -> QueueJob | None:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[QueueJob]:
        return sorted(self._jobs.values(), key=lambda x: x.created_at, reverse=True)

    def pause(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None:
            return False
        job.pause_flag = True
        if job.status == "queued":
            job.status = "paused"
        job.updated_at = time.time()
        return True

    def resume(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None:
            return False
        job.pause_flag = False
        if job.status == "paused":
            job.status = "queued"
        job.updated_at = time.time()
        return True

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None:
            return False
        job.cancel_flag = True
        if job.status in {"queued", "paused"}:
            job.status = "cancelled"
        job.updated_at = time.time()
        return True

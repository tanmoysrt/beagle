from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable

from ..constants import JOB_ATTEMPT_LIMITS
from ..storage.db import Database
from ..storage.migrations import utc_now

log = logging.getLogger("beagle.queue")
POLL_SECONDS = 0.5


class JobQueue:
    """Durable queue backed by the core database. Jobs run to completion; a newer
    job for the same review just replaces the older result."""

    def __init__(self, core: Database, workers: int, handler: Callable[[str, dict], None]):
        self.core = core
        self.workers = workers
        self.handler = handler
        self.threads: list[threading.Thread] = []
        self.stopping = threading.Event()

    def start(self) -> None:
        self.requeue_orphans()
        for index in range(self.workers):
            thread = threading.Thread(target=self.work, name=f"beagle-worker-{index}", daemon=True)
            thread.start()
            self.threads.append(thread)

    def stop(self, timeout: float = 5.0) -> None:
        self.stopping.set()
        for thread in self.threads:
            thread.join(timeout=timeout)

    def enqueue(self, kind: str, payload: dict[str, Any], review_id: str | None = None) -> int:
        cursor = self.core.execute(
            "insert into jobs (kind, payload_json, review_id, status, created_at)"
            " values (?,?,?,'queued',?)",
            (kind, json.dumps(payload), review_id, utc_now()),
        )
        return int(cursor.lastrowid)

    def job(self, job_id: int) -> dict | None:
        row = self.core.one("select * from jobs where id = ?", (job_id,))
        return dict(row) if row else None

    def pending(self) -> int:
        return int(self.core.scalar("select count(*) from jobs where status in ('queued','running')") or 0)

    def requeue_orphans(self) -> int:
        """Recover jobs a crash left running, repeating only what is safe to repeat.

        A crash can land after the work but before the job was marked done, so a
        review is failed rather than run again.
        """
        requeued = 0
        with self.core.tx() as conn:
            rows = conn.execute(
                "select id, kind, attempts from jobs where status = 'running'"
            ).fetchall()
            for job_id, kind, attempts in rows:
                if attempts < JOB_ATTEMPT_LIMITS.get(kind, 1):
                    conn.execute(
                        "update jobs set status = 'queued', started_at = null where id = ?",
                        (job_id,),
                    )
                    requeued += 1
                else:
                    conn.execute(
                        "update jobs set status = 'failed', error = ?, finished_at = ?"
                        " where id = ?",
                        ("interrupted by a restart; not repeated automatically", utc_now(), job_id),
                    )
        return requeued

    def claim(self) -> dict | None:
        with self.core.tx() as conn:
            row = conn.execute(
                "select id, kind, payload_json, review_id, attempts from jobs"
                " where status = 'queued' order by id limit 1"
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "update jobs set status = 'running', started_at = ?, attempts = attempts + 1"
                " where id = ?",
                (utc_now(), row[0]),
            )
        return {
            "id": row["id"],
            "kind": row["kind"],
            "payload": json.loads(row["payload_json"]),
            "review_id": row["review_id"],
            "attempts": row["attempts"] + 1,
        }

    def work(self) -> None:
        while not self.stopping.is_set():
            try:
                job = self.claim()
            except Exception:
                # A worker thread that dies here never comes back.
                log.exception("claiming a job failed")
                time.sleep(POLL_SECONDS)
                continue
            if job is None:
                time.sleep(POLL_SECONDS)
                continue
            self.run_job(job)

    def run_job(self, job: dict) -> None:
        log.info("job %s: %s %s", job["id"], job["kind"], job.get("review_id") or "")
        try:
            self.handler(job["kind"], job["payload"])
            self.finish(job["id"], "done")
        except Exception as exc:
            log.exception("job %s failed", job["id"])
            if self.should_retry(job):
                self.requeue(job["id"], str(exc))
            else:
                self.finish(job["id"], "failed", str(exc))

    def should_retry(self, job: dict) -> bool:
        return job["attempts"] < JOB_ATTEMPT_LIMITS.get(job["kind"], 1)

    def requeue(self, job_id: int, error: str) -> None:
        self.core.execute(
            "update jobs set status = 'queued', error = ?, started_at = null where id = ?",
            (error, job_id),
        )

    def finish(self, job_id: int, status: str, error: str | None = None) -> None:
        self.core.execute(
            "update jobs set status = ?, error = ?, finished_at = ? where id = ?",
            (status, error, utc_now(), job_id),
        )

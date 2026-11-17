from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from buaa_booking.config import CHINA

RETRYABLE_REFUSALS = {"conflict", "rate_limited", "captcha_invalid", "release_not_open", "preparation_retry"}


@contextmanager
def run_lock(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "runner.lock").open("a+b") as handle:
        handle.seek(0)
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("已有预约进程运行，请勿重复启动") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


class Journal:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(directory / "orders.sqlite3")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS jobs (job_key TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, job_key TEXT, event TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS diagnostics (id INTEGER PRIMARY KEY, job_key TEXT, event TEXT NOT NULL)")
        self.db.commit()

    def trace(self, key: str, stage: str, **fields):
        # Explicit scalar allowlist: never store request payloads, headers or raw responses.
        allowed = {"school_time", "tick", "duration_ms", "status", "server_code", "message",
                   "error_type", "captcha_source", "captcha_age_ms", "attempt", "candidate_count",
                   "offset_ms", "uncertainty_ms", "best_rtt_ms"}
        record = {"stage": stage, "recorded_at": datetime.now(CHINA).isoformat()}
        record.update({k: v for k, v in fields.items() if k in allowed and isinstance(v, (str, int, float))})
        with self.db:
            self.db.execute("INSERT INTO diagnostics(job_key,event) VALUES (?,?)",
                            (key, json.dumps(record, ensure_ascii=False)))

    def diagnostics(self, key: str | None = None) -> list[dict]:
        rows = self.db.execute("SELECT event FROM diagnostics WHERE job_key=? ORDER BY id", (key,)) if key else self.db.execute("SELECT event FROM diagnostics ORDER BY id")
        return [json.loads(row[0]) for row in rows]

    def close(self):
        self.db.close()

    def resume_unsubmitted(self, key: str):
        """Explicit manual restart after preparation failed; retain every historical event."""
        record = self.get(key)
        history = [json.loads(r[0]) for r in self.db.execute("SELECT event FROM events WHERE job_key=?", (key,))]
        if (not record or record.get("status") != "finished" or record.get("attempts") != 0
                or any(r.get("attempts", 0) != 0 or r.get("trade_no") or r.get("status") in
                       {"submitting", "unknown", "submitted", "needs_review", "pending_payment", "paid"}
                       for r in history)
                or any(e["stage"].startswith("submit_") for e in self.diagnostics(key))):
            raise RuntimeError("只有历史中从未提交订单的准备失败记录，才可显式重启")
        return self.save(key, "preparation_retry", message="用户明确重新启动；历史确认未发送订单，保留原记录")

    def get(self, key: str) -> dict | None:
        row = self.db.execute("SELECT payload FROM jobs WHERE job_key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def latest(self) -> dict | None:
        row = self.db.execute("SELECT event FROM events ORDER BY id DESC LIMIT 1").fetchone()
        return json.loads(row[0]) if row else None

    def save(self, key: str, status: str, **updates) -> dict:
        record = self.get(key) or {"job_key": key, "attempts": 0}
        record.update(updates)
        record.update(status=status, updated_at=datetime.now(CHINA).isoformat())
        encoded = json.dumps(record, ensure_ascii=False)
        with self.db:
            self.db.execute("INSERT INTO jobs VALUES (?,?) ON CONFLICT(job_key) DO UPDATE SET payload=excluded.payload", (key, encoded))
            self.db.execute("INSERT INTO events(job_key,event) VALUES (?,?)", (key, encoded))
        return record

    def begin_submission(self, key: str, candidate: dict, max_attempts: int) -> dict:
        current = self.get(key) or {"attempts": 0}
        if current.get("status") is not None and current["status"] not in RETRYABLE_REFUSALS:
            raise RuntimeError("该目标已有提交记录，禁止重复提交")
        if current["attempts"] >= max_attempts:
            raise RuntimeError("已达到提交次数上限")
        return self.save(key, "submitting", candidate=candidate, attempts=current["attempts"] + 1)

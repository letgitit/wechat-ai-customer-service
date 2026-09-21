import json
import sqlite3
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from .models import ReplyDraft, stamp, utcnow


class Store:
    def __init__(self, path, clock=utcnow):
        self.clock = clock
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, isolation_level=None, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        PRAGMA foreign_keys=ON;
        PRAGMA busy_timeout=5000;
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS runtime_state (
          id INTEGER PRIMARY KEY CHECK(id=1), binding_id TEXT NOT NULL, run_id TEXT NOT NULL,
          binding_epoch TEXT NOT NULL, generation INTEGER NOT NULL, mode TEXT NOT NULL,
          paused INTEGER NOT NULL, pause_reason TEXT NOT NULL, heartbeat_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS message_event (
          event_id TEXT PRIMARY KEY, binding_id TEXT NOT NULL, binding_epoch TEXT NOT NULL,
          ui_id TEXT NOT NULL, sender_display TEXT NOT NULL, question TEXT NOT NULL,
          observed_at TEXT NOT NULL, processing_status TEXT NOT NULL,
          UNIQUE(binding_id, binding_epoch, ui_id));
        CREATE TABLE IF NOT EXISTS reply_task (
          task_id TEXT PRIMARY KEY,
          event_id TEXT NOT NULL UNIQUE REFERENCES message_event(event_id),
          engine TEXT NOT NULL, answer TEXT NOT NULL DEFAULT '',
          source_ids TEXT NOT NULL DEFAULT '[]',
          needs_review INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL,
          generation INTEGER NOT NULL, run_id TEXT NOT NULL, binding_epoch TEXT NOT NULL,
          created_at TEXT NOT NULL, expires_at TEXT NOT NULL, attempt_started_at TEXT,
          observed_at TEXT, error_code TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS audit_event (
          id INTEGER PRIMARY KEY, time TEXT NOT NULL, event_type TEXT NOT NULL, task_id TEXT,
          binding_id TEXT NOT NULL, reason TEXT NOT NULL,
          metadata_redacted TEXT NOT NULL DEFAULT '{}');
        """)

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def audit(self, kind, task_id=None, reason=""):
        state = self.state()
        self.db.execute(
            "INSERT INTO audit_event(time,event_type,task_id,binding_id,reason) VALUES(?,?,?,?,?)",
            (stamp(self.clock()), kind, task_id, state["binding_id"] if state else "", reason),
        )

    def state(self):
        row = self.db.execute("SELECT * FROM runtime_state WHERE id=1").fetchone()
        return dict(row) if row else None

    def start(self, binding, epoch, mode):
        with self.transaction():
            previous = self.state()
            if previous and previous["binding_id"] != binding:
                raise ValueError("DATABASE_BINDING_MISMATCH")
            self.db.execute(
                "UPDATE reply_task SET status='UNKNOWN',error_code='CRASH_RECOVERY' "
                "WHERE status='SENDING'"
            )
            self.db.execute(
                "UPDATE reply_task SET status='DRAFT',needs_review=1,"
                "error_code='RESTART_REVIEW' WHERE status='READY'"
            )
            self.db.execute(
                "UPDATE reply_task SET status='DRAFT',needs_review=1,"
                "error_code='INTERRUPTED_GENERATION' WHERE status='GENERATING'"
            )
            self.db.execute(
                "UPDATE message_event SET processing_status='MANUAL' "
                "WHERE processing_status='GENERATING'"
            )
            self.db.execute(
                "INSERT OR REPLACE INTO runtime_state VALUES(1,?,?,?,?,?,?,?,?)",
                (
                    binding,
                    uuid4().hex,
                    epoch,
                    (previous["generation"] + 1) if previous else 0,
                    mode,
                    previous["paused"] if previous else 0,
                    previous["pause_reason"] if previous else "",
                    stamp(self.clock()),
                ),
            )
            self.audit("START", reason="HISTORY_GAP_BASELINE_REQUIRED")

    def accept(
        self, event_id, snapshot, message, text, engine, ttl, max_pending, expected_generation=None
    ):
        with self.transaction():
            state = self.state()
            if (
                state["paused"]
                or (expected_generation is not None and state["generation"] != expected_generation)
                or (state["binding_id"], state["binding_epoch"])
                != (snapshot.binding_id, snapshot.binding_epoch)
            ):
                return None
            pending = self.db.execute(
                "SELECT count(*) FROM reply_task WHERE status IN ('GENERATING','DRAFT','READY')"
            ).fetchone()[0]
            if pending >= max_pending:
                self.audit("REJECT", reason="QUEUE_FULL")
                return None
            cursor = self.db.execute(
                "INSERT OR IGNORE INTO message_event VALUES(?,?,?,?,?,?,?,?)",
                (
                    event_id,
                    snapshot.binding_id,
                    snapshot.binding_epoch,
                    message.ui_id,
                    message.sender_display,
                    text,
                    stamp(message.observed_at),
                    "GENERATING",
                ),
            )
            if not cursor.rowcount:
                return None
            task_id = uuid4().hex
            self.db.execute(
                "INSERT INTO reply_task(task_id,event_id,engine,status,generation,run_id,"
                "binding_epoch,created_at,expires_at) VALUES(?,?,?,'GENERATING',?,?,?,?,?)",
                (
                    task_id,
                    event_id,
                    engine,
                    state["generation"],
                    state["run_id"],
                    snapshot.binding_epoch,
                    stamp(self.clock()),
                    stamp(self.clock() + timedelta(seconds=ttl)),
                ),
            )
            self.audit("ACCEPT", task_id)
            return task_id

    def finish_draft(self, task_id: str, draft: ReplyDraft, mode: str):
        with self.transaction():
            task = self.task(task_id)
            state = self.state()
            if task["status"] != "GENERATING":
                return
            if state["paused"] or (task["run_id"], task["generation"], task["binding_epoch"]) != (
                state["run_id"],
                state["generation"],
                state["binding_epoch"],
            ):
                status = "CANCELLED"
            elif task["expires_at"] <= stamp(self.clock()):
                status = "EXPIRED"
            elif mode == "dry_run":
                status = "SIMULATED"
            elif draft.needs_review or mode == "manual":
                status = "DRAFT"
            else:
                status = "READY"
            self.db.execute(
                "UPDATE reply_task SET answer=?,source_ids=?,needs_review=?,status=?,"
                "error_code=? WHERE task_id=?",
                (
                    draft.text,
                    json.dumps(draft.source_ids),
                    draft.needs_review,
                    status,
                    draft.reason,
                    task_id,
                ),
            )
            self.db.execute(
                "UPDATE message_event SET processing_status='PROCESSED' WHERE event_id=?",
                (task["event_id"],),
            )
            self.audit(status, task_id, draft.reason)

    def tasks(self):
        return [dict(row) for row in self.db.execute("SELECT * FROM reply_task ORDER BY rowid")]

    def task(self, task_id):
        row = self.db.execute("SELECT * FROM reply_task WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise ValueError("TASK_NOT_FOUND")
        return dict(row)

    def pause(self, reason="MANUAL"):
        with self.transaction():
            state = self.state()
            if not state:
                raise ValueError("NOT_STARTED")
            # 人工暂停不能覆盖要求重绑的安全暂停原因。
            if state["paused"] and state["pause_reason"] != "MANUAL":
                reason = state["pause_reason"]
            self.db.execute(
                "UPDATE runtime_state SET paused=1,pause_reason=?,generation=generation+1",
                (reason,),
            )
            self.db.execute(
                "UPDATE reply_task SET status='CANCELLED',error_code=? WHERE status IN "
                "('GENERATING','DRAFT','READY')",
                (reason,),
            )
            inflight = self.db.execute(
                "SELECT count(*) FROM reply_task WHERE status='SENDING'"
            ).fetchone()[0]
            self.audit("PAUSE", reason=reason)
            return inflight

    def resume(self):
        with self.transaction():
            state = self.state()
            if not state or not state["paused"] or state["pause_reason"] != "MANUAL":
                raise ValueError("RESUME_REQUIRES_MANUAL_PAUSE; 安全暂停需人工确认后重新绑定")
            self.db.execute(
                "UPDATE runtime_state SET paused=0,pause_reason='',generation=generation+1"
            )
            self.audit("RESUME", reason="BASELINE_REQUIRED")

    def rebind(self):
        with self.transaction():
            state = self.state()
            if not state or not state["paused"]:
                raise ValueError("REBIND_REQUIRES_PAUSE")
            self.db.execute(
                "UPDATE runtime_state SET paused=0,pause_reason='',generation=generation+1"
            )
            self.audit("REBIND", reason="OPERATOR_CONFIRMED")

    def approve(self, task_id):
        with self.transaction():
            t, s = self.task(task_id), self.state()
            if t["status"] != "DRAFT" or not t["answer"] or t["expires_at"] <= stamp(self.clock()):
                raise ValueError("TASK_NOT_APPROVABLE")
            if s["paused"] or (t["run_id"], t["generation"], t["binding_epoch"]) != (
                s["run_id"],
                s["generation"],
                s["binding_epoch"],
            ):
                raise ValueError("STALE_TASK_REQUIRES_MANUAL_HANDLING")
            self.db.execute(
                "UPDATE reply_task SET status='READY',needs_review=0 WHERE task_id=?", (task_id,)
            )
            self.audit("APPROVE", task_id)

    def attempts(self):
        return self.db.execute(
            "SELECT count(*) FROM audit_event WHERE event_type='SENDING'"
        ).fetchone()[0]

    def claim(self, task_id, budget, interval):
        with self.transaction():
            t, s = self.task(task_id), self.state()
            if t["status"] != "READY":
                return False
            if s["paused"] or (t["run_id"], t["generation"], t["binding_epoch"]) != (
                s["run_id"],
                s["generation"],
                s["binding_epoch"],
            ):
                self.db.execute(
                    "UPDATE reply_task SET status='CANCELLED',error_code='STALE' WHERE task_id=?",
                    (task_id,),
                )
                return False
            now = stamp(self.clock())
            if t["expires_at"] <= now:
                self.db.execute(
                    "UPDATE reply_task SET status='EXPIRED' WHERE task_id=?", (task_id,)
                )
                return False
            last = self.db.execute(
                "SELECT max(time) FROM audit_event WHERE event_type='SENDING'"
            ).fetchone()[0]
            if self.attempts() >= budget or (
                last and last > stamp(self.clock() - timedelta(seconds=interval))
            ):
                return False
            self.db.execute(
                "UPDATE reply_task SET status='SENDING',attempt_started_at=? WHERE task_id=?",
                (now, task_id),
            )
            self.audit("SENDING", task_id)
            return True

    def result(self, task_id, result):
        with self.transaction():
            status = "FAILED" if result.status == "NOT_ATTEMPTED" else result.status
            self.db.execute(
                "UPDATE reply_task SET status=?,observed_at=?,error_code=? "
                "WHERE task_id=? AND status='SENDING'",
                (
                    status,
                    stamp(result.observed_at) if result.observed_at else None,
                    result.reason,
                    task_id,
                ),
            )
            self.audit(status, task_id, result.reason)

    def expire(self):
        self.db.execute(
            "UPDATE reply_task SET status='EXPIRED',error_code='TTL' WHERE status IN "
            "('GENERATING','DRAFT','READY') AND expires_at<=?",
            (stamp(self.clock()),),
        )

    def cleanup(self, days):
        # 保留无内容的审计与预算；清理不会让重启重新获得发送次数。
        with self.transaction():
            ids = [
                r[0]
                for r in self.db.execute(
                    "SELECT event_id FROM reply_task WHERE created_at<? AND status IN "
                    "('SIMULATED','OBSERVED_SENT','UNKNOWN','CANCELLED','EXPIRED','FAILED')",
                    (stamp(self.clock() - timedelta(days=days)),),
                )
            ]
            for event_id in ids:
                self.db.execute(
                    "UPDATE reply_task SET answer='',source_ids='[]' WHERE event_id=?", (event_id,)
                )
                self.db.execute(
                    "UPDATE message_event SET sender_display='',question='' WHERE event_id=?",
                    (event_id,),
                )
            self.audit("CLEANUP", reason="CONTENT_REDACTED")
            return len(ids)

    def close(self):
        self.db.close()

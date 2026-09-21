import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from uuid import uuid4

from .config import Config
from .delta import Delta, GapError
from .models import ReplyDraft, SendRequest, SendResult, stamp, utcnow
from .policy import Authorization, question, send_gate
from .replies import reply_provider
from .storage import Store


class Engine:
    def __init__(
        self,
        config: Config,
        adapter,
        store: Store,
        *,
        auth=None,
        replies=None,
        clock=utcnow,
        lock_valid=lambda: True,
        monotonic=time.monotonic,
    ):
        self.config, self.adapter, self.store = config, adapter, store
        auth = auth or Authorization()
        self.auth, self.clock, self.lock_valid = auth, clock, lock_valid
        self.monotonic = monotonic
        self.deadline = monotonic() + min(
            config.run_duration_seconds, auth.duration_seconds or config.run_duration_seconds
        )
        self.replies = replies or reply_provider(config, allow_llm=auth.allow_llm)
        self.delta = Delta()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="llm-draft")
        self.pending = {}
        self.generation = None
        self.started = False
        self.epoch = None
        self.after_claim = None
        self.budget = min(config.max_sends_per_run, auth.max_sends or config.max_sends_per_run)

    def _validate(self, snapshot):
        c = self.config
        if (snapshot.binding_id, snapshot.chat_name, snapshot.chat_type) != (
            c.binding_id,
            c.target,
            "group",
        ):
            raise GapError("TARGET_MISMATCH")
        if self.epoch is not None and snapshot.binding_epoch != self.epoch:
            raise GapError("REBIND_REQUIRED")

    def start(self):
        # 先恢复数据库；GUI 初始化或首个读取失败也不能遗留 SENDING。
        self.store.start(self.config.binding_id, "UNBOUND", self.config.send_mode)
        self.started = True
        try:
            self.adapter.connect()
            snapshot = self.adapter.snapshot()
            self._validate(snapshot)
            self.delta.update(snapshot)
            self.epoch = snapshot.binding_epoch
            self.store.db.execute("UPDATE runtime_state SET binding_epoch=?", (self.epoch,))
            self.generation = self.store.state()["generation"]
        except Exception:
            self.store.pause("REBIND_REQUIRED")

    def ingest(self, snapshot, message, event_id=None):
        text = question(message)
        if text is None:
            return
        c = self.config
        # 异常长问题不持久化整段；客服引擎仍收到原输入以生成拒绝结果。
        stored_text = text if len(text) <= c.max_question_chars else "[超长输入已省略]"
        task_id = self.store.accept(
            event_id or uuid4().hex,
            snapshot,
            message,
            stored_text,
            "knowledge" if c.knowledge_enabled else c.reply_engine,
            c.reply_ttl_seconds,
            c.max_pending_tasks,
            expected_generation=self.generation,
        )
        if task_id is None:
            return
        if c.knowledge_enabled or (
            c.reply_engine == "llm" and text and len(text) <= c.max_question_chars
        ):
            self.pending[task_id] = self.executor.submit(self.replies.generate, text)
        else:
            self.store.finish_draft(task_id, self.replies.generate(text), c.send_mode)

    def tick(self):
        if not self.started:
            raise RuntimeError("NOT_STARTED")
        s = self.store.state()
        if self.generation != s["generation"]:
            self.delta.reset()
            self.generation = s["generation"]
            for task_id, future in list(self.pending.items()):
                if future.cancel():
                    del self.pending[task_id]
        self.store.expire()
        try:
            snapshot = self.adapter.snapshot()
            self._validate(snapshot)
            new = self.delta.update(snapshot)
        except Exception:
            self.store.pause("GAP_OR_TARGET_FAILURE")
            return
        self.store.db.execute("UPDATE runtime_state SET heartbeat_at=?", (stamp(self.clock()),))
        if not s["paused"]:
            for message in new:
                self.ingest(snapshot, message)
        for task_id, future in list(self.pending.items()):
            if future.done():
                if self.config.knowledge_enabled:
                    draft = None
                    try:
                        result = future.result()
                    except Exception:
                        result = None
                    task, state = self.store.task(task_id), self.store.state()
                    active = (
                        task["status"] == "GENERATING"
                        and not state["paused"]
                        and task["expires_at"] > stamp(self.clock())
                        and all(
                            task[k] == state[k] for k in ("run_id", "generation", "binding_epoch")
                        )
                    )
                    try:
                        if result is not None:
                            draft = self.replies.finalize(task_id, result, active=active)
                    except Exception:
                        draft = None
                    if draft is None:
                        draft = ReplyDraft("", needs_review=True, reason="KNOWLEDGE_FAILED")
                else:
                    draft = future.result()
                self.store.finish_draft(task_id, draft, self.config.send_mode)
                del self.pending[task_id]
        self.dispatch()

    def dispatch(self):
        c = self.config
        if not send_gate(c, self.auth, self.adapter.kind, self.lock_valid()):
            return
        for task in self.store.tasks():
            if self.monotonic() >= self.deadline:
                return
            if task["status"] != "READY":
                continue
            try:
                snapshot = self.adapter.snapshot()
                self._validate(snapshot)
                self.delta.check(snapshot)
            except Exception:
                self.store.pause("PREFLIGHT_FAILED")
                return
            if self.monotonic() >= self.deadline:
                return
            if not self.store.claim(task["task_id"], self.budget, c.min_send_interval_seconds):
                continue
            # SENDING 已提交；从这里开始暂停可能无法撤回在途动作。
            if self.after_claim:
                self.after_claim(task["task_id"])
            prefix = f"{c.reply_prefix} #{task['task_id']}"
            request = SendRequest(
                task["task_id"],
                c.binding_id,
                task["binding_epoch"],
                c.target,
                f"{prefix}\n{task['answer']}",
                datetime.fromisoformat(task["expires_at"]),
            )
            try:
                result = self.adapter.send_text(request)
            except Exception:
                result = SendResult("UNKNOWN", "SEND_EXCEPTION", self.clock())
            self.store.result(task["task_id"], result)
            if result.status != "OBSERVED_SENT":
                self.store.pause("SEND_UNCERTAIN")
                return

    def close(self):
        for future in self.pending.values():
            future.cancel()
        self.executor.shutdown(wait=True, cancel_futures=True)
        self.adapter.close()

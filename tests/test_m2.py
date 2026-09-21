import os
import subprocess
import sys
from dataclasses import replace

import pytest
from conftest import add, msg
from filelock import Timeout

from wechat_cs.adapters.fake import FakeWechatAdapter
from wechat_cs.config import Config
from wechat_cs.delta import Delta, GapError
from wechat_cs.engine import Engine
from wechat_cs.locking import instance_lock
from wechat_cs.models import ChatSnapshot, ReplyDraft
from wechat_cs.policy import Authorization, question
from wechat_cs.storage import Store


def test_a06_rolling_anchor(rig):
    e, a, s, _ = rig()
    add(a, msg("1"), msg("2"))
    e.tick()
    a.current = replace(a.current, messages=(msg("2"), msg("3")))
    e.tick()
    assert len(s.tasks()) == 3 and not a.calls


def test_a07_a16_distinct_ids_same_name_text(rig):
    e, a, s, _ = rig(send_mode="auto", allow_send=True, max_sends_per_run=1)
    add(a, msg("1"), msg("2"))
    e.tick()
    assert len(s.tasks()) == 2 and len(a.calls) == 1
    assert [t["status"] for t in s.tasks()] == ["OBSERVED_SENT", "READY"]


def test_a08_idempotent_event(rig):
    e, a, s, _ = rig()
    m = msg()
    e.ingest(a.current, m, "same-event")
    e.ingest(a.current, m, "same-event")
    e.ingest(a.current, replace(m, ui_id="different"), "same-event")
    e.ingest(a.current, m, "different-event")
    assert len(s.tasks()) == 1 and not a.calls


@pytest.mark.parametrize(
    "changed",
    [
        (msg("recreated"),),
        (),
        (msg("1", content="changed"),),
        (msg(None),),
        (msg("1"), msg("1")),
        (msg("2"), msg("1")),
    ],
)
def test_a09_gap_cancels_tasks(rig, changed):
    e, a, s, _ = rig(send_mode="manual")
    add(a, msg("1"), msg("2"))
    e.tick()
    a.current = replace(a.current, messages=changed)
    e.tick()
    assert s.state()["paused"]
    assert all(t["status"] == "CANCELLED" for t in s.tasks())
    assert not a.calls
    with pytest.raises(ValueError, match="RESUME"):
        s.resume()
    s.pause()
    with pytest.raises(ValueError, match="RESUME"):
        s.resume()


def test_a10_empty_baseline_and_read_failure(rig):
    e, a, s, _ = rig()
    add(a, msg())
    e.tick()
    assert len(s.tasks()) == 1
    a.snapshots = iter([RuntimeError("synthetic read failure")])
    e.tick()
    assert s.state()["paused"] and not a.calls


@pytest.mark.parametrize(
    "attr,kind",
    [
        ("self", "text"),
        ("system", "text"),
        ("other", "text"),
        ("", "text"),
        ("friend", "image"),
        ("friend", "voice"),
        ("friend", "quote"),
    ],
)
def test_a11_a12_ignore_sources_types(rig, attr, kind):
    e, a, s, _ = rig()
    add(a, msg(attr=attr, type=kind))
    e.tick()
    assert s.tasks() == [] and not a.calls


@pytest.mark.parametrize(
    "text,expected",
    [
        ("普通聊天", None),
        ("#客服端", None),
        ("中间 #客服 问题", None),
        ("#客服 问题", "问题"),
        ("#客服：问题", "问题"),
        ("#客服:问题", "问题"),
        ("#客服\n问题", "问题"),
        ("#客服", ""),
        (None, None),
    ],
)
def test_a13_prefix(text, expected):
    assert question(msg(content=text)) == expected


def test_a15_oversized_question(rig):
    e, a, s, _ = rig(send_mode="auto", allow_send=True)
    add(a, msg(content="#客服 " + "x" * 1001))
    e.tick()
    assert s.tasks()[0]["status"] == "DRAFT"
    assert s.tasks()[0]["error_code"] == "INVALID_QUESTION"
    assert not a.calls
    assert s.db.execute("SELECT question FROM message_event").fetchone()[0] == "[超长输入已省略]"


@pytest.mark.parametrize(
    "change,auth,lock",
    [
        ({"send_mode": "dry_run"}, Authorization(True, "合成测试群"), True),
        ({"allow_send": False}, Authorization(True, "合成测试群"), True),
        ({}, Authorization(False, "合成测试群"), True),
        ({}, Authorization(True, ""), True),
        ({}, Authorization(True, "其他群"), True),
        ({}, Authorization(True, "合成测试群"), False),
    ],
)
def test_a17_independent_send_gates(rig, change, auth, lock):
    config = {"send_mode": "auto", "allow_send": True} | change
    e, a, s, _ = rig(**config)
    e.auth, e.lock_valid = auth, lambda: lock
    add(a, msg())
    e.tick()
    assert not a.calls
    assert s.tasks()[0]["status"] in {"READY", "SIMULATED"}


def test_a17_adapter_kind_gate(rig):
    e, a, s, _ = rig(send_mode="auto", allow_send=True)
    a.kind = "wxauto"
    add(a, msg())
    e.tick()
    assert not a.calls and s.tasks()[0]["status"] == "READY"


@pytest.mark.parametrize(
    "change",
    [
        {"chat_name": "另一个群"},
        {"chat_type": "friend"},
        {"binding_id": "other"},
        {"binding_epoch": "new"},
    ],
)
def test_a18_a19_target_or_epoch_change(rig, change):
    e, a, s, _ = rig(send_mode="manual")
    add(a, msg())
    e.tick()
    a.current = replace(a.current, **change)
    e.tick()
    assert s.state()["paused"] and not a.calls
    assert s.tasks()[0]["status"] == "CANCELLED"


def test_a20_pause_before_claim(rig):
    e, a, s, _ = rig(send_mode="manual", allow_send=True)
    add(a, msg())
    e.tick()
    s.approve(s.tasks()[0]["task_id"])
    assert s.pause() == 0
    e.dispatch()
    assert s.tasks()[0]["status"] == "CANCELLED" and not a.calls


def test_a21_pause_after_claim(rig):
    e, a, s, _ = rig(send_mode="auto", allow_send=True)
    inflight = []
    e.after_claim = lambda _: inflight.append(s.pause())
    add(a, msg("1"), msg("2"))
    e.tick()
    assert inflight == [1] and len(a.calls) == 1
    assert [t["status"] for t in s.tasks()] == ["OBSERVED_SENT", "CANCELLED"]


def test_a22_pause_resume_rebaseline(rig):
    e, a, s, _ = rig(send_mode="auto", allow_send=True)
    s.pause()
    add(a, msg("pause"))
    e.tick()
    s.resume()
    add(a, msg("before-baseline"))
    e.tick()
    assert not s.tasks()
    add(a, msg("fresh"))
    e.tick()
    assert len(s.tasks()) == len(a.calls) == 1


@pytest.mark.parametrize("error,echo", [(TimeoutError("sensitive"), True), (None, False)])
def test_a23_a24_unknown_no_retry_or_approve(rig, error, echo):
    e, a, s, _ = rig(send_mode="auto", allow_send=True)
    a.send_error, a.echo = error, echo
    add(a, msg())
    e.tick()
    task = s.tasks()[0]
    assert task["status"] == "UNKNOWN" and len(a.calls) == 1
    for _ in range(3):
        e.tick()
    with pytest.raises(ValueError, match="NOT_APPROVABLE"):
        s.approve(task["task_id"])
    assert len(a.calls) == 1
    assert "sensitive" not in str(s.tasks())


def test_a25_unique_self_echo(rig):
    e, a, s, _ = rig(send_mode="auto", allow_send=True)
    add(a, msg())
    e.tick()
    t = s.tasks()[0]
    assert t["status"] == "OBSERVED_SENT" and t["observed_at"]
    assert t["task_id"] in a.current.messages[-1].content
    assert a.current.messages[-1].attr == "self"


def test_a26_crash_recovery_subprocess(tmp_path):
    database = tmp_path / "crash.sqlite3"
    code = """
import os, sys
from wechat_cs.config import Config
from wechat_cs.storage import Store
from wechat_cs.adapters.fake import FakeWechatAdapter
from wechat_cs.engine import Engine
from wechat_cs.models import MessageObservation
from wechat_cs.policy import Authorization
c=Config(send_mode="auto", allow_send=True)
s=Store(sys.argv[1]); a=FakeWechatAdapter(); e=Engine(c,a,s,auth=Authorization(True,c.target))
e.start()
for i in range(2):
 e.ingest(a.current,MessageObservation(str(i),"friend","text","synthetic","#客服 q"))
e.after_claim=lambda _: os._exit(77)
e.dispatch()
"""
    proc = subprocess.run([sys.executable, "-c", code, str(database)], capture_output=True)
    assert proc.returncode == 77, proc.stderr.decode()
    s = Store(database)
    assert [t["status"] for t in s.tasks()] == ["SENDING", "READY"]
    a = FakeWechatAdapter()
    e = Engine(Config(), a, s)
    try:
        e.start()
        assert [t["status"] for t in s.tasks()] == ["UNKNOWN", "DRAFT"]
        e.tick()
        assert not a.calls and s.attempts() == 1
        for task in s.tasks():
            with pytest.raises(ValueError):
                s.approve(task["task_id"])
    finally:
        e.close()
        s.close()


def test_a27_expiry_interval_budget_persist(rig):
    e, a, s, clock = rig(send_mode="auto", allow_send=True, max_sends_per_run=1)
    add(a, msg("1"), msg("2"))
    e.tick()
    assert len(a.calls) == 1
    clock.advance(121)
    e.tick()
    assert s.tasks()[1]["status"] == "EXPIRED"
    s.start(e.config.binding_id, a.current.binding_epoch, "auto")
    assert s.attempts() == 1
    add(a, msg("3"))
    e.generation = s.state()["generation"]
    e.tick()
    assert len(a.calls) == 1


def test_a27_interval_virtual_clock(rig):
    e, a, s, clock = rig(send_mode="auto", allow_send=True)
    e.config = replace(e.config, min_send_interval_seconds=5)
    add(a, msg("1"), msg("2"))
    e.tick()
    assert len(a.calls) == 1
    clock.advance(5)
    e.tick()
    assert len(a.calls) == 2


def test_a28_global_lock_different_databases(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    one = instance_lock("wxauto", "a.sqlite3")
    with one:
        code = """
from wechat_cs.locking import instance_lock
from filelock import Timeout
try:
 with instance_lock("wxauto", "b.sqlite3"): raise SystemExit(9)
except Timeout: raise SystemExit(23)
"""
        result = subprocess.run([sys.executable, "-c", code], env=os.environ.copy())
        assert result.returncode == 23
        with pytest.raises(Timeout):
            instance_lock("wxauto", "b.sqlite3").acquire()
    with instance_lock("mock", tmp_path / "a.sqlite3"):
        with instance_lock("mock", tmp_path / "b.sqlite3"):
            pass


def test_delta_reappearing_old_id():
    d = Delta()

    def snap(messages):
        return ChatSnapshot("b", "e", "g", "group", messages)

    d.update(snap((msg("1"), msg("2"))))
    d.update(snap((msg("2"), msg("3"))))
    with pytest.raises(GapError, match="REUSED"):
        d.update(snap((msg("3"), msg("1"))))


def test_storage_late_generation_rejected(rig):
    e, a, s, _ = rig()
    task = s.accept("event", a.current, msg(), "q", "llm", 120, 50)
    s.db.execute("UPDATE runtime_state SET generation=generation+1")
    s.finish_draft(task, ReplyDraft("late"), "auto")
    assert s.task(task)["status"] == "CANCELLED" and not a.calls

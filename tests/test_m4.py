import json
import subprocess
import sys
import threading
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
from conftest import Clock, add, msg

from wechat_cs.adapters.wxauto_adapter import WxautoAdapter
from wechat_cs.cli import main
from wechat_cs.config import Config
from wechat_cs.engine import Engine
from wechat_cs.models import ReplyDraft, SendRequest
from wechat_cs.policy import Authorization
from wechat_cs.storage import Store


class FakeWeChat:
    def __init__(self):
        self.info = {"chat_name": "合成测试群", "chat_type": "group"}
        self.messages = []
        self.calls = []
        self.echo = True
        self.error = None
        self.on_send = None
        self.threads = []

    def ChatInfo(self):
        self.threads.append(threading.get_ident())
        return self.info

    def GetAllMessage(self):
        self.threads.append(threading.get_ident())
        return self.messages

    def SendMsg(self, msg):
        self.threads.append(threading.get_ident())
        self.calls.append(msg)
        if self.on_send:
            self.on_send()
        if self.error:
            raise self.error
        if self.echo:
            self.messages.append(
                SimpleNamespace(
                    id=f"echo-{len(self.calls)}",
                    attr="self",
                    type="text",
                    sender="same-name",
                    content=msg,
                )
            )
        return True


def make_adapter(**kwargs):
    sdk = FakeWeChat()
    clock = Clock()
    config = Config(adapter="wxauto", target_group="合成测试群")
    adapter = WxautoAdapter(
        config,
        factory=lambda: sdk,
        clock=clock,
        sleep=lambda _: None,
        lock_valid=lambda: True,
        **kwargs,
    )
    adapter.connect()
    snapshot = adapter.snapshot()
    request = SendRequest(
        "unique-task",
        config.binding_id,
        snapshot.binding_epoch,
        config.target,
        "[AI测试 #unique-task]\n测试答案",
        clock() + timedelta(seconds=120),
    )
    return adapter, sdk, clock, request


def test_a37_free_api_mapping_and_echo():
    a, sdk, _, request = make_adapter()
    sdk.messages = [
        SimpleNamespace(id="1", attr="friend", type="text", sender="同昵称", content="#客服 问题")
    ]
    snap = a.snapshot()
    assert snap.messages[0].sender_display == "同昵称"
    assert snap.messages[0].ui_id == "1" and snap.messages[0].source_time is None
    result = a.send_text(request)
    assert result.status == "OBSERVED_SENT" and len(sdk.calls) == 1
    assert set(sdk.threads) == {threading.get_ident()}
    a.close()
    assert a.wx is None and "wxauto4" not in sys.modules


@pytest.mark.parametrize(
    "change",
    [
        "missing-id",
        "missing-content",
        "invalid-sender",
        "duplicate-id",
        "not-list",
        "missing-info",
        "wrong-name",
        "wrong-type",
    ],
)
def test_a37_missing_fields_fail_closed(change):
    a, sdk, _, _ = make_adapter()
    raw = SimpleNamespace(id="1", attr="friend", type="text", sender="s", content="q")
    sdk.messages = [raw]
    if change == "missing-id":
        del raw.id
    elif change == "missing-content":
        del raw.content
    elif change == "invalid-sender":
        raw.sender = None
    elif change == "duplicate-id":
        sdk.messages.append(raw)
    elif change == "not-list":
        sdk.messages = None
    elif change == "missing-info":
        sdk.info = {}
    elif change == "wrong-name":
        sdk.info["chat_name"] = "other"
    else:
        sdk.info["chat_type"] = "friend"
    with pytest.raises(ValueError):
        a.snapshot()
    assert sdk.calls == []
    a.close()


def test_a37_unknown_source_is_not_guessed():
    a, sdk, _, _ = make_adapter()
    sdk.messages = [SimpleNamespace(id="1", type="text", content="#客服 q", sender="机器人")]
    assert a.snapshot().messages[0].attr == ""
    assert sdk.calls == []
    a.close()


@pytest.mark.parametrize(
    "case,expected",
    [
        ("sdk-error", "UNKNOWN"),
        ("no-echo", "UNKNOWN"),
        ("switch-after-send", "UNKNOWN"),
        ("expired", "NOT_ATTEMPTED"),
        ("wrong-epoch", "NOT_ATTEMPTED"),
        ("lost-lock", "NOT_ATTEMPTED"),
        ("switch-before-send", "NOT_ATTEMPTED"),
    ],
)
def test_a23_a24_a37_sdk_send_results(case, expected):
    a, sdk, clock, req = make_adapter()
    if case == "sdk-error":
        sdk.error = TimeoutError("SECRET")
    elif case == "no-echo":
        sdk.echo = False
    elif case == "switch-after-send":
        sdk.on_send = lambda: sdk.info.update(chat_name="other")
    elif case == "expired":
        clock.advance(121)
    elif case == "wrong-epoch":
        req = replace(req, binding_epoch="stale")
    elif case == "lost-lock":
        a.lock_valid = lambda: False
    else:
        sdk.info["chat_name"] = "other"
    result = a.send_text(req)
    assert result.status == expected
    assert len(sdk.calls) == (1 if expected == "UNKNOWN" else 0)
    assert "SECRET" not in str(result)
    a.close()


@pytest.mark.parametrize("gate", ["dry-run", "config", "runtime", "target", "mode", "lock"])
def test_a17_real_sdk_never_called_when_gate_missing(tmp_path, gate):
    a, sdk, clock, _ = make_adapter()
    c = Config(adapter="wxauto", target_group="合成测试群", send_mode="auto", allow_send=True)
    auth = Authorization(True, c.target)
    if gate == "dry-run":
        c = replace(c, send_mode="dry_run")
    elif gate == "config":
        c = replace(c, allow_send=False)
    elif gate == "runtime":
        auth = replace(auth, allow_send=False)
    elif gate == "target":
        auth = replace(auth, confirm_target="")
    elif gate == "mode":
        c = replace(c, adapter="mock")
    s = Store(tmp_path / "gates.sqlite3", clock)
    e = Engine(c, a, s, auth=auth, clock=clock, lock_valid=lambda: gate != "lock")
    try:
        e.start()
        sdk.messages.append(
            SimpleNamespace(id="new", attr="friend", type="text", sender="s", content="#客服 q")
        )
        e.tick()
        assert sdk.calls == []
        assert s.tasks()[0]["status"] in {"SIMULATED", "READY"}
    finally:
        e.close()
        s.close()


def test_a37_owner_thread_and_missing_api():
    a, sdk, _, _ = make_adapter()
    failures = []

    def worker():
        for fn in (a.connect, a.snapshot, a.close):
            try:
                fn()
            except RuntimeError as exc:
                failures.append(str(exc))

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert failures == ["UI_THREAD_REQUIRED"] * 3
    a.close()
    for factory in (
        lambda: object(),
        lambda: SimpleNamespace(
            ChatInfo=lambda: {}, GetAllMessage=lambda: [], SendMsg=lambda wrong: None
        ),
    ):
        adapter = WxautoAdapter(a.config, factory=factory, lock_valid=lambda: True)
        with pytest.raises(RuntimeError):
            adapter.connect()


def test_a36_cli_controls_and_terminal_approval(rig, tmp_path, capsys):
    e, a, s, _ = rig(send_mode="manual")
    add(a, msg())
    e.tick()
    db = s.db.execute("PRAGMA database_list").fetchone()[2]
    task = s.tasks()[0]["task_id"]
    # 控制进程使用真实 UTC，因此把合成任务有效期放到未来。
    s.db.execute("UPDATE reply_task SET expires_at='2099-01-01T00:00:00+00:00'")
    for args in (
        ["status"],
        ["tasks", "list"],
        ["tasks", "show", task],
        ["tasks", "approve", task],
        ["pause"],
        ["resume"],
        ["cleanup"],
        ["tasks", "list"],
    ):
        assert main([*args, "--db", db]) == 0
    assert s.task(task)["status"] == "CANCELLED"
    assert main(["tasks", "approve", task, "--db", db]) == 2
    assert main(["resume", "--db", db]) == 2
    assert main(["status", "--db", str(tmp_path / "absent")]) == 2
    assert not a.calls
    output = capsys.readouterr().out
    assert "inflight_cannot_retract" in output and "CANCELLED" in output


@pytest.mark.parametrize(
    "args",
    [
        ["run", "--max-sends", "0"],
        ["run", "--duration-seconds", "-1"],
        ["tasks", "approve"],
        ["bad-command"],
    ],
)
def test_a36_cli_invalid_args(args):
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2


def test_a01_a36_a38_cli_demo_doctor_help(tmp_path, capsys):
    report = tmp_path / "report.json"
    assert main(["doctor", "--adapter", "mock", "--report", str(report)]) == 0
    assert json.loads(report.read_text())["send_calls"] == 0
    assert main(["demo", "--report", str(report)]) == 0
    data = json.loads(report.read_text())
    assert data["events"] == data["simulated_send_calls"] == 1 and data["real_send_calls"] == 0
    assert "wxauto4" not in sys.modules
    for command in ([], ["run"], ["doctor"], ["pause"], ["resume"], ["tasks", "approve"]):
        with pytest.raises(SystemExit) as exc:
            main([*command, "--help"])
        assert exc.value.code == 0
    capsys.readouterr()


def test_a02_cli_config_and_platform_errors(tmp_path, capsys):
    assert main(["run", "--config", str(tmp_path / "absent")]) == 2
    assert main(["run", "--send-mode", "auto"]) == 2
    assert main(["run", "--adapter", "wxauto"]) == 2
    assert "Traceback" not in capsys.readouterr().out


def test_cli_finite_mock_run(tmp_path):
    config = tmp_path / "run.toml"
    config.write_text('[app]\ndatabase="' + (tmp_path / "run.sqlite3").as_posix() + '"\n')
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wechat_cs",
            "run",
            "--config",
            str(config),
            "--duration-seconds",
            "1",
        ],
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert '"status": "STOPPED"' in result.stdout


def test_storage_queue_expiry_recovery_and_cleanup(rig):
    e, a, s, clock = rig(send_mode="manual", max_pending_tasks=1)
    add(a, msg("1"), msg("2"))
    e.tick()
    assert len(s.tasks()) == 1
    task = s.tasks()[0]["task_id"]
    clock.advance(121)
    with pytest.raises(ValueError):
        s.approve(task)
    s.expire()
    assert s.task(task)["status"] == "EXPIRED"
    clock.advance(8 * 86400)
    assert s.cleanup(7) == 1 and s.task(task)["answer"] == ""
    assert s.db.execute("SELECT question FROM message_event").fetchone()[0] == ""
    assert not a.calls


def test_storage_claim_guards_and_transaction_rollback(rig):
    e, a, s, clock = rig(send_mode="manual")
    add(a, msg())
    e.tick()
    t = s.tasks()[0]["task_id"]
    assert not s.claim(t, 3, 0)
    s.approve(t)
    clock.advance(121)
    assert not s.claim(t, 3, 0) and s.task(t)["status"] == "EXPIRED"
    s.db.execute("UPDATE reply_task SET status='READY'")
    s.db.execute("UPDATE runtime_state SET generation=generation+1")
    assert not s.claim(t, 3, 0) and s.task(t)["status"] == "CANCELLED"
    with pytest.raises(ValueError):
        s.task("no-task")
    generation = s.state()["generation"]
    with pytest.raises(RuntimeError):
        with s.transaction():
            s.db.execute("UPDATE runtime_state SET generation=999")
            raise RuntimeError()
    assert s.state()["generation"] == generation
    with pytest.raises(ValueError):
        s.start("other-binding", "epoch", "dry_run")


def test_storage_interrupted_generation_and_rebind(rig):
    e, a, s, clock = rig()
    t = s.accept("unfinished", a.current, msg(), "q", "llm", 120, 50)
    s.start(e.config.binding_id, a.current.binding_epoch, "dry_run")
    assert s.task(t)["status"] == "DRAFT"
    assert s.task(t)["error_code"] == "INTERRUPTED_GENERATION"
    s.pause("REBIND_REQUIRED")
    s.rebind()
    assert not s.state()["paused"]
    with pytest.raises(ValueError):
        s.rebind()
    t = s.accept("late", a.current, msg("2"), "q", "llm", 120, 50)
    clock.advance(121)
    s.finish_draft(t, ReplyDraft("too late"), "auto")
    assert s.task(t)["status"] == "EXPIRED"


def test_engine_preflight_and_not_attempted(rig):
    e, a, s, _ = rig(send_mode="manual", allow_send=True)
    add(a, msg())
    e.tick()
    s.approve(s.tasks()[0]["task_id"])
    a.current = replace(a.current, chat_name="other")
    e.dispatch()
    assert s.state()["pause_reason"] == "PREFLIGHT_FAILED" and not a.calls


def test_engine_failed_before_ui_action(rig):
    e, a, s, _ = rig(send_mode="auto", allow_send=True)
    a.before_send = lambda: setattr(a, "current", replace(a.current, chat_name="other"))
    add(a, msg())
    e.tick()
    assert s.tasks()[0]["status"] == "FAILED" and not a.calls


def test_initial_failure_and_unstarted_tick(rig):
    e, a, s, _ = rig()
    e.started = False
    with pytest.raises(RuntimeError):
        e.tick()
    a.snapshots = iter([RuntimeError("READ_FAILED")])
    e.start()
    assert s.state()["paused"] and not a.calls


def test_pause_resume_race_during_ingestion(rig):
    e, a, s, _ = rig(send_mode="auto", allow_send=True)
    s.pause()
    s.resume()
    # 主循环尚未看到新 generation，不能把暂停期快照写成新事件。
    e.ingest(a.current, msg())
    assert s.tasks() == [] and a.calls == []
    e.tick()
    add(a, msg("after-baseline"))
    e.tick()
    assert len(a.calls) == 1


def test_run_deadline_no_next_send(rig):
    e, a, s, _ = rig(send_mode="auto", allow_send=True)
    times = iter([e.deadline - 1, e.deadline - 1, e.deadline + 1])
    e.monotonic = lambda: next(times)
    add(a, msg("1"), msg("2"))
    e.tick()
    assert len(a.calls) == 1 and s.tasks()[1]["status"] == "READY"


def test_deadline_during_preflight(rig):
    e, a, s, _ = rig(send_mode="auto", allow_send=True)
    times = iter([e.deadline - 1, e.deadline + 1])
    e.monotonic = lambda: next(times)
    add(a, msg())
    e.tick()
    assert not a.calls and s.tasks()[0]["status"] == "READY"


def test_cli_untrusted_exception_redaction(monkeypatch, capsys):
    from wechat_cs import cli

    def error(_):
        raise ValueError("TOPSECRETKEY")

    monkeypatch.setattr(cli, "diagnostic", error)
    assert cli.main(["doctor", "--adapter", "mock"]) == 2
    assert "TOPSECRETKEY" not in capsys.readouterr().out


def test_sdk_preexisting_echo_does_not_prove_new_send():
    a, sdk, _, req = make_adapter()
    sdk.messages = [
        SimpleNamespace(id="old-echo", attr="self", type="text", sender="self", content=req.text)
    ]
    a.snapshot()
    sdk.echo = False
    assert a.send_text(req).status == "UNKNOWN"
    assert len(sdk.calls) == 1
    a.close()


def test_startup_recovers_before_gui_connect_failure(rig, monkeypatch):
    e, a, s, _ = rig(send_mode="manual", allow_send=True)
    add(a, msg())
    e.tick()
    task = s.tasks()[0]["task_id"]
    s.approve(task)
    assert s.claim(task, 3, 0)

    def unavailable():
        raise RuntimeError("GUI_UNAVAILABLE")

    monkeypatch.setattr(a, "connect", unavailable)
    e.start()
    assert s.task(task)["status"] == "UNKNOWN"
    assert s.state()["paused"] and a.calls == []

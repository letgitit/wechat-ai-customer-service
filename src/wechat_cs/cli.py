import argparse
import json
import platform
import sys
import tempfile
import time
from dataclasses import replace
from importlib.metadata import version
from pathlib import Path

from .adapters.fake import FakeWechatAdapter
from .config import Config, load_config
from .engine import Engine
from .locking import instance_lock
from .models import MessageObservation, stamp, utcnow
from .policy import Authorization
from .replies import reply_provider
from .storage import Store


def emit(data, path=None):
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text + "\n", encoding="utf-8")
    print(text)


def positive(value):
    n = int(value)
    if n <= 0:
        raise argparse.ArgumentTypeError("必须为正整数")
    return n


def parser():
    p = argparse.ArgumentParser(description="单测试群客服 v0.1；默认 Mock / dry-run / fixed")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("run", "doctor"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--config")
        cmd.add_argument("--adapter", choices=["mock", "wxauto"])
        if name == "doctor":
            cmd.add_argument("--report")
        else:
            cmd.add_argument("--dry-run", action="store_true")
            cmd.add_argument("--send-mode", choices=["dry_run", "manual", "auto"])
            cmd.add_argument("--reply-engine", choices=["fixed", "faq", "llm"])
            cmd.add_argument("--allow-send", action="store_true")
            cmd.add_argument("--confirm-target", default="")
            cmd.add_argument("--allow-llm", action="store_true")
            cmd.add_argument("--max-sends", type=positive)
            cmd.add_argument("--duration-seconds", type=positive)
            cmd.add_argument(
                "--rebind", action="store_true", help="停止旧进程后，人工核验目标并重绑"
            )
    demo = sub.add_parser("demo")
    demo.add_argument("--scenario", default="examples/scenarios/basic.json")
    demo.add_argument("--report")
    for name in ("status", "pause", "resume", "cleanup"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--db", default=Config().database)
        if name == "cleanup":
            cmd.add_argument("--retention-days", type=positive, default=7)
    tasks = sub.add_parser("tasks").add_subparsers(dest="task_command", required=True)
    for name in ("list", "show", "approve"):
        cmd = tasks.add_parser(name)
        if name != "list":
            cmd.add_argument("task_id")
        cmd.add_argument("--db", default=Config().database)
    from .knowledge_cli import add_commands

    add_commands(sub)
    return p


def adapter_for(c, lock):
    if c.adapter == "mock":
        return FakeWechatAdapter(binding_id=c.binding_id, target=c.target)
    from .adapters.wxauto_adapter import WxautoAdapter

    return WxautoAdapter(c, lock_valid=lambda: lock.is_locked)


def diagnostic(c):
    data = {
        "status": "PASS",
        "adapter": c.adapter,
        "python": platform.python_version(),
        "os": platform.system(),
        "time": stamp(utcnow()),
        "send_calls": 0,
        "login_verified": False,
        "dependencies": {name: version(name) for name in ("httpx", "filelock")},
    }
    with instance_lock(c.adapter, c.database) as lock:
        a = adapter_for(c, lock)
        try:
            a.connect()
            snapshot = a.snapshot()
            data["group_verified"] = (
                snapshot.chat_type == "group" and snapshot.chat_name == c.target
            )
            data["wxauto4"] = getattr(a, "package_version", "NOT_INSTALLED_OR_USED")
            data["message_count"] = len(snapshot.messages)
        finally:
            a.close()
    return data


def demo(scenario):
    raw = json.loads(Path(scenario).read_text(encoding="utf-8"))
    c = replace(Config(), send_mode="auto", allow_send=True, min_send_interval_seconds=0)
    with tempfile.TemporaryDirectory(prefix="wechat-cs-demo-") as temp:
        s = Store(Path(temp) / "demo.sqlite3")
        a = FakeWechatAdapter()
        e = Engine(c, a, s, auth=Authorization(True, c.target))
        try:
            frames = raw["frames"]
            if not frames:
                raise ValueError("EMPTY_SCENARIO")
            for i, frame in enumerate(frames):
                a.current = replace(
                    a.current, messages=tuple(MessageObservation(**m) for m in frame)
                )
                if i == 0:
                    e.start()
                else:
                    e.tick()
            events = s.db.execute("SELECT count(*) FROM message_event").fetchone()[0]
            sends = len(a.calls)
            if events != raw["expected_events"] or sends != raw["expected_sends"]:
                raise ValueError("SCENARIO_ASSERTION_FAILED")
            return {
                "status": "PASS",
                "channel": "FAKE_ONLY",
                "time": stamp(utcnow()),
                "events": events,
                "tasks": len(s.tasks()),
                "simulated_send_calls": sends,
                "states": [t["status"] for t in s.tasks()],
                "real_send_calls": 0,
                "external_llm_calls": 0,
                "windows": "NOT_RUN",
            }
        finally:
            e.close()
            s.close()


def run(c, args):
    auth = Authorization(
        args.allow_send, args.confirm_target, args.allow_llm, args.max_sends, args.duration_seconds
    )
    if c.send_mode != "dry_run" and (
        not c.allow_send or not auth.allow_send or auth.confirm_target != c.target
    ):
        raise ValueError("SEND_NOT_AUTHORIZED; 需要配置开关、--allow-send 和精确 --confirm-target")
    # 模型权限校验先于 GUI 初始化。
    replies = reply_provider(c, allow_llm=auth.allow_llm)
    duration = min(c.run_duration_seconds, auth.duration_seconds or c.run_duration_seconds)
    with instance_lock(c.adapter, c.database) as lock:
        s = Store(c.database)
        a = adapter_for(c, lock)
        e = Engine(c, a, s, auth=auth, replies=replies, lock_valid=lambda: lock.is_locked)
        try:
            if args.rebind:
                if args.confirm_target != c.target:
                    raise ValueError("REBIND_TARGET_CONFIRMATION_REQUIRED")
                s.rebind()
            e.start()
            s.cleanup(c.retention_days)
            if s.state()["paused"] and s.state()["pause_reason"] != "MANUAL":
                raise ValueError("START_BLOCKED_REBIND_REQUIRED")
            deadline = time.monotonic() + duration
            while time.monotonic() < deadline:
                e.tick()
                if s.state()["paused"] and s.state()["pause_reason"] != "MANUAL":
                    raise ValueError("SAFETY_PAUSE_REBIND_REQUIRED")
                if c.send_mode != "dry_run" and s.attempts() >= e.budget:
                    break
                time.sleep(min(c.poll_interval_seconds, max(0, deadline - time.monotonic())))
            emit({"status": "STOPPED", "attempts": s.attempts(), "adapter": c.adapter})
        finally:
            e.close()
            s.close()


def control(args):
    if not Path(args.db).is_file():
        raise ValueError("DATABASE_NOT_FOUND; 先启动一次程序")
    s = Store(args.db)
    try:
        if args.command == "status":
            state = s.state()
            emit(
                {
                    "state": state,
                    "attempts": s.attempts(),
                    "inflight": sum(t["status"] == "SENDING" for t in s.tasks()),
                }
            )
        elif args.command == "pause":
            emit({"status": "PAUSED", "inflight_cannot_retract": s.pause()})
        elif args.command == "resume":
            s.resume()
            emit({"status": "RESUMED", "baseline_required": True})
        elif args.command == "cleanup":
            emit({"redacted_tasks": s.cleanup(args.retention_days)})
        elif args.task_command == "approve":
            s.approve(args.task_id)
            emit({"status": "APPROVED", "task_id": args.task_id})
        elif args.task_command == "show":
            emit(s.task(args.task_id))
        else:
            emit(
                [
                    {
                        k: t[k]
                        for k in (
                            "task_id",
                            "status",
                            "engine",
                            "needs_review",
                            "error_code",
                            "created_at",
                            "expires_at",
                        )
                    }
                    for t in s.tasks()
                ]
            )
    finally:
        s.close()


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command in {"doctor", "run"}:
            c = load_config(args.config)
            overrides = {
                k: getattr(args, k)
                for k in ("adapter", "send_mode", "reply_engine")
                if getattr(args, k, None) is not None
            }
            if getattr(args, "dry_run", False):
                overrides["send_mode"] = "dry_run"
            c = replace(c, **overrides)
            if args.command == "doctor":
                emit(diagnostic(c), args.report)
            else:
                run(c, args)
        elif args.command in {"kb", "answer", "eval"}:
            from .knowledge_cli import execute

            emit(execute(args), args.report)
        elif args.command == "demo":
            emit(demo(args.scenario), args.report)
        else:
            control(args)
        return 0
    except KeyboardInterrupt:
        emit({"status": "STOPPED", "reason": "OPERATOR_INTERRUPT"})
        return 130
    except Exception as exc:
        # 异常详情可能来自 HTTP/UI，不打印原始 exception、堆栈或输入参数。
        public_reasons = {
            "WINDOWS_NATIVE_PYTHON_311_REQUIRED",
            "WXAUTO_VERSION_NOT_VALIDATED",
            "FREE_API_MISSING",
            "SEND_SIGNATURE_MISMATCH",
            "DESKTOP_LOCK_REQUIRED",
            "LLM_NOT_AUTHORIZED",
            "LLM_CONFIG_OR_KEY_MISSING",
            "TASK_NOT_APPROVABLE",
            "STALE_TASK_REQUIRES_MANUAL_HANDLING",
            "TASK_NOT_FOUND",
            "START_BLOCKED_REBIND_REQUIRED",
            "SAFETY_PAUSE_REBIND_REQUIRED",
            "REBIND_TARGET_CONFIRMATION_REQUIRED",
            "DATABASE_BINDING_MISMATCH",
            "SCENARIO_ASSERTION_FAILED",
            "INVALID_FAQ",
            "AMBIGUOUS_FAQ",
        }
        reason = str(exc) if str(exc) in public_reasons else type(exc).__name__
        emit(
            {
                "status": "BLOCKED",
                "reason": reason,
                "action": "检查配置、平台、测试群绑定和运行授权；实机步骤见 README。",
            },
            getattr(args, "report", None),
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())

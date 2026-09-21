from dataclasses import replace

from conftest import add, msg

from wechat_cs.adapters.fake import FakeWechatAdapter
from wechat_cs.config import Config
from wechat_cs.engine import Engine
from wechat_cs.storage import Store


def test_a03_historical_baseline(tmp_path):
    a = FakeWechatAdapter()
    a.current = replace(a.current, messages=(msg("a"), msg("b")))
    s = Store(tmp_path / "baseline.sqlite3")
    e = Engine(Config(), a, s)
    try:
        e.start()
        for _ in range(10):
            e.tick()
        assert s.tasks() == [] and a.calls == []
    finally:
        e.close()
        s.close()


def test_a04_a05_a11_fake_roundtrip(rig):
    e, a, s, _ = rig(send_mode="auto", allow_send=True)
    add(a, msg("new"), msg("own", attr="self"), msg("chat", content="闲聊"))
    e.tick()
    for _ in range(10):
        e.tick()
    assert len(s.tasks()) == 1
    assert s.tasks()[0]["status"] == "OBSERVED_SENT"
    assert len(a.calls) == 1
    assert s.db.execute("SELECT count(*) FROM message_event").fetchone()[0] == 1


def test_a14_fixed_followup_dry_run(rig):
    e, a, s, _ = rig()
    add(a, msg(content="#客服"))
    e.tick()
    assert s.tasks()[0]["status"] == "SIMULATED"
    assert "补充" in s.tasks()[0]["answer"]
    assert a.calls == []

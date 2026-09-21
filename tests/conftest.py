import socket
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from wechat_cs.adapters.fake import FakeWechatAdapter
from wechat_cs.config import Config
from wechat_cs.engine import Engine
from wechat_cs.models import MessageObservation
from wechat_cs.policy import Authorization
from wechat_cs.storage import Store


class Clock:
    def __init__(self):
        self.now = datetime(2026, 9, 20, tzinfo=UTC)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


def msg(ui="1", content="#客服 测试", attr="friend", type="text", sender="合成成员"):
    return MessageObservation(ui, attr, type, sender, content, datetime(2026, 9, 20, tzinfo=UTC))


@pytest.fixture(autouse=True)
def no_network_or_gui(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("真实网络/GUI 不在离线测试授权内")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    import builtins

    real_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in {"wxauto4", "wxautox4"}:
            return denied()
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)


@pytest.fixture
def rig(tmp_path):
    engines = []

    def build(**changes):
        clock = Clock()
        c = replace(Config(), min_send_interval_seconds=0, **changes)
        adapter = FakeWechatAdapter(clock=clock, target=c.target)
        store = Store(tmp_path / f"test-{len(engines)}.sqlite3", clock)
        engine = Engine(c, adapter, store, clock=clock, auth=Authorization(True, c.target))
        engine.start()
        engines.append(engine)
        return engine, adapter, store, clock

    yield build
    for e in engines:
        e.close()
        e.store.close()


def add(adapter, *messages):
    adapter.current = replace(adapter.current, messages=adapter.current.messages + messages)

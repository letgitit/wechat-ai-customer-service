import threading
from dataclasses import replace
from uuid import uuid4

from ..models import (
    AdapterCapabilities,
    ChatSnapshot,
    MessageObservation,
    SendRequest,
    SendResult,
    utcnow,
)


class FakeWechatAdapter:
    kind = "mock"

    def __init__(
        self,
        snapshots=(),
        *,
        binding_id="local-test-001",
        target="合成测试群",
        clock=utcnow,
        echo=True,
        send_error=None,
    ):
        self.clock = clock
        self.current = ChatSnapshot(binding_id, uuid4().hex, target, "group")
        self.snapshots = iter(snapshots)
        self.echo = echo
        self.send_error = send_error
        self.calls: list[SendRequest] = []
        self.owner = threading.get_ident()
        self.reads = 0
        self.closed = False
        self.before_send = None

    def _owner(self):
        if threading.get_ident() != self.owner:
            raise RuntimeError("UI_THREAD_REQUIRED")

    def connect(self):
        self._owner()
        return AdapterCapabilities(self.kind)

    def snapshot(self):
        self._owner()
        self.reads += 1
        item = next(self.snapshots, self.current)
        if isinstance(item, Exception):
            raise item
        self.current = item
        return item

    def send_text(self, request):
        self._owner()
        if self.before_send:
            self.before_send()
        if (
            (request.binding_id, request.binding_epoch, request.expected_chat_name)
            != (self.current.binding_id, self.current.binding_epoch, self.current.chat_name)
            or self.current.chat_type != "group"
            or self.clock() >= request.expires_at
        ):
            return SendResult("NOT_ATTEMPTED", "TARGET_OR_EXPIRY")
        self.calls.append(request)
        if self.send_error:
            raise self.send_error
        if not self.echo:
            return SendResult("UNKNOWN", "NO_SELF_ECHO", self.clock())
        self.current = replace(
            self.current,
            messages=self.current.messages
            + (
                MessageObservation(
                    uuid4().hex, "self", "text", "测试机器人", request.text, self.clock()
                ),
            ),
        )
        return SendResult("OBSERVED_SENT", attempted_at=self.clock(), observed_at=self.clock())

    def close(self):
        self._owner()
        self.closed = True

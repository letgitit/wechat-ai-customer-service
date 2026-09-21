import inspect
import sys
import threading
import time
from importlib.metadata import version
from uuid import uuid4

from ..config import Config
from ..delta import Delta, GapError
from ..models import (
    AdapterCapabilities,
    ChatSnapshot,
    MessageObservation,
    SendRequest,
    SendResult,
    utcnow,
)


class WxautoAdapter:
    kind = "wxauto"

    def __init__(
        self,
        config: Config,
        *,
        factory=None,
        clock=utcnow,
        sleep=time.sleep,
        lock_valid=lambda: False,
    ):
        self.config, self.factory, self.clock = config, factory, clock
        self.sleep, self.lock_valid = sleep, lock_valid
        self.owner = threading.get_ident()
        self.wx = None
        self.epoch = uuid4().hex
        self.last = None
        self.package_version = "injected-contract-double"

    def _guard(self):
        if threading.get_ident() != self.owner:
            raise RuntimeError("UI_THREAD_REQUIRED")
        if not self.lock_valid():
            raise RuntimeError("DESKTOP_LOCK_REQUIRED")

    def connect(self):
        self._guard()
        factory = self.factory
        if factory is None:
            if sys.platform != "win32" or sys.version_info[:2] != (3, 11):
                raise RuntimeError("WINDOWS_NATIVE_PYTHON_311_REQUIRED")
            self.package_version = version("wxauto4")
            if self.package_version != "41.1.7":
                raise RuntimeError("WXAUTO_VERSION_NOT_VALIDATED")
            from wxauto4 import WeChat

            factory = WeChat
        self.wx = factory()
        for name in ("ChatInfo", "GetAllMessage", "SendMsg"):
            if not callable(getattr(self.wx, name, None)):
                raise RuntimeError("FREE_API_MISSING")
        if "msg" not in inspect.signature(self.wx.SendMsg).parameters:
            raise RuntimeError("SEND_SIGNATURE_MISMATCH")
        return AdapterCapabilities(self.kind)

    def _info(self):
        data = self.wx.ChatInfo()
        if (
            not isinstance(data, dict)
            or data.get("chat_type") != "group"
            or data.get("chat_name") != self.config.target_group
        ):
            raise GapError("TARGET_MISMATCH")
        return data["chat_name"], data["chat_type"]

    def snapshot(self):
        self._guard()
        before = self._info()
        raw = self.wx.GetAllMessage()
        if not isinstance(raw, list):
            raise GapError("INVALID_SNAPSHOT")
        now = self.clock()
        messages = []
        for item in raw[-self.config.snapshot_limit :]:
            ui_id = getattr(item, "id", None)
            content = getattr(item, "content", None)
            if not isinstance(ui_id, str) or not ui_id or not isinstance(content, str):
                raise GapError("MESSAGE_FIELDS_MISSING")
            # 未知来源绝不按昵称猜测；保留它作为窗口差分锚点，业务层忽略。
            attr, kind = getattr(item, "attr", ""), getattr(item, "type", "")
            sender = getattr(item, "sender", "")
            if not all(isinstance(v, str) for v in (attr, kind, sender)):
                raise GapError("MESSAGE_FIELDS_INVALID")
            messages.append(MessageObservation(ui_id, attr, kind, sender, content, now))
        if before != self._info():
            raise GapError("TARGET_CHANGED_DURING_READ")
        snap = ChatSnapshot(self.config.binding_id, self.epoch, *before, tuple(messages), now)
        check = Delta()
        check.update(snap)  # 即使初始快照也拒绝 ID 碰撞。
        self.last = snap
        return snap

    def send_text(self, request: SendRequest):
        attempted = False
        attempted_at = None
        try:
            self._guard()
            previous = self.last
            snapshot = self.snapshot()
            if (
                (request.binding_id, request.binding_epoch, request.expected_chat_name)
                != (snapshot.binding_id, snapshot.binding_epoch, snapshot.chat_name)
                or self.clock() >= request.expires_at
                or previous is None
            ):
                return SendResult("NOT_ATTEMPTED", "STALE_REQUEST")
            delta = Delta()
            delta.update(previous)
            delta.update(snapshot)
            old_ids = {m.ui_id for m in snapshot.messages}
            self._guard()
            self._info()
            if self.clock() >= request.expires_at:
                return SendResult("NOT_ATTEMPTED", "EXPIRED")
            attempted = True
            attempted_at = self.clock()
            # 不传 who，不搜索或切换目标。SDK 返回真也不代表送达。
            self.wx.SendMsg(msg=request.text)
            for _ in range(3):
                observed = self.snapshot()
                delta.update(observed)
                if any(
                    m.ui_id not in old_ids
                    and m.attr == "self"
                    and m.type == "text"
                    and m.content == request.text
                    and request.task_id in m.content
                    for m in observed.messages
                ):
                    return SendResult(
                        "OBSERVED_SENT", attempted_at=attempted_at, observed_at=self.clock()
                    )
                self.sleep(0.2)
            return SendResult("UNKNOWN", "NO_SELF_ECHO", attempted_at)
        except Exception:
            return SendResult(
                "UNKNOWN" if attempted else "NOT_ATTEMPTED",
                "UI_SEND_OR_VERIFY_FAILURE",
                attempted_at,
            )

    def close(self):
        if threading.get_ident() != self.owner:
            raise RuntimeError("UI_THREAD_REQUIRED")
        # 仅释放引用，不能关闭操作者的微信窗口。
        self.wx = None

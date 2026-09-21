from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol


def utcnow() -> datetime:
    return datetime.now(UTC)


def stamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("时间必须带时区")
    return value.astimezone(UTC).isoformat()


@dataclass(frozen=True)
class MessageObservation:
    ui_id: str | None
    attr: str
    type: str
    sender_display: str
    content: str
    observed_at: datetime = field(default_factory=utcnow)
    source_time: str | None = None

    def identity(self) -> tuple:
        return self.ui_id, self.attr, self.type, self.sender_display, self.content


@dataclass(frozen=True)
class ChatSnapshot:
    binding_id: str
    binding_epoch: str
    chat_name: str
    chat_type: str
    messages: tuple[MessageObservation, ...] = ()
    captured_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class AdapterCapabilities:
    kind: str
    read: bool = True
    send: bool = True
    login_verified: bool = False


@dataclass(frozen=True)
class SendRequest:
    task_id: str
    binding_id: str
    binding_epoch: str
    expected_chat_name: str
    text: str
    expires_at: datetime


@dataclass(frozen=True)
class SendResult:
    status: Literal["OBSERVED_SENT", "NOT_ATTEMPTED", "UNKNOWN"]
    reason: str = ""
    attempted_at: datetime | None = None
    observed_at: datetime | None = None


@dataclass(frozen=True)
class ReplyDraft:
    text: str
    source_ids: tuple[str, ...] = ()
    needs_review: bool = False
    reason: str = ""


class WechatAdapter(Protocol):
    kind: str

    def connect(self) -> AdapterCapabilities: ...
    def snapshot(self) -> ChatSnapshot: ...
    def send_text(self, request: SendRequest) -> SendResult: ...
    def close(self) -> None: ...

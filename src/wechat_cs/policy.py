import re
from dataclasses import dataclass

from .config import Config
from .models import MessageObservation


@dataclass(frozen=True)
class Authorization:
    allow_send: bool = False
    confirm_target: str = ""
    allow_llm: bool = False
    max_sends: int | None = None
    duration_seconds: int | None = None


def question(message: MessageObservation) -> str | None:
    if message.attr != "friend" or message.type != "text":
        return None
    if not isinstance(message.content, str):
        return None
    match = re.match(r"^#客服(?:[\s:：]+|$)(.*)$", message.content, re.DOTALL)
    return match.group(1).strip() if match else None


def send_gate(config: Config, auth: Authorization, kind: str, lock_valid: bool) -> bool:
    if config.send_mode not in {"manual", "auto"}:
        return False
    if config.adapter != kind or not lock_valid:
        return False
    # Fake 模拟发送也必须有显式授权，避免模式混淆。
    return config.allow_send and auth.allow_send and auth.confirm_target == config.target

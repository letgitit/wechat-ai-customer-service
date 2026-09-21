import math
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Config:
    adapter: str = "mock"
    send_mode: str = "dry_run"
    reply_engine: str = "fixed"
    runtime_dir: str = ".runtime"
    database: str = ".runtime/wechat_cs.sqlite3"
    log_level: str = "INFO"
    binding_id: str = "local-test-001"
    target_group: str = ""
    expected_chat_type: str = "group"
    poll_interval_seconds: float = 2.0
    snapshot_limit: int = 200
    trigger_prefix: str = "#客服"
    max_question_chars: int = 1000
    max_reply_chars: int = 500
    reply_prefix: str = "[AI测试]"
    fixed_reply: str = "已收到。这是固定回复连通测试，不代表产品问题的正式解答。"
    faq_path: str = "examples/faq.json"
    question_mode: str = "independent"
    allow_send: bool = False
    max_sends_per_run: int = 3
    run_duration_seconds: int = 300
    min_send_interval_seconds: float = 5.0
    reply_ttl_seconds: int = 120
    require_manual_review_for_llm: bool = True
    max_pending_tasks: int = 50
    send_retry_count: int = 0
    retention_days: int = 7
    endpoint: str = ""
    model: str = ""
    api_key_env: str = "WECHAT_CS_LLM_API_KEY"
    allow_external_calls: bool = False
    connect_timeout_seconds: float = 5.0
    request_deadline_seconds: float = 30.0
    read_timeout_seconds: float = 10.0
    write_timeout_seconds: float = 10.0
    pool_timeout_seconds: float = 5.0
    max_response_bytes: int = 131072
    max_tokens: int = 500
    retry_count: int = 0

    def __post_init__(self):
        for f in fields(self):
            v = getattr(self, f.name)
            expected = f.type
            if expected is float:
                valid = type(v) in (float, int) and math.isfinite(v) and v >= 0
            else:
                valid = type(v) is expected
            if not valid:
                raise ValueError(f"配置类型或数值非法: {f.name}")
            if (
                expected in (int, float)
                and f.name not in {"min_send_interval_seconds", "send_retry_count", "retry_count"}
                and v <= 0
            ):
                raise ValueError(f"配置必须为正数: {f.name}")
        for name, allowed in {
            "adapter": {"mock", "wxauto"},
            "send_mode": {"dry_run", "manual", "auto"},
            "reply_engine": {"fixed", "faq", "llm"},
            "expected_chat_type": {"group"},
            "question_mode": {"independent"},
            "trigger_prefix": {"#客服"},
        }.items():
            if getattr(self, name) not in allowed:
                raise ValueError(f"配置枚举非法: {name}")
        if self.send_retry_count != 0 or self.retry_count != 0:
            raise ValueError("v0.1 禁止自动重试")
        if not self.require_manual_review_for_llm:
            raise ValueError("LLM 必须人工审核")
        if not self.binding_id or not self.fixed_reply.strip():
            raise ValueError("绑定和固定回复不得为空")
        if len(self.fixed_reply) > self.max_reply_chars:
            raise ValueError("固定回复超长")
        if self.adapter == "wxauto" and not self.target_group.strip():
            raise ValueError("wxauto 必须配置唯一测试群名")
        if self.endpoint:
            parsed = urlsplit(self.endpoint)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.fragment
                or parsed.query
            ):
                raise ValueError("endpoint 必须是无凭据、无查询参数的 HTTPS URL")

    @property
    def target(self) -> str:
        return self.target_group or "合成测试群"


def load_config(path: str | Path | None) -> Config:
    if path is None:
        return Config()
    with open(path, "rb") as f:
        data = tomllib.load(f)
    values = {}
    allowed = {f.name for f in fields(Config)}
    for section, items in data.items():
        if section not in {"app", "wechat", "service", "safety", "llm"} or not isinstance(
            items, dict
        ):
            raise ValueError("未知配置分组")
        for key, value in items.items():
            if key not in allowed or key in values:
                raise ValueError(f"未知或重复配置: {key}")
            values[key] = value
    return Config(**values)

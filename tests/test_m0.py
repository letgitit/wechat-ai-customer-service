import sys

import pytest

from wechat_cs.config import Config, load_config


def test_a01_a02_defaults():
    c = load_config(None)
    assert (c.adapter, c.send_mode, c.reply_engine) == ("mock", "dry_run", "fixed")
    assert not c.allow_send and not c.allow_external_calls
    assert load_config("config.example.toml") == c
    assert "wxauto4" not in sys.modules


@pytest.mark.parametrize(
    "values",
    [
        {"adapter": "bad"},
        {"adapter": "wxauto"},
        {"send_mode": "bad"},
        {"allow_send": "true"},
        {"max_sends_per_run": 0},
        {"send_retry_count": 1},
        {"require_manual_review_for_llm": False},
        {"poll_interval_seconds": float("nan")},
        {"endpoint": "http://bad"},
        {"endpoint": "https://key:secret@example.test"},
    ],
)
def test_a02_invalid(values):
    with pytest.raises(ValueError):
        Config(**values)

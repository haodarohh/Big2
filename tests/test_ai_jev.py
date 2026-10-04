"""Verify request_choice targets OpenRouter by default and a local laya server via env vars."""

import pytest

from big2 import ai_jev


class FakeResponse:
    """Minimal stand-in for requests.Response returning a fixed choice."""

    def raise_for_status(self):
        pass

    def json(self):
        return {"answers": {"move": {"choice": "opt_0"}}}


@pytest.fixture
def post(monkeypatch):
    """Capture requests.post calls; start each test with all AI env vars cleared."""
    for name in ("BIG2_AI_URL", "BIG2_AI_MODEL", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json})
        return FakeResponse()

    monkeypatch.setattr(ai_jev.requests, "post", fake_post)
    return calls


def test_default_uses_openrouter_with_key_and_jev_model(post, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    assert ai_jev.request_choice("s", {"opt_0": "a"}) == "opt_0"
    call = post[0]
    assert call["url"] == ai_jev.DECISIONS_URL
    assert call["headers"]["Authorization"] == "Bearer k"
    assert call["json"]["model"] == ai_jev.MODEL


def test_default_without_key_is_rejected(post):
    with pytest.raises(ai_jev.JevError, match="OPENROUTER_API_KEY"):
        ai_jev.request_choice("s", {"opt_0": "a"})
    assert post == []


def test_local_url_needs_no_key_and_omits_model(post, monkeypatch):
    monkeypatch.setenv("BIG2_AI_URL", "http://127.0.0.1:8000/v1/systemone")
    assert ai_jev.request_choice("s", {"opt_0": "a"}) == "opt_0"
    call = post[0]
    assert call["url"] == "http://127.0.0.1:8000/v1/systemone"
    assert "Authorization" not in call["headers"]
    assert "model" not in call["json"]


def test_model_env_overrides_for_local(post, monkeypatch):
    monkeypatch.setenv("BIG2_AI_URL", "http://127.0.0.1:8000/v1/systemone")
    monkeypatch.setenv("BIG2_AI_MODEL", "laya")
    ai_jev.request_choice("s", {"opt_0": "a"})
    assert post[0]["json"]["model"] == "laya"

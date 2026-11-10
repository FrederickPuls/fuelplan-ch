"""LLM-Client ohne Netz: Anthropic-SDK gegen MockTransport. Das SDK (anthropic 2.x) nutzt das Paket httpx2, nicht hx."""

from __future__ import annotations

import json

import httpx2 as hx
import pytest
from pydantic import BaseModel, Field

from fuelplan import config
from fuelplan.llm.client import (CreditsExhausted, LLMClient, LLMError, ProviderUnavailable, RateLimited, SchemaError,
                                 TruncatedResponse, estimate_cost)
from fuelplan.llm.schemas import AcceptanceRecipeIdea
from fuelplan.runlog import read_usage, record_usage


class Small(BaseModel):
    name: str
    grams: int = Field(ge=1)


def _message(content: list[dict], *, cost: float | None = 0.00123, cache_read=0, cache_write=0, model="anthropic/claude-sonnet-5.5",
             stop_reason="end_turn"):
    usage = {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": cache_read, "cache_creation_input_tokens": cache_write}
    if cost is not None:
        usage["cost"] = cost
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": model, "content": content,
            "stop_reason": stop_reason, "stop_sequence": None, "usage": usage, "provider": "Anthropic"}


def _json_text(data) -> dict:
    return {"type": "text", "text": json.dumps(data, ensure_ascii=False)}


def make_client(handler, monkeypatch, provider="openrouter"):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    return LLMClient(provider=provider, http_client=hx.Client(transport=hx.MockTransport(handler)), max_retries=0)


def test_complete_json_sends_schema_cache_control_and_provider_routing(monkeypatch):
    seen = {}

    def handler(req: hx.Request):
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        seen["headers"] = dict(req.headers)
        return hx.Response(200, json=_message([_json_text({"name": "Reis", "grams": 80})]))

    c = make_client(handler, monkeypatch)
    res = c.complete_json(model=config.PLAN_MODEL, system="SYS", user="USER", schema=Small, max_tokens=50, label="plan", effort="low")
    assert res.data == Small(name="Reis", grams=80) and res.raw == {"name": "Reis", "grams": 80}
    assert seen["url"] == "https://openrouter.ai/api/v1/messages"
    b = seen["body"]
    assert b["system"][0]["cache_control"] == {"type": "ephemeral"} and b["system"][0]["text"] == "SYS"
    assert b["output_config"] == {"format": {"type": "json_schema", "schema": Small.model_json_schema()}, "effort": "low"}
    assert "tools" not in b and "tool_choice" not in b
    assert b["provider"] == {"only": ["anthropic"]} and b["max_tokens"] == 50
    assert seen["headers"]["x-title"] == "fuelplan-ch" and "test-key" not in json.dumps(res.usage.to_dict())
    u = res.usage
    assert u.cost_usd == 0.00123 and u.cost_source == "openrouter" and u.provider == "Anthropic"
    assert u.input_tokens == 100 and u.output_tokens == 20 and u.attempts == 1 and u.label == "plan"


def test_retry_once_on_invalid_schema_then_success(monkeypatch):
    calls = []

    def handler(req):
        calls.append(json.loads(req.content))
        if len(calls) == 1:
            return hx.Response(200, json=_message([_json_text({"name": "Reis", "grams": 0})]))
        return hx.Response(200, json=_message([_json_text({"name": "Reis", "grams": 80})]))

    res = make_client(handler, monkeypatch).complete_json(model="m", system="s", user="u", schema=Small, max_tokens=10)
    assert res.data.grams == 80 and res.usage.attempts == 2
    assert res.usage.input_tokens == 200 and res.usage.cost_usd == pytest.approx(0.00246)
    second = calls[1]["messages"]
    assert second[1]["role"] == "assistant" and '"grams": 0' in second[1]["content"]
    assert second[2]["role"] == "user" and "Ungültig" in second[2]["content"]


# --- Schritt 10: abgeschnittene Antwort → frisch mit doppeltem max_tokens --------------------------------------

TRUNCATED = {"type": "text", "text": '{"name": "Reis", "gra'}


def test_max_tokens_retries_fresh_with_doubled_limit(monkeypatch):
    calls = []

    def handler(req):
        calls.append(json.loads(req.content))
        if len(calls) == 1:
            return hx.Response(200, json=_message([TRUNCATED], stop_reason="max_tokens"))
        return hx.Response(200, json=_message([_json_text({"name": "Reis", "grams": 80})]))

    res = make_client(handler, monkeypatch).complete_json(model="m", system="s", user="u", schema=Small, max_tokens=1000)
    assert res.data.grams == 80 and res.usage.attempts == 2 and res.usage.stop_reason == "end_turn"
    assert calls[0]["max_tokens"] == 1000 and calls[1]["max_tokens"] == 2000
    assert calls[1]["messages"] == [{"role": "user", "content": "u"}]  # frisch: kein abgeschnittener Text, keine Korrekturbitte
    assert len(res.usage.notes) == 1 and "abgeschnitten bei max_tokens=1000" in res.usage.notes[0] and "max_tokens=2000" in res.usage.notes[0]
    assert res.usage.input_tokens == 200  # beide Versuche gezählt


def test_max_tokens_retry_capped_by_config(monkeypatch):
    monkeypatch.setattr(config, "MAX_TOKENS_CAP", 1500)
    calls = []

    def handler(req):
        calls.append(json.loads(req.content))
        if len(calls) == 1:
            return hx.Response(200, json=_message([TRUNCATED], stop_reason="max_tokens"))
        return hx.Response(200, json=_message([_json_text({"name": "Reis", "grams": 80})]))

    make_client(handler, monkeypatch).complete_json(model="m", system="s", user="u", schema=Small, max_tokens=1000)
    assert [c["max_tokens"] for c in calls] == [1000, 1500]


def test_max_tokens_twice_raises_truncated(monkeypatch):
    calls = []
    handler = lambda req: (calls.append(1), hx.Response(200, json=_message([TRUNCATED], stop_reason="max_tokens")))[1]
    with pytest.raises(TruncatedResponse, match="max_tokens=2000"):
        make_client(handler, monkeypatch).complete_json(model="m", system="s", user="u", schema=Small, max_tokens=1000)
    assert len(calls) == 2  # kein dritter Versuch, keine Korrekturbitte mit abgeschnittenem Text


def test_max_tokens_at_cap_raises_immediately(monkeypatch):
    monkeypatch.setattr(config, "MAX_TOKENS_CAP", 1000)
    calls = []
    handler = lambda req: (calls.append(1), hx.Response(200, json=_message([TRUNCATED], stop_reason="max_tokens")))[1]
    with pytest.raises(TruncatedResponse):
        make_client(handler, monkeypatch).complete_json(model="m", system="s", user="u", schema=Small, max_tokens=1000)
    assert len(calls) == 1


def test_schema_error_after_fresh_retry_still_corrects_once(monkeypatch):
    """Nach dem frischen Versuch bleibt die Korrekturbitte für Schema-Fehler erhalten (höchstens 3 Requests)."""
    calls = []

    def handler(req):
        calls.append(json.loads(req.content))
        if len(calls) == 1:
            return hx.Response(200, json=_message([TRUNCATED], stop_reason="max_tokens"))
        if len(calls) == 2:
            return hx.Response(200, json=_message([_json_text({"name": "Reis", "grams": 0})]))
        return hx.Response(200, json=_message([_json_text({"name": "Reis", "grams": 80})]))

    res = make_client(handler, monkeypatch).complete_json(model="m", system="s", user="u", schema=Small, max_tokens=1000)
    assert res.data.grams == 80 and res.usage.attempts == 3 and len(res.usage.notes) == 2
    assert calls[2]["max_tokens"] == 2000 and calls[2]["messages"][1]["role"] == "assistant" and "Ungültig" in calls[2]["messages"][2]["content"]


def test_effort_omitted_when_not_given(monkeypatch):
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return hx.Response(200, json=_message([_json_text({"name": "Reis", "grams": 80})]))

    make_client(handler, monkeypatch).complete_json(model="m", system="s", user="u", schema=Small, max_tokens=10)
    assert "effort" not in seen["body"]["output_config"]
    make_client(handler, monkeypatch).complete_text(model="m", system="s", user="u", max_tokens=10)
    assert "output_config" not in seen["body"]


def test_usage_captures_thinking_and_stop_reason_and_notes(monkeypatch):
    calls = []

    def handler(req):
        calls.append(1)
        body = _message([_json_text({"name": "Reis", "grams": 0 if len(calls) == 1 else 80})])
        body["usage"]["output_tokens_details"] = {"thinking_tokens": 7}
        return hx.Response(200, json=body)

    res = make_client(handler, monkeypatch).complete_json(model="m", system="s", user="u", schema=Small, max_tokens=10)
    assert res.usage.thinking_tokens == 14 and res.usage.stop_reason == "end_turn"
    assert len(res.usage.notes) == 1 and "Versuch 1" in res.usage.notes[0]


def test_schema_error_after_two_invalid_answers(monkeypatch):
    handler = lambda req: hx.Response(200, json=_message([_json_text({"name": "x"})]))
    with pytest.raises(SchemaError):
        make_client(handler, monkeypatch).complete_json(model="m", system="s", user="u", schema=Small, max_tokens=10)


def test_non_json_answer_raises_schema_error(monkeypatch):
    handler = lambda req: hx.Response(200, json=_message([{"type": "text", "text": "hallo"}]))
    with pytest.raises(SchemaError, match="kein gültiges JSON"):
        make_client(handler, monkeypatch).complete_json(model="m", system="s", user="u", schema=Small, max_tokens=10)


@pytest.mark.parametrize("status,exc,needle", [(402, CreditsExhausted, "Guthaben"), (429, RateLimited, "Rate Limit"),
                                               (529, ProviderUnavailable, "nicht verfügbar"), (401, LLMError, "Key")])
def test_http_errors_translated(monkeypatch, status, exc, needle):
    handler = lambda req: hx.Response(status, json={"error": {"type": "x", "message": "detail"}})
    with pytest.raises(exc, match=needle):
        make_client(handler, monkeypatch).complete_text(model="m", system="s", user="u", max_tokens=5)


def test_anthropic_provider_uses_direct_api_and_estimates_cost(monkeypatch):
    seen = {}

    def handler(req):
        seen["url"] = str(req.url); seen["body"] = json.loads(req.content)
        return hx.Response(200, json=_message([{"type": "text", "text": "OK"}], cost=None, cache_read=1000, model="anthropic/claude-sonnet-5.5"))

    text, u = make_client(handler, monkeypatch, provider="anthropic").complete_text(model="anthropic/claude-sonnet-5.5", system="s", user="u", max_tokens=5)
    assert text == "OK" and seen["url"] == "https://api.anthropic.com/v1/messages" and "provider" not in seen["body"]
    assert u.cost_source.startswith("estimate") and u.cost_usd == pytest.approx(estimate_cost("anthropic/claude-sonnet-5.5", 100, 20, 1000, 0))
    assert u.cache_read_tokens == 1000


def test_unknown_provider():
    with pytest.raises(ValueError):
        LLMClient(provider="foo")


def test_estimate_cost_known_and_unknown_model():
    assert estimate_cost("anthropic/claude-sonnet-5.5", 1_000_000, 0, 0, 0) == 2.0
    assert estimate_cost("unknown", 1, 1, 1, 1) is None


def test_usage_log_roundtrip(tmp_path, monkeypatch):
    handler = lambda req: hx.Response(200, json=_message([{"type": "text", "text": "OK"}]))
    _, u = make_client(handler, monkeypatch).complete_text(model="m", system="s", user="u", max_tokens=5, label="t")
    path = tmp_path / "usage.jsonl"
    record_usage(u, path, run_dir="runs/x")
    rows = read_usage(path)
    assert len(rows) == 1 and rows[0]["label"] == "t" and rows[0]["run_dir"] == "runs/x" and rows[0]["total_tokens"] == 120


def test_test_schema_is_valid_json_schema():
    s = AcceptanceRecipeIdea.model_json_schema()
    assert s["type"] == "object" and "ingredients" in s["properties"]

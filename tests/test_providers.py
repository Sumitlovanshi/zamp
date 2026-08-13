"""Provider dispatch and the Gemini extraction path.

The architectural claim being protected: swapping the vision provider can
never change verification — both providers emit the same Ledger contract,
and verdicts come only from the network-free solver. These tests exercise
the dispatch rules and the Gemini path end to end against a mock transport,
so CI needs neither vendor.
"""

import json

import httpx
import pytest

from tallyproof.extract import vlm


# ---------------------------------------------------------------- dispatch
def test_no_keys_means_no_provider(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("TALLYPROOF_PROVIDER", raising=False)
    assert vlm.configured_provider() is None
    with pytest.raises(vlm.ExtractionError) as e:
        vlm.extract(b"", "image/jpeg", "t")
    assert e.value.kind == "no_key"


def test_anthropic_wins_when_both_configured(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.delenv("TALLYPROOF_PROVIDER", raising=False)
    assert vlm.configured_provider() == "anthropic"


def test_gemini_only_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.delenv("TALLYPROOF_PROVIDER", raising=False)
    assert vlm.configured_provider() == "gemini"


def test_forced_provider_without_its_key_is_none(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("TALLYPROOF_PROVIDER", "gemini")
    assert vlm.configured_provider() is None  # forced provider lacks a key: honest None


# ---------------------------------------------------------------- gemini path
def gemini_response(payload: dict) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]}


def test_gemini_extraction_end_to_end(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-g")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key_header"] = request.headers.get("x-goog-api-key")
        body = json.loads(request.content)
        seen["schema"] = body["generationConfig"]["responseSchema"]["type"]
        return httpx.Response(200, json=gemini_response({
            "merchant": "cafe", "currency_hint": None,
            "rows": [{"name": "espresso", "qty": "1", "unitprice": None, "price": "10,000"}],
            "subtotal": "10,000", "tax": None, "service": None, "discount": None,
            "total": None, "cash": None, "change": None, "menuqty": None,
        }))

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client",
                        lambda **kw: real_client(transport=transport, **kw))
    led = vlm._extract_gemini(b"imgbytes", "image/jpeg", "t1")
    assert seen["key_header"] == "test-g"
    assert "key=" not in seen["url"]  # secrets never travel in the URL
    assert seen["schema"] == "OBJECT"
    assert led.rows[0].price.surface == "10,000"
    assert led.subtotal.surface == "10,000"

    # the same ledger flows into the same solver — provider cannot touch verdicts
    from tallyproof.core.solver import decide
    assert decide(led).doc_verdict == "TIES_OUT"


def test_gemini_429_maps_to_rate_limited(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-g")
    monkeypatch.setattr(vlm, "MAX_ATTEMPTS", 2)
    monkeypatch.setattr(vlm.time, "sleep", lambda s: None)
    transport = httpx.MockTransport(lambda req: httpx.Response(429, json={}))
    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client",
                        lambda **kw: real_client(transport=transport, **kw))
    with pytest.raises(vlm.ExtractionError) as e:
        vlm._extract_gemini(b"x", "image/jpeg", "t")
    assert e.value.kind == "rate_limited"


def test_gemini_safety_block_is_api_error_without_retry(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-g")
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"candidates": []})

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client",
                        lambda **kw: real_client(transport=transport, **kw))
    with pytest.raises(vlm.ExtractionError) as e:
        vlm._extract_gemini(b"x", "image/jpeg", "t")
    assert e.value.kind == "api_error"
    assert len(calls) == 1  # malformed output is not retried into quota burn

"""Regression tests for the review-confirmed hardening fixes.

Each test encodes a specific attack or race the first review round found;
if any of these start failing, one of those holes has been reopened.
"""

import io
import threading

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tallyproof.app import limits, main
from tallyproof.app.limits import Budget, RateLimiter
from tallyproof.app.store import DocRecord, Store
from tallyproof.core.ledger import Cell, Ledger, make_row
from tallyproof.core.solver import decide


@pytest.fixture()
def client():
    return TestClient(main.app)


def tiny_jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (60, 90), "white").save(buf, format="JPEG")
    return buf.getvalue()


# ---- finding 1: layer-0 PROVEN note must not claim an unrun check --------
def test_layer0_proven_note_is_layer_accurate():
    """rows 6,5 + subtotal 6: ties out at layer 0, but re-reading '5'→6 with
    membership {row1} would ALSO balance — so the note must not claim
    alternative readings were checked."""
    cert = decide(Ledger(
        doc_id="t",
        rows=(make_row(0, price="6"), make_row(1, price="5")),
        subtotal=Cell("totals.subtotal", "6"),
    ))
    assert cert.doc_verdict == "TIES_OUT"
    note = cert.cells["totals.subtotal"].note
    assert "no alternative reading" not in note
    assert "precedence" in note  # states the lexicographic prior instead


# ---- finding 2: client IP from the platform edge, not the socket peer ----
def test_rate_limit_keys_on_forwarded_ip(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(main.vlm, "extract", lambda img, mt, doc_id: Ledger(
        doc_id=doc_id, rows=(make_row(0, price="1,000"),),
        subtotal=Cell("totals.subtotal", "1,000")))
    # drain one forwarded identity completely
    for _ in range(limits.BURST):
        r = client.post("/upload", files={"file": ("r.jpg", tiny_jpeg(), "image/jpeg")},
                        headers={"X-Forwarded-For": "203.0.113.7"}, follow_redirects=False)
        assert r.status_code in (303, 429)
    r = client.post("/upload", files={"file": ("r.jpg", tiny_jpeg(), "image/jpeg")},
                    headers={"X-Forwarded-For": "203.0.113.7"}, follow_redirects=False)
    assert r.status_code == 429
    # a different end user behind the same proxy still has quota
    r = client.post("/upload", files={"file": ("r.jpg", tiny_jpeg(), "image/jpeg")},
                    headers={"X-Forwarded-For": "198.51.100.9"}, follow_redirects=False)
    assert r.status_code == 303
    limits.LIMITER._buckets.clear()


# ---- finding 3: reserve is atomic; aborts refund --------------------------
def test_budget_reserve_atomic_under_threads():
    b = Budget()
    import tallyproof.app.limits as L
    old = L.DAILY_MODEL_BUDGET
    L.DAILY_MODEL_BUDGET = 10
    try:
        wins = []
        def worker():
            if b.reserve():
                wins.append(1)
        threads = [threading.Thread(target=worker) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(wins) == 10  # never over budget, no matter the interleaving
    finally:
        L.DAILY_MODEL_BUDGET = old


def test_failed_upload_refunds_quota(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    ip = "203.0.113.55"
    before_budget = limits.BUDGET.remaining
    # garbage uploads (415) must not eat the visitor's tokens or the budget
    for _ in range(limits.BURST + 3):
        r = client.post("/upload", files={"file": ("x.jpg", b"not an image", "image/jpeg")},
                        headers={"X-Forwarded-For": ip})
        assert r.status_code == 415  # never 429: the token was refunded
    assert limits.BUDGET.remaining == before_budget
    limits.LIMITER._buckets.clear()


def test_rate_limiter_burst_exact_under_threads():
    rl = RateLimiter()
    results = []
    def worker():
        ok, _ = rl.reserve("1.2.3.4")
        results.append(ok)
    threads = [threading.Thread(target=worker) for _ in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(results) == limits.BURST  # exactly the burst, never more


# ---- finding 4: pixel cap enforced at our threshold, not PIL's 2x --------
def test_oversize_pixels_rejected_before_decode(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(main.Image, "MAX_IMAGE_PIXELS", 1_000_000)
    buf = io.BytesIO()
    Image.new("RGB", (1300, 900), "white").save(buf, format="PNG")  # 1.17MP > cap
    r = client.post("/upload", files={"file": ("big.png", buf.getvalue(), "image/png")})
    assert r.status_code == 415
    limits.LIMITER._buckets.clear()


# ---- finding 5: cookieless churn cannot evict document-holding sessions ---
def test_session_cap_only_counts_document_holders():
    store = Store()
    owner = store.session(None)
    store.add(owner, DocRecord(doc_id="d1", name="mine", ledger={}, certificate={},
                               image=b"", media_type="image/jpeg"))
    for _ in range(2000):  # a cookieless GET flood mints sessions...
        store.session(None)
    assert store.stats()["sessions"] == 1  # ...but none of them occupy the cap
    assert store.session(owner.sid).docs["d1"].name == "mine"  # owner survives


# ---- extraction failure: token refunded, budget attempt stays spent -------
def test_extraction_failure_refunds_token_not_budget(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def boom(img, mt, doc_id):
        raise main.vlm.ExtractionError("api_error", "provider rejected the call")

    monkeypatch.setattr(main.vlm, "extract", boom)
    ip = "203.0.113.77"
    budget_before = limits.BUDGET.remaining
    for _ in range(limits.BURST + 2):  # more failures than the burst allows
        r = client.post("/upload", files={"file": ("r.jpg", tiny_jpeg(), "image/jpeg")},
                        headers={"X-Forwarded-For": ip})
        assert r.status_code == 502  # never 429: the visitor's token came back
    # every attempt burned budget — provider load is capped by attempts
    assert limits.BUDGET.remaining == budget_before - (limits.BURST + 2)
    limits.LIMITER._buckets.clear()
    limits.BUDGET._day = ""  # reset the day counter for other tests

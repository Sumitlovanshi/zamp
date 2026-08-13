"""End-to-end app tests: no network, no key, no model — the extractor is a
deterministic fixture, which is the point: everything below the extractor
is testable because verdicts never come from the model."""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tallyproof.app import limits
from tallyproof.app.main import app
from tallyproof.core.ledger import Cell, Ledger, make_row
from tallyproof.extract import vlm
from tallyproof.extract.vlm import ledger_from_payload


@pytest.fixture()
def client():
    return TestClient(app)


def tiny_jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (60, 90), "white").save(buf, format="JPEG")
    return buf.getvalue()


def fixture_ledger(doc_id: str) -> Ledger:
    return Ledger(
        doc_id=doc_id,
        rows=(make_row(0, name="americano", price="10,000"),
              make_row(1, name="croissant", price="15,000")),
        subtotal=Cell("totals.subtotal", "25,000"),
        tax=Cell("totals.tax", "2,500"),
        total=Cell("totals.total", "27,500"),
    )


# ---------------------------------------------------------------- gallery
def test_index_renders_tiles_and_evidence(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    r = client.get("/")
    assert r.status_code == 200
    # no key -> the upload affordance is honestly paused, not a dead end
    assert "Uploads are paused" in r.text
    for slug in ("proven", "repaired", "ambiguous", "unexplained", "no-structure", "misread"):
        assert f"/s/{slug}" in r.text
    assert "83.5%" in r.text  # the measured ambiguity census, on the landing page

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    r = client.get("/")
    assert "Photograph a receipt" in r.text  # live mode shows the camera


def test_sample_pages_render_every_verdict(client):
    for slug, marker in [
        ("proven", "26 of 27 cells proven"),
        ("repaired", "arithmetic requires"),
        ("ambiguous", "nothing gets certified"),
        ("unexplained", "The paper is wrong"),
        ("no-structure", "no redundancy"),
        ("misread", "Simulated misread"),
    ]:
        r = client.get(f"/s/{slug}")
        assert r.status_code == 200, slug
        assert marker in r.text, slug


def test_unknown_sample_404(client):
    assert client.get("/s/nope").status_code == 404


def test_sample_image_traversal_guarded(client):
    assert client.get("/samples/..%2Fpyproject.toml").status_code == 404
    assert client.get("/samples/cord-test-085.jpg").status_code == 200


# ---------------------------------------------------------------- upload path
def test_upload_without_key_is_honest_503(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    r = client.post("/upload", files={"file": ("r.jpg", tiny_jpeg(), "image/jpeg")})
    assert r.status_code == 503
    assert "gallery" in r.text.lower() or "sample" in r.text.lower()


def test_upload_full_journey_with_fixture_extractor(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(vlm, "extract", lambda img, mt, doc_id: fixture_ledger(doc_id))
    r = client.post("/upload", files={"file": ("cafe.jpg", tiny_jpeg(), "image/jpeg")},
                    follow_redirects=False)
    assert r.status_code == 303
    doc = client.get(r.headers["location"])
    assert doc.status_code == 200
    assert "review <b>0</b>" in doc.text.replace("Review", "review")  # everything proven
    # image endpoint serves the cleaned bytes back
    img = client.get(r.headers["location"] + "/image")
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
    # batch now carries the doc with census semantics
    batch = client.get("/batch")
    assert "cafe.jpg" in batch.text
    assert "27,500" in batch.text or "27500" in batch.text
    csv_out = client.get("/batch.csv").text
    assert "totals.total" in csv_out and "PROVEN" in csv_out


def test_upload_garbage_is_415(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    r = client.post("/upload", files={"file": ("evil.jpg", b"<html>not an image", "image/jpeg")})
    assert r.status_code == 415


def test_upload_oversize_is_413(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    big = b"\xff" * (9 * 1024 * 1024)
    r = client.post("/upload", files={"file": ("big.jpg", big, "image/jpeg")})
    assert r.status_code == 413


def test_empty_extraction_is_422_not_hallucination(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(vlm, "extract",
                        lambda img, mt, doc_id: Ledger(doc_id=doc_id))
    r = client.post("/upload", files={"file": ("cat.jpg", tiny_jpeg(), "image/jpeg")})
    assert r.status_code == 422
    assert "refuses to hallucinate" in r.text


def test_extractor_failure_is_502_not_500(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def boom(img, mt, doc_id):
        raise vlm.ExtractionError("timeout", "deadline exceeded")

    monkeypatch.setattr(vlm, "extract", boom)
    r = client.post("/upload", files={"file": ("r.jpg", tiny_jpeg(), "image/jpeg")})
    assert r.status_code == 502
    assert "deadline" in r.text


def test_rate_limit_429_with_retry_after(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    bucket = limits.LIMITER._buckets.setdefault("testclient", limits.Bucket())
    bucket.tokens = 0  # drain
    r = client.post("/upload", files={"file": ("r.jpg", tiny_jpeg(), "image/jpeg")})
    assert r.status_code == 429
    assert "Retry-After" in r.headers
    bucket.tokens = limits.BURST  # restore for other tests


def test_budget_exhausted_is_labelled_degraded(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(limits, "DAILY_MODEL_BUDGET", 0)
    limits.BUDGET._day = ""  # force roll with new budget
    r = client.post("/upload", files={"file": ("r.jpg", tiny_jpeg(), "image/jpeg")})
    assert r.status_code == 503
    assert "budget" in r.text.lower()
    limits.BUDGET._day = ""  # reset


# ---------------------------------------------------------------- misc
def test_expired_doc_message_owns_the_retention_policy(client):
    r = client.get("/d/doc-doesnotexist")
    assert r.status_code == 404
    assert "retention" in r.text


def test_status_and_health(client):
    assert client.get("/healthz").json()["ok"] is True
    assert client.get("/status").status_code == 200


def test_ledger_from_payload_handles_junk():
    led = ledger_from_payload(
        {"rows": [{"name": None, "qty": "2", "unitprice": None, "price": "1,000"},
                  "not-a-dict", {"name": "x", "qty": "", "unitprice": "  ", "price": None}],
         "subtotal": "2,000", "total": None, "merchant": 42},
        "t",
    )
    assert len(led.rows) == 2
    assert led.rows[0].price.surface == "1,000"
    assert led.rows[1].qty is None  # empty strings are absent, not cells
    assert led.subtotal.surface == "2,000"
    assert led.merchant == "42"

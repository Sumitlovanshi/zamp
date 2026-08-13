"""Tallyproof — the web surface.

Server-rendered, zero build step, no client JS beyond <details> elements.
The gallery is precomputed (samples/manifest.json), so the first
impression needs no model, no key and no luck; live uploads go through
the vision extractor and the same solver the eval suite runs.

Failure is a designed state, never a 500: rate limits carry Retry-After; a spent budget flips a labelled degraded
banner while the gallery keeps working; a cat photo gets an honest
INSUFFICIENT_STRUCTURE page showing what little was read.
"""

from __future__ import annotations

import io
import json
import re
import secrets
import time
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageOps

from ..core.solver import decide
from ..extract import vlm
from .limits import BUDGET, LIMITER
from .queries import batch_csv, batch_summary
from .store import SESSION_TTL_S, STORE, DocRecord

APP_DIR = Path(__file__).parent
ROOT = APP_DIR.parents[2]  # repo root: src/tallyproof/app -> src -> root
SAMPLES = json.loads((ROOT / "samples" / "manifest.json").read_text())
EVAL_PATH = ROOT / "eval" / "summary.json"
EVAL = json.loads(EVAL_PATH.read_text()) if EVAL_PATH.exists() else {}

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 40_000_000  # decompression-bomb guard

app = FastAPI(title="Tallyproof", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")


def _pretty_cell(cell_id: str) -> str:
    """Human display for a cell id, 1-based to match equation labels:
    row4.price -> 'line 5 · price'; totals.total -> 'total'."""
    if cell_id.startswith("row"):
        idx, field = cell_id[3:].split(".")
        return f"line {int(idx) + 1} · {field}"
    return cell_id.split(".", 1)[1].replace("menuqty", "item count")


_ROW_ID = re.compile(r"row(\d+)\.(qty|unitprice|price)")


def _pretty_ids(text: str) -> str:
    """Prettify machine cell ids wherever they appear in prose (component
    details), so on-screen numbering is 1-based everywhere at once."""
    return _ROW_ID.sub(lambda m: f"line {int(m.group(1)) + 1} · {m.group(2)}", text)


templates.env.filters["pretty_cell"] = _pretty_cell
templates.env.filters["pretty_ids"] = _pretty_ids

VERDICT_ORDER = ("REPAIRED", "AMBIGUOUS", "UNVERIFIED", "UNCONSTRAINED", "PROVEN")


def _ctx(request: Request, **kw) -> dict:
    sid = request.cookies.get("tp_sid")
    session = STORE.peek(sid)
    return {
        "request": request,
        "n_batch": len(session.docs) if session else 0,
        "budget_remaining": BUDGET.remaining,
        "have_key": vlm.configured_provider() is not None,
        "ttl_minutes": SESSION_TTL_S // 60,
        **kw,
    }


def _session(request: Request):
    return STORE.session(request.cookies.get("tp_sid"))


def _with_cookie(resp: Response, sid: str, request: Request) -> Response:
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    resp.set_cookie("tp_sid", sid, max_age=SESSION_TTL_S, httponly=True,
                    samesite="lax", secure=secure)
    return resp


def _sorted_cells(cert: dict) -> list[dict]:
    """Cells in display order: rows first by index, then the totals block."""
    def key(item):
        cid, _ = item
        if cid.startswith("row"):
            idx, field = cid[3:].split(".")
            return (0, int(idx), {"qty": 0, "unitprice": 1, "price": 2}[field])
        block_order = ["subtotal", "tax", "service", "discount",
                       "total", "cash", "change", "menuqty"]
        return (1, block_order.index(cid.split(".")[1]), 0)

    return [dict(cell, cell_id=cid) for cid, cell in sorted(cert["cells"].items(), key=key)]


def _headline_cell(cert: dict) -> str | None:
    """The cell whose proof panel opens by default: the story of the page."""
    for verdict in VERDICT_ORDER[:3]:
        for cid, cell in cert["cells"].items():
            if cell["verdict"] == verdict:
                return cid
    return None


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    s = _session(request)
    tiles = [
        {k: t[k] for k in ("slug", "title", "blurb", "image", "injected")}
        | {
            "verdict": t["certificate"]["doc_verdict"],
            "review": t["certificate"]["review_count"],
            "cells": len(t["certificate"]["cells"]),
        }
        for t in SAMPLES
    ]
    resp = templates.TemplateResponse(
        request, "index.html",
        _ctx(request, tiles=tiles, evidence=EVAL),
    )
    return _with_cookie(resp, s.sid, request)


@app.get("/s/{slug}", response_class=HTMLResponse)
def sample(request: Request, slug: str):
    tile = next((t for t in SAMPLES if t["slug"] == slug), None)
    if tile is None:
        return _error(request, 404, "No such sample.")
    cert = tile["certificate"]
    return templates.TemplateResponse(
        request, "doc.html",
        _ctx(
            request,
            title=tile["title"],
            cert=cert,
            cells=_sorted_cells(cert),
            open_cell=_headline_cell(cert),
            image_url=f"/samples/{tile['image']}",
            sample=tile,
            is_sample=True,
        ),
    )


@app.get("/samples/{name}")
def sample_image(name: str):
    path = (ROOT / "samples" / name).resolve()
    if path.parent != (ROOT / "samples").resolve() or not path.exists():
        return PlainTextResponse("not found", status_code=404)
    return Response(path.read_bytes(), media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=86400"})


def _clean_image(raw: bytes) -> tuple[bytes, str]:
    """Sniff, verify, strip EXIF (receipt photos carry GPS), bound size."""
    img = Image.open(io.BytesIO(raw))
    img.verify()  # structural check on the actual bytes, not the filename
    img = Image.open(io.BytesIO(raw))
    # PIL only *raises* at 2x MAX_IMAGE_PIXELS (warns below that), and
    # convert() allocates the full raster — enforce our cap ourselves,
    # from the lazily-parsed header, before any decode happens
    if img.size[0] * img.size[1] > Image.MAX_IMAGE_PIXELS:
        raise ValueError("image exceeds the pixel cap")
    img = ImageOps.exif_transpose(img)  # bake orientation, then drop metadata
    img = img.convert("RGB")
    img.thumbnail((2000, 2000))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=88)
    return out.getvalue(), "image/jpeg"


def _client_ip(request: Request) -> str:
    """Rightmost X-Forwarded-For hop — the entry appended by the platform
    edge (Railway/Fly/most PaaS), which a client cannot spoof.  The raw
    socket peer behind a proxy is the proxy itself, which would collapse
    the per-address limit into one shared global bucket."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


@app.post("/upload")
def upload(request: Request, file: UploadFile):
    # deliberately sync: FastAPI runs def handlers in its threadpool, so the
    # model call and PIL work never block the event loop for other visitors
    s = _session(request)
    ip = _client_ip(request)

    if vlm.configured_provider() is None:
        return _error(request, 503,
                      "No model key is configured, so live extraction is off. "
                      "The six sample receipts carry the full experience — "
                      "they never needed a model.")

    # reserve atomically at the gate; refund on every path that never
    # reaches the model (check-then-spend across a slow body read is a race)
    reserved, retry_after = LIMITER.reserve(ip)
    if not reserved:
        return _error(
            request, 429,
            f"Rate limit: 12 uploads/hour per address. Try again in ~{retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )
    if not BUDGET.reserve():
        LIMITER.refund(ip)
        return _error(request, 503,
                      "Today's model budget is spent — the honest failure mode "
                      "of a public demo funded by one person's API key. The "
                      "sample gallery still works completely; it never touches "
                      "the model.")

    def abort(code: int, message: str):
        LIMITER.refund(ip)
        BUDGET.refund()
        return _error(request, code, message)

    # read in bounded chunks and abort early — never buffer an unbounded body
    chunks, size = [], 0
    while chunk := file.file.read(1 << 20):
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            return abort(413, "Images up to 8 MB only.")
        chunks.append(chunk)
    raw = b"".join(chunks)
    try:
        image, media_type = _clean_image(raw)
    except Exception:  # noqa: BLE001 — hostile bytes may raise anything; the answer is always 415
        return abort(415,
                     "That file did not decode as an image (JPEG/PNG/WEBP). "
                     "PDFs and HEIC are out of scope — deliberately, see the "
                     "decisions log.")

    doc_id = f"doc-{secrets.token_urlsafe(6)}"
    try:
        ledger = vlm.extract(image, media_type, doc_id)
    except vlm.ExtractionError as e:
        msg = {
            "rate_limited": "The model provider rate-limited us mid-call. "
                            "Your quota was not consumed twice; retry shortly.",
            "timeout": "The model call exceeded its deadline. Retry once; "
                       "if it persists the provider is having a day.",
            "api_error": "The model call failed. Nothing was stored.",
        }.get(e.kind, "Extraction failed. Nothing was stored.")
        return _error(request, 502, msg)

    if not ledger.cells():
        return _error(
            request, 422,
            "No numerals found — this doesn't look like a receipt. Nothing "
            "was stored. (A blurry photo, a menu, or a cat all land here; "
            "the system refuses to hallucinate a plausible ledger.)")

    cert = decide(ledger)
    rec = DocRecord(
        doc_id=doc_id,
        name=file.filename or doc_id,
        ledger=ledger.to_dict(),
        certificate=cert.to_dict(),
        image=image,
        media_type=media_type,
    )
    STORE.add(s, rec)
    return _with_cookie(RedirectResponse(f"/d/{doc_id}", status_code=303), s.sid, request)


@app.get("/d/{doc_id}", response_class=HTMLResponse)
def doc(request: Request, doc_id: str):
    s = _session(request)
    rec = s.docs.get(doc_id)
    if rec is None:
        return _error(request, 404,
                      "Document not found — sessions live for an hour, then "
                      "everything is deleted. That is the retention policy "
                      "working, not a bug.")
    cert = rec.certificate
    resp = templates.TemplateResponse(
        request, "doc.html",
        _ctx(
            request,
            title=rec.name,
            cert=cert,
            cells=_sorted_cells(cert),
            open_cell=_headline_cell(cert),
            image_url=f"/d/{doc_id}/image",
            is_sample=False,
        ),
    )
    return _with_cookie(resp, s.sid, request)


@app.get("/d/{doc_id}/image")
def doc_image(request: Request, doc_id: str):
    s = _session(request)
    rec = s.docs.get(doc_id)
    if rec is None:
        return PlainTextResponse("expired", status_code=404)
    return Response(rec.image, media_type=rec.media_type,
                    headers={"Cache-Control": "private, max-age=3600"})


@app.get("/batch", response_class=HTMLResponse)
def batch(request: Request):
    s = _session(request)
    docs = sorted(s.docs.values(), key=lambda d: d.created)
    summary = batch_summary(docs) if docs else None
    resp = templates.TemplateResponse(
        request, "batch.html", _ctx(request, summary=summary, docs=docs)
    )
    return _with_cookie(resp, s.sid, request)


@app.get("/batch.csv")
def batch_export(request: Request):
    s = _session(request)
    docs = sorted(s.docs.values(), key=lambda d: d.created)
    return Response(
        batch_csv(docs),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=tallyproof.csv"},
    )


@app.get("/status", response_class=HTMLResponse)
def status(request: Request):
    provider = vlm.configured_provider()
    return templates.TemplateResponse(
        request, "status.html",
        _ctx(request, store=STORE.stats(),
             provider=provider,
             mode="live" if provider and BUDGET.remaining > 0 else "gallery-only"),
    )


@app.get("/healthz")
def healthz():
    return {"ok": True, "time": time.time()}


def _error(request: Request, code: int, message: str, headers: dict | None = None):
    resp = templates.TemplateResponse(
        request, "error.html", _ctx(request, code=code, message=message), status_code=code
    )
    for k, v in (headers or {}).items():
        resp.headers[k] = v
    return resp

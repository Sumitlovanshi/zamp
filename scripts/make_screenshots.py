"""Regenerate docs/screenshots/ — the visual walkthrough.

Launches the app twice (once with a placeholder key so the live-mode UI
renders, once without to show the designed gallery-only degradation),
captures every page full-height with headless Chromium, and writes an
illustrated index so the repo shows the product to people who will never
run it.

Requires the optional dev dependency:  pip install playwright
                                       playwright install chromium
Run:  .venv/bin/python scripts/make_screenshots.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
PORT = 8912

# (path, filename, caption) — the order tells the product's story
PAGES = [
    ("/", "01-landing",
     "The landing page: the claim, the camera, six sample tiles (one per honest "
     "verdict), and the measured evidence — every number regenerates from `make eval`."),
    ("/s/proven", "02-proven",
     "TIES_OUT: 26 of 27 cells proven by interlocking identities. The 27th — a cash "
     "line with no printed change to check against — is honestly UNCONSTRAINED."),
    ("/s/repaired", "03-repaired",
     "The aha: a real annotation error in CORD's published ground truth. `222.000` "
     "is struck through, repaired to `222,000`, and the proof panel is open — the "
     "identities that pinned it, and the statement that exactly one re-reading closes "
     "the residual."),
    ("/s/ambiguous", "04-ambiguous",
     "AMBIGUOUS: two row-groupings balance, so nothing is certified. Refusing to "
     "choose is the correct answer — the callout says why."),
    ("/s/unexplained", "05-unexplained",
     "UNEXPLAINED: every reading of every cell was tried; none closes the residual. "
     "The extraction agrees with the pixels. The paper itself is wrong — proven, "
     "not guessed."),
    ("/s/no-structure", "06-no-structure",
     "NO_STRUCTURE: a receipt with no redundancy. Nothing can be proven, and every "
     "cell says so instead of wearing a fake confidence score."),
    ("/s/misread", "07-misread",
     "Simulated OCR misread, declared on the page (one glyph swapped within the "
     "confusion set). Exactly one re-reading closes the residual, so it is repaired — "
     "original shown, never silently overwritten."),
    ("/status", "08-status",
     "The status page: mode, budget, sessions, retention — the operational truth a "
     "visitor can check."),
    ("/d/expired-doc", "09-retention-404",
     "The 404 for an expired document owns the retention policy: sessions live for "
     "an hour, then everything is deleted. That is the design working, not a bug."),
]

DEGRADED_PAGES = [
    ("/", "10-gallery-only-mode",
     "The same landing page with no model key: uploads are honestly paused, the "
     "banner says why, and the six samples still carry the full experience — "
     "designed degradation, not a dead end."),
]


def start_server(with_key: bool) -> subprocess.Popen:
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    if with_key:
        env["ANTHROPIC_API_KEY"] = "sk-ant-demo-placeholder"  # renders live-mode UI only
    proc = subprocess.Popen(
        [str(ROOT / ".venv/bin/uvicorn"), "tallyproof.app.main:app",
         "--app-dir", "src", "--port", str(PORT), "--log-level", "warning"],
        cwd=ROOT, env=env,
    )
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/healthz", timeout=1)
            return proc
        except Exception:
            time.sleep(0.25)
    proc.terminate()
    raise SystemExit("server did not become healthy")


def shoot(pages, page) -> list[tuple[str, str]]:
    captured = []
    for path, name, caption in pages:
        page.goto(f"http://127.0.0.1:{PORT}{path}", wait_until="networkidle")
        page.wait_for_timeout(300)  # let images settle
        target = OUT / f"{name}.png"
        page.screenshot(path=str(target), full_page=True)
        captured.append((name, caption))
        print(f"  {target.relative_to(ROOT)}")
    return captured


def main() -> None:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    captured: list[tuple[str, str]] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900},
                                device_scale_factor=2)
        server = start_server(with_key=True)
        try:
            print("live-mode pages:")
            captured += shoot(PAGES, page)
        finally:
            server.terminate()
            server.wait()
        server = start_server(with_key=False)
        try:
            print("degraded-mode page:")
            captured += shoot(DEGRADED_PAGES, page)
        finally:
            server.terminate()
            server.wait()
        browser.close()

    index = [
        "# Tallyproof — visual walkthrough",
        "",
        "Every page of the running app, captured full-height by",
        "`scripts/make_screenshots.py` against a local instance. The first nine",
        "are the app as deployed with a model key; the last shows the designed",
        "degradation when no key is configured. Nothing here is a mockup.",
        "",
    ]
    for name, caption in captured:
        index += [f"## {name[3:].replace('-', ' ')}", "", caption, "",
                  f"![{name}]({name}.png)", ""]
    (OUT / "README.md").write_text("\n".join(index))
    print(f"wrote {OUT.relative_to(ROOT)}/README.md ({len(captured)} screenshots)")


if __name__ == "__main__":
    main()

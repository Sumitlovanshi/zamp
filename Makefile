# Tallyproof — everything a stranger needs, no key, no Docker, no network.
PY := .venv/bin/python

setup:            ## create venv and install (one command, offline after pip)
	python3 -m venv .venv
	.venv/bin/pip install -q -e ".[dev]"

test:             ## full suite: properties, differential, golden, app. <10s, offline
	$(PY) -m pytest

lint:
	.venv/bin/ruff check src tests eval scripts

eval:             ## regenerate every published number from CORD ground truth
	$(PY) eval/run.py > /dev/null && git diff --stat eval/report.md || true

golden:           ## regenerate the committed per-document verdicts
	$(PY) scripts/make_golden.py

samples:          ## rebuild the precomputed gallery
	$(PY) scripts/make_samples.py

run:              ## local server on :8123 (gallery works without any key)
	.venv/bin/uvicorn tallyproof.app.main:app --app-dir src --port 8123

docker:
	docker build -t tallyproof .

.PHONY: setup test lint eval golden samples run docker

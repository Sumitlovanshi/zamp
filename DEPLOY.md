# Deploying

One Docker container, no database, no volume. The app keeps sessions in
memory, so it wants exactly **one always-on instance** — not serverless.

## Railway (the supported path)

```bash
brew install railway            # or: npm i -g @railway/cli
railway login
railway init                    # from the repo root; creates the project
railway up                      # builds the Dockerfile and deploys
railway domain                  # mints the public URL
```

Live uploads need a vision-model key — set it yourself so it never leaves
your shell/dashboard. Either provider works (auto-detected; Anthropic wins
if both are set, `TALLYPROOF_PROVIDER` overrides):

```bash
railway variables --set ANTHROPIC_API_KEY=sk-ant-...       # paid, strongest
# — or —
railway variables --set GEMINI_API_KEY=...                  # free tier works for a demo
railway variables --set TALLYPROOF_DAILY_BUDGET=200         # stays inside Gemini's ~250 req/day
```

On Render: dashboard → your service → Environment → add `GEMINI_API_KEY`
(and optionally `TALLYPROOF_DAILY_BUDGET=200`), then redeploy.

**Free-Gemini caveats, honestly:** the free tier is rate-limited (~10
requests/minute, ~250/day for `gemini-2.5-flash`) — the app's own per-IP
limit (12/hour) and daily budget keep a public demo inside that. And
Google may use free-tier API data for product improvement; receipts here
are EXIF-stripped and PII-light by design, and the app's privacy footer
already tells uploaders not to submit other people's personal data — but
if that policy bothers you, use a paid key of either provider.

Without the key the app runs in **gallery-only mode** — clearly labelled,
and the six sample receipts carry the full experience (they are
precomputed and never touch a model).

Then put the minted URL into README.md's "Live demo" line.

## Free options, honestly compared

Railway's Hobby plan is ~$5/month (a one-time trial credit covers the first
weeks). If the budget is zero, these work, each with a stated trade-off:

| host | cost | trade-off |
|---|---|---|
| **Render** (free web service, Docker) | free forever | spins down after 15 min idle; ~50 s cold start on the next visit, and in-memory sessions are lost on spin-down. Gallery unaffected. A ready `render.yaml` blueprint is in the repo root: dashboard → New → Blueprint → pick the repo. |
| **Google Cloud Run** (`--min-instances=0`) | free tier covers demo traffic | ~2–5 s cold start after idle; sessions lost when the instance scales to zero (gallery unaffected). Needs a Google account + `gcloud`. |
| **Oracle Cloud Always Free VM** | free forever, always-on | sign-up friction (card verification); you run `docker run` + a reverse proxy yourself. The only free option with no cold start and durable sessions. |
| **Your own machine + Cloudflare Tunnel** | free | up only while the machine is; fine for a live walkthrough, wrong for an unattended demo URL. |

The app degrades by design, so all of these are *safe* — the gallery is baked
into the image and never needs the model, a key, or state. What the free tiers
cost you is the first impression (cold starts) and upload sessions surviving
idle periods. For an evaluated demo URL, one month of an always-on paid
container is the honest recommendation; Render-free is the best zero-cost
compromise.

Cloud Run, concretely:

```bash
gcloud run deploy tallyproof --source . --region asia-south1 \
  --allow-unauthenticated --min-instances=0 --memory=512Mi
gcloud run services update tallyproof --set-env-vars ANTHROPIC_API_KEY=sk-ant-...
```

## Anywhere else

Any host that runs a Docker image with one persistent instance works the
same way (Fly.io, Render starter, Cloud Run with `--min-instances=1`, a VPS):

```bash
docker build -t tallyproof .
docker run -p 8080:8080 -e ANTHROPIC_API_KEY=sk-ant-... tallyproof
```

Avoid free tiers that sleep on idle (the evaluated URL would open dead)
and serverless platforms (per-invocation processes lose the in-memory
sessions by design — see decisions.md #10).

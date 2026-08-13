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

Live uploads need a model key — set it yourself so it never leaves your shell:

```bash
railway variables --set ANTHROPIC_API_KEY=sk-ant-...
railway variables --set TALLYPROOF_DAILY_BUDGET=300   # optional, default 300 calls/day
```

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

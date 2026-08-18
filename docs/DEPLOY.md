# Deployment options

The constraint that decides everything: this app needs **two long-lived processes and
~440 MB of RAM**. Not a build step and a bundle — a persistent server holding in-memory
indexes, plus a WebSocket-based UI.

That single fact rules some platforms in and one platform out.

---

## Netlify — no, and not for a fixable reason

Netlify hosts static assets plus short-lived serverless functions. Three independent
blockers:

1. **Streamlit is not static.** It is a server that holds an open WebSocket per viewer and
   re-runs a Python script on every interaction. There is nothing to put in a CDN.
2. **Function timeout.** Netlify Functions cap at 10 s by default (26 s max). Ingesting the
   demo corpus takes longer than that, and any cold start pays model load on top.
3. **No persistent memory.** The BM25 index, the embedding matrix, and the graph live in
   process memory. Serverless functions are torn down between invocations, so every request
   would rebuild the entire index from scratch.

Also, the deployment bundle limit (250 MB unzipped) is smaller than onnxruntime plus the
embedding model.

You could rewrite the backend as stateless functions backed by hosted Neo4j + a hosted
vector DB, and put a React frontend on Netlify. That is a different application, not a
deployment target change. Not worth it for a portfolio piece.

---

## Fly.io — yes, best fit

Already configured. `fly.toml` runs both processes in one machine, Streamlit public on
8501, API on loopback 8000.

```bash
fly launch --no-deploy     # first time; it will read fly.toml
fly secrets set GROQ_API_KEY=gsk_... API_KEYS="demo:$(openssl rand -hex 16)"
fly deploy
```

**Why it fits best:**

- `auto_stop_machines = "suspend"` with `min_machines_running = 0` scales to zero, and
  *suspend* resumes in about a second rather than cold-booting in eight.
- Memory is a dial, not a tier. 512 MB is set in `fly.toml` because that is what the app
  measured at; you are not fighting a fixed free-tier ceiling.
- Two processes in one machine is normal, not a workaround.

**Cost reality:** Fly retired the old always-free allowance. A `shared-cpu-1x` 512 MB
machine is a few dollars a month at full uptime, and scale-to-zero means a portfolio link
that gets occasional traffic costs very little — you are billed for running time plus a
small rootfs charge. Verify current pricing before you rely on a number.

**256 MB variant:** `deploy/fly.api.toml` + `deploy/fly.ui.toml` split the app across two
machines. The API fits 256 MB **only** with `ALLOW_EMBED_DOWNLOAD=0` (TF-IDF path, 93 MB).
That measurably weakens the vector lane at paraphrase matching, which is the exact case
the vector lane exists to win. State the tradeoff if you ship it.

---

## Render — yes, works, with caveats

`render.yaml` is a single web service: Streamlit binds `$PORT` (Render's injected port and
its only public one), uvicorn stays on loopback. `start.sh` already reads `$PORT`, so
nothing needed changing.

```bash
# Push render.yaml, then in the dashboard: New > Blueprint > pick the repo.
# Set GROQ_API_KEY and API_KEYS as secrets there (sync: false in the blueprint).
```

**Caveats, in order of how much they will annoy you:**

1. **Free instances spin down after ~15 minutes idle**, and cold start is roughly 50 s.
   For a portfolio link someone clicks once from your CV, they see a blank loading screen
   for the better part of a minute. This is the real problem with Render free — not memory.
2. **512 MB free instance vs ~440 MB measured peak.** It fits with about 70 MB of headroom,
   which a few concurrent viewers can erase. Set `ALLOW_EMBED_DOWNLOAD=0` for safety, or
   move to the 2 GB Starter plan.
3. **One port per service.** Fine here, since the API is deliberately internal. If you want
   the API publicly reachable you need a second service — and then the API is on the open
   internet, so `API_KEYS` stops being optional.

---

## Hugging Face Spaces — worth considering, and probably the best free option

Not on your list, but for this specific project it is the strongest free choice:

- Free CPU Spaces get **16 GB RAM**, so every memory constraint above disappears.
- Native Streamlit and Docker SDK support; Streamlit is a first-class citizen.
- No spin-down penalty comparable to Render free.
- The audience is other ML engineers, which is who you want finding a RAG project.

Tradeoffs: it reads as a demo rather than a product, the URL is `hf.space` not your own
domain, and Spaces are public by default (private needs a paid plan). If the goal is "a
recruiter clicks the link and it works instantly", this wins. If the goal is "I deployed
production infrastructure", Fly is the better story.

---

## Recommendation

| Goal | Choose |
| --- | --- |
| Link in a CV that must load instantly, zero cost | **Hugging Face Spaces** |
| Demonstrating production deployment skill | **Fly.io**, 512 MB, `fly.toml` as committed |
| Free and you accept a 50 s cold start | **Render** free + `ALLOW_EMBED_DOWNLOAD=0` |
| Anything | **Not Netlify** |

Doing both is reasonable and cheap: Fly as the real deployment you talk about in
interviews, Spaces as the always-warm link you actually put on the CV.

---

## Before you deploy anywhere

1. **Set `API_KEYS`.** Auth is opt-in, so an unset value means the API is open. On Fly the
   API is loopback-only and lower risk; on Render with a second service it is public.
   ```bash
   fly secrets set API_KEYS="demo:$(openssl rand -hex 16)"
   ```
2. **Set `GROQ_API_KEY`**, or every answer is the extractive fallback and reads poorly.
3. **Do not put real corporate documents in a public deployment.** There is no
   authentication on the UI, only on the API.
4. **Check `/health` after deploy.** `status: degraded` with
   `embedder_mode: tfidf-fallback` means the model prefetch failed and the vector lane is
   running on the weaker path.

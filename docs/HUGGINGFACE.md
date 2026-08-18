# Deploying to Hugging Face Spaces

The best free option for this project: free CPU Spaces get **16 GB RAM**, so every memory
constraint discussed in `docs/DEPLOY.md` disappears, and there is no Render-style 50-second
cold start.

## One-time setup

1. Create a Space at https://huggingface.co/new-space
   - **SDK:** Docker (blank template, not Streamlit - we need both processes)
   - **Hardware:** CPU basic (free)
   - **Visibility:** Public (private Spaces need a paid plan)

2. Clone it and copy this project in:

   ```bash
   git clone https://huggingface.co/spaces/<your-username>/rag-arena hf-space
   cd hf-space

   # copy everything except the git metadata and local artefacts
   rsync -a --exclude '.git' --exclude '.venv' --exclude 'data/chroma' \
            --exclude 'data/admin_credentials.json' \
            ../rag-arena/ .

   # the Space README must carry HF frontmatter - ours lives in deploy/huggingface/
   cp deploy/huggingface/README.md README.md
   ```

   The frontmatter matters: `sdk: docker` and `app_port: 8501` tell HF to build the
   Dockerfile and route traffic to Streamlit. Without `app_port` HF expects port 7860 and
   you get a blank page.

3. Set secrets in **Settings > Variables and secrets**:

   | Name | Type | Value |
   | --- | --- | --- |
   | `GROQ_API_KEY` | Secret | your Groq key |
   | `ADMIN_EMAIL` | Secret | your owner email |
   | `ADMIN_SLUG` | Secret | something other than `ashish` if you want it less guessable |
   | `API_KEYS` | Secret | `demo:<random hex>` - only needed if you expose the API |

4. Push:

   ```bash
   git add -A && git commit -m "Deploy RAG Arena" && git push
   ```

   First build takes 5-10 minutes, mostly the embedding-model prefetch.

## Register the admin account immediately

The first registration claims the panel. Until you register, the form is live on a public
URL - and although it only accepts `ADMIN_EMAIL`, there is no reason to leave it open.

Go to `https://<your-space>.hf.space/?admin=<ADMIN_SLUG>` and register as soon as the
build finishes.

## The persistence problem, and what to do about it

Space filesystems are **ephemeral**. Anything written at runtime - `data/portfolio.json`,
`data/admin_credentials.json`, uploaded resumes, ingested documents - is lost when the
Space restarts, which happens on every push and after long idle periods.

Consequences:

- **You must re-register the admin account after every restart.** Slightly annoying, but it
  also means a stale password can never linger.
- **Portfolio edits vanish** unless you export them.

The workflow that makes content durable:

1. Edit in the admin panel.
2. Open the **Export** tab, download `portfolio.json`.
3. Commit it to the repo at `data/portfolio.json` and push.

Now the content is baked into the image and survives every restart. The admin panel becomes
an editor that produces a committed artefact, rather than a live CMS - which for a personal
site that changes a few times a year is the right trade.

If you want genuine persistence, back the content with a HF Dataset repo and read/write it
through `huggingface_hub`. That is a real change to `app/adminstore.py`, not a config
toggle, and it is not implemented.

## Notes

- **User id.** The Dockerfile creates `appuser` with uid 10001 and chowns `/app`. HF Docker
  Spaces conventionally use uid 1000. Ours works because everything the app writes is under
  `/app`, which it owns. If you hit permission errors, rebuild with
  `--build-arg APP_UID=1000`.
- **Model prefetch.** `PREFETCH_MODEL=1` bakes `bge-small-en-v1.5` into the image. Keep it -
  without it the first query after every restart pays a ~130 MB download.
- **Do not ingest real corporate documents.** The Space is public and the UI has no
  authentication. Only the admin panel is protected.
- **Memory.** With 16 GB available you can drop the memory guards if you want throughput:
  set `EMBED_THREADS=4` and `EMBED_BATCH_SIZE=32` as Space variables.

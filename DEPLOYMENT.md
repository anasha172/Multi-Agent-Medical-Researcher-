# Deployment (Phase 24)

## Deployment checklist

- [x] `requirements.txt` — pinned to the exact versions this project was built and tested against
- [x] `.env` — never committed (`.gitignore`); every required key is documented in `.env.example`
- [x] LanceDB path — configurable via `LANCEDB_PATH`, defaults to `data/lancedb/` (see persistence note below)
- [x] API keys — `OPENROUTER_API_KEY`, `TAVILY_API_KEY`, `NCBI_EMAIL`, `NCBI_API_KEY` (all read from environment, never hardcoded)
- [x] NCBI configuration — `NCBI_EMAIL` required by Entrez's usage policy; `NCBI_API_KEY` optional (raises the rate limit)
- [x] Tavily configuration — `TAVILY_API_KEY`, domain restriction is enforced in code (`tools/tavily_search.py`), not configurable via env
- [x] Streamlit app — `app.py` is a complete, self-contained entrypoint
- [x] No local-only paths — every file path in the codebase is relative (`Path(__file__).resolve().parent...`) or environment-configurable; verified with a repo-wide grep for hardcoded absolute paths
- [x] No secrets in Git — `.env` is gitignored; `.env.example` holds only empty placeholders

## Important: LanceDB persistence

LanceDB is a **per-run evidence cache**, not a database the app depends on being pre-populated. Every research run retrieves fresh evidence from PubMed/Tavily and re-indexes it into LanceDB before analysis. If the deployment platform's filesystem is ephemeral (most container platforms, including Streamlit Community Cloud), the LanceDB directory resets on every restart/redeploy — **this is expected and fine**. Nothing in the app assumes the store survives beyond a session; a fresh research question repopulates it. Persistent storage would only be a nice-to-have (faster repeat lookups across restarts), never a requirement.

## Option A — Streamlit Community Cloud (simplest)

1. Push this repository to GitHub (`.env` stays untracked).
2. On [share.streamlit.io](https://share.streamlit.io), create a new app pointing at this repo, branch, and `app.py`.
3. In the app's **Secrets** panel, paste the contents of your local `.env` (Streamlit Cloud injects these as environment variables — no code changes needed).
4. Deploy.

**Note:** `runtime.txt` requests Python 3.12, the exact version every pinned dependency in `requirements.txt` was installed and tested against. If Streamlit Community Cloud's supported versions differ when you deploy, adjust `runtime.txt` accordingly and re-verify `pip install -r requirements.txt` succeeds there first.

## Option B — Docker (most portable, recommended if Option A's Python version isn't available)

Builds and runs identically to local development, since the image pins the exact same Python version:

```bash
docker build -t medresearch-ai .
docker run -p 8501:8501 --env-file .env medresearch-ai
```

Then open `http://localhost:8501`. This works on any container host (Render, Railway, Fly.io, a VM, etc.) — push the image to a registry and point the platform at it, supplying the same environment variables from `.env` through that platform's secrets/environment configuration UI.

## Verifying a deployment

Once live, run through the Phase 23 test scenarios manually (see `tests/test_scenarios.py` for the exact questions) and confirm:
- A simple question ("What is hypertension?") returns a report with real citations.
- The GLP-1 demo question produces the full pipeline: plan → evidence → analysis → contradictions → insights → report → validation.
- The research-use-only disclaimer is visible on every screen.

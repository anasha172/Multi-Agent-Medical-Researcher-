# MedResearch AI — Multi-Agent Healthcare Evidence Intelligence

> Ask a complex healthcare research question. Our AI research team searches trusted
> medical sources, analyzes evidence, detects contradictions, identifies evidence
> gaps, and produces a citation-backed research report.

**Research Use Only:** This system synthesizes publicly available medical literature
and regulatory information. It is not a medical diagnostic tool and should not
replace professional medical advice.

## Status

✅ All 30 phases of `PHASES.md` implemented: Query Planner → PubMed + Tavily
retrieval → LanceDB hybrid search → Critical Analysis → Contradiction Detection
→ Insight Generation → Report Builder → Evidence Validator, orchestrated by
LangGraph and served through a Streamlit UI with a live agent-execution view,
an evidence graph, and citation drill-down.

## Stack

Python · LangGraph · LanceDB · OpenRouter · Sentence Transformers ·
Biopython/NCBI Entrez · Tavily · Streamlit · Plotly · Pydantic v2

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
copy .env.example .env      # then fill in your API keys
streamlit run app.py
```

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for Streamlit Community Cloud and Docker
instructions, plus a checklist and the LanceDB persistence caveat.

## Testing

```bash
.venv\Scripts\python.exe -m pytest tests/ -v
```

Most tests are unit-level (mocked, no network). Tests that require live API
keys (OpenRouter/NCBI/Tavily) are skipped automatically if those aren't set
in `.env`, and are named accordingly (e.g. `test_..._live_...`).
`tests/test_scenarios.py` runs the five end-to-end scenarios from Phase 23
against the real, full pipeline.

## Positioning & Safety (Phase 29)

MedResearch AI is positioned as a **research evidence synthesis tool**,
never as a diagnostic, treatment, or advice system. This is enforced in
code, not just stated in a footer:

| Never claimed | Instead, always | Enforced in |
|---|---|---|
| "100% accurate" / fully conclusive | Evidence-backed synthesis with stated limitations/gaps | `agents/analyzer.py`, `agents/report.py` prompts |
| Doctor replacement / diagnosis | Describes what the evidence shows, not what to do | `prompts/report.txt`, `prompts/validator.txt` (safety check), `app.py` disclaimer on every screen |
| Treatment recommendation | No directive language ("you should take X") | Validator's deterministic phrase check + LLM safety review (`agents/validator.py`) |
| "Clinically validated confidence score" | "Research Evidence Confidence" — a stated prototype heuristic | `utils/scoring.py`, `models/schemas.py::ConfidenceScore` docstring |
| Hypotheses as established fact | Explicitly labelled, schema-enforced | `Insight.is_hypothesis` validator (`models/schemas.py`) |
| Fabricated citations | Every claim traces to a real, retrieved source or is dropped | Citation-marker validation across `AnalysisResult`, `ReportNarrative`, and `agents/report.py`'s resolve/verify step |

See `ARCHITECTURE.md` for the full system diagram and agent responsibilities.

## Project Structure

```text
healthcare-researcher/
├── app.py                # Streamlit UI (Phases 18-21)
├── agents/                # planner, analyzer, contradiction, insights, report, validator
├── graph/                 # LangGraph state + workflow (Phases 16-17)
├── tools/                 # pubmed, tavily, lancedb, retriever
├── models/                # Pydantic v2 schemas (agent data contracts)
├── prompts/                # per-agent prompt templates
├── utils/                 # llm client, embeddings, scoring, text helpers
├── data/lancedb/          # local hybrid vector store (ephemeral-safe, see DEPLOYMENT.md)
├── tests/                 # pytest suite, one file per phase's deliverable
├── Dockerfile / .dockerignore
├── DEPLOYMENT.md
└── PHASES.md               # the build specification this project follows
```

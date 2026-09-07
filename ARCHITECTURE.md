# Architecture (Phases 27–28)

## System diagram

```text
                     USER
                      │
                      ▼
               QUERY PLANNER               (agents/planner.py — LLM, structured output)
                      │
                      ▼
          CONTEXTUAL RETRIEVER            (tools/retriever.py — no LLM, tool orchestration)
             ┌────────┴────────┐
             ▼                 ▼
         PUBMED             TAVILY          (parallel via ThreadPoolExecutor,
      (Biopython/Entrez)  (FDA/WHO/NCBI-      not separate graph nodes)
                            restricted)
             └────────┬────────┘
                      ▼
                 LANCEDB RAG                (hybrid vector + BM25, dedup by PMID>URL>title)
                      │
                      ▼
              CRITICAL ANALYSIS             (agents/analyzer.py — LLM)
                      │
                      ▼
            CONTRADICTION DETECTOR          (agents/contradiction.py — LLM)
                      │
                      ▼
               INSIGHT GENERATOR            (agents/insights.py — LLM)
                      │
                      ▼
               REPORT BUILDER  ◄──────┐     (agents/report.py — LLM for prose only;
                      │               │      findings/contradictions/insights are
                      ▼               │      deterministic pass-through)
             EVIDENCE VALIDATOR       │     (agents/validator.py — deterministic
                      │               │      checks + LLM semantic review)
                 PASS? / retry ───────┘       (capped at MAX_REVISIONS=1)
                      │
                      ▼
              STREAMLIT REPORT              (app.py — live status, dashboard,
                                              evidence graph, citation drill-down)
```

Technology labels: **LangGraph** (orchestration + conditional routing) ·
**OpenRouter** (LLM gateway, per-role model config) · **LanceDB** (hybrid
vector+BM25 store) · **Sentence Transformers** (local embeddings) ·
**Biopython** (PubMed/Entrez) · **Tavily** (domain-restricted web search) ·
**Pydantic v2** (every inter-agent payload) · **Streamlit** + **Plotly**
(UI + visualization).

## Why this is a real multi-agent system

Judges may ask: *"Why do you need multiple agents instead of one prompt?"*

| Agent | Responsibility |
|---|---|
| **Planner** | Understands the question; decomposes it into sub-questions and source-specific search queries. Never draws a conclusion itself. |
| **Retriever** *(tool, not an LLM agent)* | Finds evidence from PubMed + restricted web sources, deduplicates, ranks. |
| **Analyzer** | Evaluates evidence quality — study design, sample size, limitations — and extracts citable claims. |
| **Contradiction Detector** | Checks whether credible sources disagree, and why. |
| **Insight Generator** | Identifies trends, evidence gaps, and clearly-labelled hypotheses — never presented as fact. |
| **Report Builder** | Turns everything upstream into a structured, citation-backed report. |
| **Validator** | A final QA pass: citation completeness, hallucination detection, safety language — routes back to the Report Builder once if it fails. |

Each agent has a **distinct responsibility and a strict Pydantic v2 output
schema** (`models/schemas.py`) — they don't chat with each other in free
text. LangGraph (`graph/workflow.py`) owns the shared state
(`graph/state.py`) and the control flow, including the one bounded retry
loop between the Report Builder and Validator. This is what separates the
system from a single-prompt RAG chatbot: specialization, structured
handoffs, and a workflow that can retry and self-correct.

The strongest demo moment (see `DEMO_SCRIPT.md`):

> "These two credible studies disagree. Here is exactly what they disagree
> about, what the evidence says on both sides, and why the difference may
> exist."

## What this system never claims

See the **Positioning & Safety** section in `README.md` for the exact list
of claims this system avoids (no diagnosis, no treatment recommendation, no
"clinically validated" confidence score) and where each is enforced in
code — the disclaimer, the report/validator prompts, and the naming
discipline around "Research Evidence Confidence."

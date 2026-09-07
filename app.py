"""
MedResearch AI — Streamlit frontend (Phase 18 base UI + Phase 19 evidence
visualization + Phase 20 citation traceability + Phase 21 error surfacing),
restyled as a premium, non-technical healthcare research product per the
"Premium Simplified UI" spec: a dark navy sidebar showing only agent names
(no descriptive paragraphs), a calm light main workspace, a large research
composer, plain-language progress, and card-based results. Every advanced/
technical detail (per-node timings, raw error text) stays available but
tucked behind an optional "View research activity" expander rather than
shown by default.

As much logic as possible lives in plain functions that don't need an
active Streamlit script-run context (grouping execution logs, building the
Plotly gauge figure) so it's unit-testable without a live pipeline run; see
tests/test_app.py. The interactive click-through itself (asking a real
question and watching it run) is verified manually — it drives the full
multi-agent pipeline against live APIs, which isn't something to exercise
on every automated test run.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, Optional, Tuple

import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from graph.state import ResearchState, create_initial_state
from models.schemas import Evidence, EvidenceType, ExecutionLogEntry, RetrievedDocument

# build_workflow (graph.workflow) is deliberately NOT imported at module
# level: its transitive imports include sentence-transformers/torch,
# langgraph, and lancedb, which take ~30s to import on a cold process.
# Importing it eagerly here would block Streamlit from rendering *anything*
# -- including the initial title/input screen -- for that whole 30s with no
# visible progress indicator, which looks exactly like a hung app. Deferring
# the import into the "Start Research" click handler below means the
# initial screen renders immediately, and the one-time cold-start cost is
# paid inside a spinner that's already shown for exactly this reason.

load_dotenv()

DISCLAIMER = (
    "Research use only. MedResearch AI summarizes publicly available "
    "medical evidence and does not provide medical diagnosis or treatment "
    "advice."
)

# Node execution order + display name for every surface (sidebar, progress
# checklist, technical detail view). "increment_revision" is an internal
# bookkeeping node (Phase 17) and deliberately not shown as its own row.
NODE_LABELS: Dict[str, str] = {
    "planner": "Query Planner",
    "retriever": "Evidence Retriever",
    "analyzer": "Critical Analysis",
    "contradiction_detector": "Contradiction Detector",
    "insight_generator": "Insight Generator",
    "report_builder": "Report Builder",
    "validator": "Evidence Validator",
}

_STATUS_BADGE: Dict[Optional[str], Tuple[str, str]] = {
    None: ("Pending", "gray"),
    "running": ("Running", "blue"),
    "completed": ("Completed", "green"),
    "failed": ("Failed", "red"),
}

# Plain-language phase description shown in the non-technical progress
# checklist -- deliberately avoids any AI/ML/pipeline vocabulary (spec: no
# "agent", "LLM", "retrieval", "orchestration" in user-facing copy).
AGENT_PROGRESS_PHRASE: Dict[str, str] = {
    "planner": "Planning your research",
    "retriever": "Finding trusted evidence",
    "analyzer": "Analyzing the evidence",
    "contradiction_detector": "Checking for contradictions",
    "insight_generator": "Generating insights",
    "report_builder": "Building your report",
    "validator": "Validating the evidence",
}

# Icon key per agent, used only in the sidebar (see _ICON_PATHS below).
AGENT_ICON_KEY: Dict[str, str] = {
    "planner": "list_tree",
    "retriever": "search",
    "analyzer": "microscope",
    "contradiction_detector": "git_compare",
    "insight_generator": "lightbulb",
    "report_builder": "file_text",
    "validator": "shield_check",
}

# (short card label, full question sent to the pipeline).
EXAMPLE_QUESTIONS: List[Tuple[str, str]] = [
    ("Causes of hypertension", "What are the main causes of hypertension?"),
    ("GLP-1 evidence", "What does current evidence say about GLP-1 treatments?"),
    ("Diabetes treatments", "What are the latest treatment options for type 2 diabetes?"),
]


# ---------------------------------------------------------------------------
# Pure helpers (no Streamlit context required -- unit-testable directly)
# ---------------------------------------------------------------------------


def latest_log_by_node(execution_logs: List[ExecutionLogEntry]) -> Dict[str, ExecutionLogEntry]:
    """The most recent log entry per node (a retried node has more than one)."""
    latest: Dict[str, ExecutionLogEntry] = {}
    for entry in execution_logs:
        latest[entry.agent_name] = entry
    return latest


def attempt_counts(execution_logs: List[ExecutionLogEntry]) -> Dict[str, int]:
    """How many times each node has run (>1 means a validator-triggered retry)."""
    counts: Dict[str, int] = {}
    for entry in execution_logs:
        counts[entry.agent_name] = counts.get(entry.agent_name, 0) + 1
    return counts


def status_badge_for(entry: Optional[ExecutionLogEntry]) -> Tuple[str, str]:
    """(badge_text, badge_color) for one node's latest log entry, or the pending state."""
    status_key = entry.status.value if entry else None
    return _STATUS_BADGE[status_key]


def source_counts_by_provider(documents) -> Counter:
    return Counter(doc.source.value for doc in documents)


def evidence_counts_by_strength(evidence_items) -> Counter:
    return Counter(item.strength.value for item in evidence_items)


def agent_progress_states(
    execution_logs: Optional[List[ExecutionLogEntry]], in_progress: bool
) -> Dict[str, str]:
    """
    One of "idle" / "queued" / "active" / "completed" / "failed" per agent
    (in NODE_LABELS order), used by both the sidebar and the main-page
    progress checklist so the two stay in sync.

    Every node always logs a finished entry by the time a run ends (each
    workflow node catches its own exceptions and always appends a
    completed/failed entry -- see graph/workflow.py), so "active"/"queued"
    only ever apply while a run is still streaming (in_progress=True); once
    it finishes, every agent already has a real entry.
    """
    if not execution_logs:
        return {name: "idle" for name in NODE_LABELS}

    latest = latest_log_by_node(execution_logs)
    states: Dict[str, str] = {}
    active_assigned = False
    for name in NODE_LABELS:
        entry = latest.get(name)
        if entry is None:
            if in_progress and not active_assigned:
                states[name] = "active"
                active_assigned = True
            else:
                states[name] = "queued"
        elif entry.status.value == "failed":
            states[name] = "failed"
        else:
            states[name] = "completed"
    return states


_FRIENDLY_ERROR_RULES: List[Tuple[str, str]] = [
    ("planning", "There was a brief issue planning the research steps, but the research continued."),
    ("retrieval", "One research source could not be reached. Your research continued using the remaining trusted sources."),
    ("analysis", "One part of the evidence analysis had an issue, but the research continued."),
    ("contradiction", "Checking for contradictions had a brief issue; the rest of the report is unaffected."),
    ("insight", "Generating insights had a brief issue; the rest of the report is unaffected."),
    ("report building", "There was a brief issue while building part of the report."),
    ("validation", "The final quality check had a brief issue -- please review the report's citations carefully."),
]


def friendly_error(message: str) -> str:
    """Map a raw backend error string to plain, reassuring, non-technical language."""
    lowered = message.lower()
    for keyword, friendly in _FRIENDLY_ERROR_RULES:
        if keyword in lowered:
            return friendly
    return "One step of the research process had a brief issue, but the research continued."


_EVIDENCE_STRENGTH_LABEL: Dict[str, str] = {"strong": "High", "moderate": "Moderate", "limited": "Low"}
_EVIDENCE_STRENGTH_BADGE_COLOR: Dict[str, str] = {"strong": "green", "moderate": "orange", "limited": "gray"}
_CONTRADICTION_SEVERITY_BADGE_COLOR: Dict[str, str] = {"low": "gray", "moderate": "orange", "high": "red"}


def confidence_bucket_label(confidence: float) -> str:
    """0.0-1.0 insight confidence -> a plain High/Moderate/Low bucket for badges."""
    if confidence >= 0.7:
        return "High"
    if confidence >= 0.4:
        return "Moderate"
    return "Low"


# ---------------------------------------------------------------------------
# Citation traceability (Phase 20): claim -> evidence -> source
# ---------------------------------------------------------------------------

# The bracket may be followed by a single sentence-ending punctuation mark
# (build_report()'s LLM-written sentences naturally end "...[citation]." with
# the period from the original sentence still attached after the marker is
# resolved) -- mirrors models/schemas.py's own _EVIDENCE_CITATION_PATTERN,
# which allows the same trailing [.!?]?. Without it, any finding whose
# citation bracket is followed by punctuation would silently fail to match.
_TRAILING_CITATION_PATTERN = re.compile(r"\s*\[([^\]]+)\](\s*[.!?]?)\s*$")


def extract_citations_from_text(text: str) -> List[str]:
    """
    Recover the individual citation strings from a report statement already
    resolved by build_report() (Phase 14), e.g.
    "...reduced symptoms. [PMID: 111; PMID: 222]" -> ["PMID: 111", "PMID: 222"].
    Returns [] if the text carries no trailing bracketed citation.
    """
    match = _TRAILING_CITATION_PATTERN.search(text.strip())
    if not match:
        return []
    return [part.strip() for part in match.group(1).split(";") if part.strip()]


def strip_trailing_citation(text: str) -> str:
    """The claim text alone, with its trailing [citation] marker removed
    (any sentence-ending punctuation right after the marker is kept)."""
    return _TRAILING_CITATION_PATTERN.sub(lambda m: m.group(2).strip(), text.strip()).strip()


def build_citation_lookup(evidence_items: List[Evidence]) -> Dict[str, Evidence]:
    """citation string -> the Evidence item it was resolved from."""
    return {item.citation: item for item in evidence_items}


def build_document_lookup(documents: List[RetrievedDocument]) -> Dict[str, RetrievedDocument]:
    """document_id -> RetrievedDocument, for resolving an Evidence item's original source."""
    return {doc.document_id: doc for doc in documents}


def render_claim_trace(
    statement: str,
    citation_lookup: Dict[str, Evidence],
    document_lookup: Dict[str, RetrievedDocument],
) -> None:
    """Render "Why this claim?" -> supporting evidence -> original source for one statement."""
    citations = extract_citations_from_text(statement)
    if not citations:
        st.caption("No structured citation found for this statement.")
        return

    for citation in citations:
        evidence_item = citation_lookup.get(citation)
        if evidence_item is None:
            st.caption(f"Citation: {citation} (evidence detail unavailable)")
            continue

        st.markdown("**Why this claim?**")
        st.write(evidence_item.supporting_text)
        st.caption(
            f"Study type: {evidence_item.study_type.value} | "
            f"Strength: {evidence_item.strength.value} | "
            f"Evidence type: {evidence_item.evidence_type.value}"
        )

        st.markdown("**Original source**")
        doc = document_lookup.get(evidence_item.document_id)
        if doc is not None:
            year = f" ({doc.publication_date})" if doc.publication_date else ""
            st.write(f"{doc.title}{year}")
            journal = (doc.metadata or {}).get("journal")
            if journal:
                st.caption(f"Journal: {journal}")
            if doc.url:
                st.caption(doc.url)
        else:
            st.caption(citation)


def confidence_gauge_figure(overall: float, label: str) -> go.Figure:
    """Build the Research Evidence Confidence gauge (Screen 3)."""
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=overall,
            number={"suffix": "%"},
            title={"text": f"Research Evidence Confidence — {label}"},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": "#2563eb"},
                "steps": [
                    {"range": [0, 30], "color": "#fecaca"},
                    {"range": [30, 50], "color": "#fed7aa"},
                    {"range": [50, 70], "color": "#fef08a"},
                    {"range": [70, 85], "color": "#bbf7d0"},
                    {"range": [85, 100], "color": "#86efac"},
                ],
            },
        )
    )
    fig.update_layout(height=280, margin=dict(l=20, r=20, t=60, b=20))
    return fig


# A distinct, colorful qualitative palette (cycled if there are more slices
# than colors) so every donut slice reads as visually different at a glance.
_DONUT_PALETTE: List[str] = [
    "#4F6BED", "#36C5D0", "#7467F0", "#22A06B",
    "#D99022", "#D94F5C", "#0891B2", "#B45309",
]


def donut_chart_figure(counts: Counter, title: str) -> go.Figure:
    """A colorful donut chart for one categorical breakdown (e.g. sources by
    provider, evidence strength) -- replaces a plain bar chart with a more
    visually differentiated view of the same proportions."""
    labels = list(counts.keys())
    values = list(counts.values())
    colors = [_DONUT_PALETTE[i % len(_DONUT_PALETTE)] for i in range(len(labels))]

    fig = go.Figure(
        data=[
            go.Pie(
                labels=labels,
                values=values,
                hole=0.55,
                marker=dict(colors=colors, line=dict(color="#ffffff", width=2)),
                textinfo="label+percent",
            )
        ]
    )
    fig.update_layout(
        title=title,
        height=320,
        margin=dict(l=10, r=10, t=50, b=10),
        showlegend=True,
    )
    return fig


def _truncate(text: str, length: int = 40) -> str:
    text = " ".join(text.split())  # collapse whitespace/newlines for a clean single-line label
    return text if len(text) <= length else text[: length - 1].rstrip() + "…"


def build_evidence_graph_figure(
    question: str,
    sources: List[RetrievedDocument],
    evidence_items: List[Evidence],
    executive_summary: str,
    conclusion: str,
) -> go.Figure:
    """
    The Phase 19 "evidence graph" (the recommended wow feature): a Plotly
    node/edge diagram showing

        Question -> Sources -> Evidence -> Support/Contradict -> Synthesis
        -> Final Finding

    Pure function (no Streamlit context) so it's directly unit-testable;
    see tests/test_app.py.
    """
    node_x: List[float] = []
    node_y: List[float] = []
    node_labels: List[str] = []
    node_colors: List[str] = []
    node_hover: List[str] = []
    index_of: Dict[str, int] = {}
    edges: List[Tuple[str, str]] = []

    def add_node(node_id: str, x: float, y: float, label: str, color: str, hover: str) -> None:
        index_of[node_id] = len(node_x)
        node_x.append(x)
        node_y.append(y)
        node_labels.append(label)
        node_colors.append(color)
        node_hover.append(hover)

    def centered_y(i: int, n: int) -> float:
        return i - (n - 1) / 2 if n > 1 else 0.0

    # Tier 0: the research question
    add_node("question", 0, 0, _truncate(question, 50), "#1d4ed8", question)

    # Tier 1: cited sources
    for i, doc in enumerate(sources):
        node_id = f"source:{doc.document_id}"
        add_node(node_id, 1, centered_y(i, len(sources)), _truncate(doc.title, 35), "#0891b2", doc.title)
        edges.append(("question", node_id))

    # Tier 2: evidence, colored by whether it supports/contradicts/neither
    _EVIDENCE_COLOR = {
        EvidenceType.SUPPORTING: "#16a34a",
        EvidenceType.CONTRADICTING: "#dc2626",
        EvidenceType.NEUTRAL: "#6b7280",
    }
    for i, item in enumerate(evidence_items):
        node_id = f"evidence:{item.evidence_id}"
        add_node(
            node_id,
            2,
            centered_y(i, len(evidence_items)),
            _truncate(item.claim, 35),
            _EVIDENCE_COLOR.get(item.evidence_type, "#6b7280"),
            f"{item.claim} ({item.citation})",
        )
        source_node_id = f"source:{item.document_id}"
        if source_node_id in index_of:
            edges.append((source_node_id, node_id))

    # Tier 3: aggregate Support / Contradict nodes
    has_support = any(e.evidence_type == EvidenceType.SUPPORTING for e in evidence_items)
    has_contradict = any(e.evidence_type == EvidenceType.CONTRADICTING for e in evidence_items)
    if has_support:
        add_node("support", 3, 0.6, "Support", "#16a34a", "Aggregated supporting evidence")
    if has_contradict:
        add_node("contradict", 3, -0.6, "Contradict", "#dc2626", "Aggregated contradicting evidence")

    # Tier 4: synthesis (evidence with no clear support/contradict routes straight here)
    add_node("synthesis", 4, 0, "Synthesis", "#7c3aed", _truncate(executive_summary, 200))

    for item in evidence_items:
        node_id = f"evidence:{item.evidence_id}"
        if item.evidence_type == EvidenceType.SUPPORTING and has_support:
            edges.append((node_id, "support"))
        elif item.evidence_type == EvidenceType.CONTRADICTING and has_contradict:
            edges.append((node_id, "contradict"))
        else:
            edges.append((node_id, "synthesis"))

    if has_support:
        edges.append(("support", "synthesis"))
    if has_contradict:
        edges.append(("contradict", "synthesis"))

    # Tier 5: final finding
    add_node("final_finding", 5, 0, "Final Finding", "#b45309", _truncate(conclusion, 200))
    edges.append(("synthesis", "final_finding"))

    edge_x: List[Optional[float]] = []
    edge_y: List[Optional[float]] = []
    for a, b in edges:
        if a not in index_of or b not in index_of:
            continue
        ia, ib = index_of[a], index_of[b]
        edge_x += [node_x[ia], node_x[ib], None]
        edge_y += [node_y[ia], node_y[ib], None]

    edge_trace = go.Scatter(
        x=edge_x,
        y=edge_y,
        mode="lines",
        line=dict(width=1, color="#94a3b8"),
        hoverinfo="none",
        showlegend=False,
    )
    node_trace = go.Scatter(
        x=node_x,
        y=node_y,
        mode="markers+text",
        marker=dict(size=22, color=node_colors, line=dict(width=1, color="#1e293b")),
        text=node_labels,
        textposition="top center",
        hovertext=node_hover,
        hoverinfo="text",
        showlegend=False,
    )

    fig = go.Figure(data=[edge_trace, node_trace])
    fig.update_layout(
        showlegend=False,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        height=520,
        margin=dict(l=20, r=20, t=30, b=20),
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


# ---------------------------------------------------------------------------
# Icons -- professional line icons (Lucide-style), no emoji anywhere in the UI
# ---------------------------------------------------------------------------

_ICON_PATHS: Dict[str, str] = {
    "list_tree": (
        '<path d="M21 12h-8"/><path d="M21 6H8"/><path d="M21 18h-8"/>'
        '<path d="M3 6v4a2 2 0 0 0 2 2h3"/><path d="M3 10v6a2 2 0 0 0 2 2h3"/>'
    ),
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "microscope": (
        '<path d="M6 18h8"/><path d="M3 22h18"/><path d="M14 22a7 7 0 1 0 0-14h-1"/>'
        '<path d="M9 14h2"/><path d="M9 12a2 2 0 0 1-2-2V6h6v4a2 2 0 0 1-2 2Z"/>'
        '<path d="M12 6V3a1 1 0 0 0-1-1H9a1 1 0 0 0-1 1v3"/>'
    ),
    "git_compare": (
        '<circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/>'
        '<path d="M13 6h3a2 2 0 0 1 2 2v7"/><path d="M11 18H8a2 2 0 0 1-2-2V9"/>'
    ),
    "lightbulb": (
        '<path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1.3.5 2.6 1.5 3.5.8.8 1.3 1.5 1.5 2.5"/>'
        '<path d="M9 18h6"/><path d="M10 22h4"/>'
    ),
    "file_text": (
        '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>'
        '<path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>'
    ),
    "shield_check": (
        '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1'
        'c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.79 17 5 19 5a1 1 0 0 1 1 1Z"/>'
        '<path d="m9 12 2 2 4-4"/>'
    ),
    "book_open": (
        '<path d="M12 7v14"/>'
        '<path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13'
        'a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"/>'
    ),
    "scale": (
        '<path d="m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/>'
        '<path d="m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/>'
        '<path d="M7 21h10"/><path d="M12 3v18"/><path d="M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2"/>'
    ),
    "search_x": (
        '<path d="m13.5 8.5-5 5"/><path d="m8.5 8.5 5 5"/><circle cx="10" cy="10" r="7"/>'
        '<path d="m21 21-4.3-4.3"/>'
    ),
}


def _svg_icon(name: str, size: int = 18, color: str = "currentColor") -> str:
    inner = _ICON_PATHS[name]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0">{inner}</svg>'
    )


_STATUS_GLYPH: Dict[str, str] = {
    "idle": "○",
    "queued": "○",
    "active": "●",
    "completed": "✓",
    "failed": "✕",
}


# ---------------------------------------------------------------------------
# Global styling -- premium cool-tone palette, dark navy sidebar, Inter type
# ---------------------------------------------------------------------------


_CUSTOM_CSS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {
--app-background: #F6F8FC;
--surface-primary: #FFFFFF;
--surface-secondary: #F1F5FA;
--sidebar-background: #0B1220;
--sidebar-hover: #121D30;
--sidebar-active: #172443;
--text-primary: #101828;
--text-secondary: #667085;
--text-muted: #98A2B3;
--sidebar-text: #ECF2FF;
--sidebar-muted: #94A3B8;
--brand-primary: #4F6BED;
--brand-hover: #4059D9;
--brand-soft: #EEF1FF;
--border-soft: #E4E9F1;
--success: #22A06B;
--warning: #D99022;
--danger: #D94F5C;
}
html, body, [data-testid="stAppViewContainer"] p, h1, h2, h3, h4, h5, h6, button, input, textarea, label, [data-testid="stMarkdownContainer"] {
font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}
[data-testid="stAppViewContainer"] { background: var(--app-background); }
[data-testid="stHeader"] { background: transparent; }
.block-container { max-width: 1000px; padding-top: 3.5rem; padding-bottom: 3rem; }
[data-testid="stSidebar"] { background: var(--sidebar-background); }
[data-testid="stSidebar"] * { color: var(--sidebar-text); }
.sb-brand-title { font-size: 18px; font-weight: 700; color: var(--sidebar-text); margin-bottom: 2px; }
.sb-brand-subtitle { font-size: 12px; color: var(--sidebar-muted); margin-bottom: 22px; }
.sb-section-label { font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--sidebar-muted); margin: 4px 0 10px 2px; }
.sb-agent-row { display: flex; align-items: center; gap: 10px; padding: 9px 10px; border-radius: 10px; margin-bottom: 2px; }
.sb-agent-row.sb-active { background: var(--sidebar-active); }
.sb-agent-row .sb-status { width: 14px; font-size: 13px; text-align: center; flex-shrink: 0; }
.sb-agent-row .sb-label { font-size: 14px; font-weight: 500; }
.sb-agent-row.sb-idle .sb-label, .sb-agent-row.sb-queued .sb-label { color: var(--sidebar-muted); }
.sb-agent-row.sb-idle svg, .sb-agent-row.sb-queued svg { opacity: .55; }
.sb-agent-row.sb-completed .sb-label { color: var(--sidebar-text); }
.sb-agent-row.sb-active .sb-label { color: var(--sidebar-text); font-weight: 600; }
.sb-agent-row.sb-failed .sb-label { color: var(--danger); }
.sb-agent-row.sb-active .sb-status { animation: sb-pulse 1.4s ease-in-out infinite; }
@keyframes sb-pulse { 0%, 100% { opacity: 1; } 50% { opacity: .3; } }
.sb-footer-note { font-size: 11px; color: var(--sidebar-muted); line-height: 1.5; margin-top: 8px; }
.stButton>button, [data-testid="stDownloadButton"]>button { border-radius: 10px !important; font-weight: 600 !important; transition: background 120ms, border-color 120ms, color 120ms; }
button[kind="primary"], [data-testid="stBaseButton-primary"] { background: var(--brand-primary) !important; border-color: var(--brand-primary) !important; }
button[kind="primary"]:hover, [data-testid="stBaseButton-primary"]:hover { background: var(--brand-hover) !important; border-color: var(--brand-hover) !important; }
button[kind="secondary"], [data-testid="stBaseButton-secondary"] { background: var(--surface-primary) !important; border: 1px solid var(--border-soft) !important; color: var(--text-primary) !important; }
button[kind="secondary"]:hover, [data-testid="stBaseButton-secondary"]:hover { border-color: var(--brand-primary) !important; color: var(--brand-primary) !important; }
[data-testid="stTextInput"] input { border-radius: 12px !important; padding: 14px 16px !important; border: 1px solid var(--border-soft) !important; font-size: 15px !important; background: var(--surface-primary) !important; }
[data-testid="stTextInput"] input:focus { border-color: var(--brand-primary) !important; box-shadow: 0 0 0 3px var(--brand-soft) !important; }
[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 14px !important; border-color: var(--border-soft) !important; }
[data-testid="stExpander"] { border-radius: 14px !important; border: 1px solid var(--border-soft) !important; }
[data-testid="stMetricValue"] { color: var(--text-primary); }
[data-testid="stMetricLabel"] { color: var(--text-secondary); }
[data-testid="stTabs"] button[role="tab"] { font-weight: 600; }
.app-title { font-size: 34px; font-weight: 700; color: var(--text-primary); margin: 0 0 6px 0; }
.app-subtitle { font-size: 16px; color: var(--text-secondary); margin: 0 0 28px 0; }
.composer-label { font-size: 14px; font-weight: 600; color: var(--text-primary); margin-bottom: 8px; }
.section-caption { font-size: 13px; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: .04em; margin: 32px 0 12px 2px; }
.result-title { font-size: 24px; font-weight: 700; color: var(--text-primary); margin-bottom: 2px; }
.result-subtitle { font-size: 14px; color: var(--success); font-weight: 600; margin-bottom: 20px; }
.icon-label { display: flex; align-items: center; gap: 8px; font-weight: 600; color: var(--text-primary); }
.progress-row { display: flex; align-items: center; gap: 10px; padding: 6px 0; font-size: 14px; }
.progress-row .p-status { width: 16px; text-align: center; flex-shrink: 0; }
.progress-row.p-done { color: var(--text-primary); }
.progress-row.p-active { color: var(--brand-primary); font-weight: 600; }
.progress-row.p-queued { color: var(--text-muted); }
.progress-row.p-failed { color: var(--danger); }
.progress-row.p-active .p-status { animation: sb-pulse 1.4s ease-in-out infinite; }
.footer-note { font-size: 12px; color: var(--text-muted); text-align: center; margin-top: 44px; }
.source-meta { font-size: 12.5px; color: var(--text-secondary); }
</style>
"""


def _inject_css() -> None:
    # Every line above starts at column 0 -- Markdown treats 4+ leading
    # spaces as an indented code block, which would otherwise dump this
    # entire stylesheet onto the page as literal text instead of applying
    # it (this actually happened during development; see git history).
    st.markdown(_CUSTOM_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Sidebar -- product branding + agent names only, no descriptive paragraphs
# ---------------------------------------------------------------------------


def render_sidebar(
    placeholder,
    execution_logs: Optional[List[ExecutionLogEntry]] = None,
    in_progress: bool = False,
    report=None,
) -> None:
    """
    Render into `placeholder` (an st.sidebar.empty()) rather than directly
    into st.sidebar -- this function is called on every streamed chunk
    while a run is in progress, and writing straight to st.sidebar would
    just keep appending a new copy of the agent list below the last one
    instead of replacing it.

    `report` (a FinalReport) is optional -- when a completed report is
    available, a "Download Report" button is shown right under the
    MedResearch AI branding, above the agent list.
    """
    states = agent_progress_states(execution_logs, in_progress)

    rows = []
    for name, label in NODE_LABELS.items():
        state = states[name]
        rows.append(
            f'<div class="sb-agent-row sb-{state}">'
            f'<span class="sb-status">{_STATUS_GLYPH[state]}</span>'
            f'<span class="sb-icon">{_svg_icon(AGENT_ICON_KEY[name], size=17)}</span>'
            f'<span class="sb-label">{label}</span>'
            f"</div>"
        )

    with placeholder.container():
        st.markdown(
            '<div class="sb-brand-title">MedResearch AI</div>'
            '<div class="sb-brand-subtitle">Healthcare Evidence Intelligence</div>',
            unsafe_allow_html=True,
        )
        if report is not None:
            from agents.report import render_report_pdf  # local: keeps this a light import

            st.download_button(
                "Download Report",
                data=render_report_pdf(report),
                file_name="medresearch_report.pdf",
                mime="application/pdf",
                icon=":material/download:",
                use_container_width=True,
            )
        st.markdown(
            '<div class="sb-section-label">AI Research Team</div>' + "".join(rows),
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="sb-footer-note">Research use only — not a substitute '
            "for professional medical advice.</div>",
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Research progress -- plain-language checklist, technical detail optional
# ---------------------------------------------------------------------------


def render_progress(
    execution_logs: List[ExecutionLogEntry], in_progress: bool, placeholder
) -> None:
    states = agent_progress_states(execution_logs, in_progress)
    completed = sum(1 for s in states.values() if s == "completed")
    total = len(NODE_LABELS)

    rows = []
    for name in NODE_LABELS:
        state = states[name]
        css_state = "failed" if state == "failed" else ("done" if state == "completed" else state)
        rows.append(
            f'<div class="progress-row p-{css_state}">'
            f'<span class="p-status">{_STATUS_GLYPH[state]}</span>'
            f"<span>{AGENT_PROGRESS_PHRASE[name]}</span>"
            f"</div>"
        )

    with placeholder.container():
        st.markdown(
            "**Researching your question**" if in_progress else "**Research activity**"
        )
        st.markdown("".join(rows), unsafe_allow_html=True)
        st.progress(completed / total)
        if in_progress:
            st.caption("This usually takes under a couple of minutes.")

        with st.expander("View research activity (technical detail)"):
            counts = attempt_counts(execution_logs)
            latest = latest_log_by_node(execution_logs)
            for name, label in NODE_LABELS.items():
                entry = latest.get(name)
                badge_text, color = status_badge_for(entry)
                attempt = counts.get(name, 0)
                row_label = label + (f" (attempt {attempt})" if attempt > 1 else "")

                col_label, col_badge, col_detail = st.columns([3, 1, 4])
                col_label.write(row_label)
                col_badge.badge(badge_text, color=color)
                if entry and entry.error:
                    col_detail.caption(entry.error)
                elif entry and entry.message:
                    col_detail.caption(entry.message)


def render_warnings(errors: List[str]) -> None:
    """
    Surface non-fatal errors (Phase 21: "show a user-friendly error") in
    plain language -- e.g. one PubMed query failing, or an LLM call falling
    back to a backup model -- so they're visible without technical jargon.
    The run continues regardless; this is transparency, not a failure state.
    """
    if not errors:
        return
    with st.expander(f"{len(errors)} note(s) about this research run", expanded=False):
        for error in errors:
            st.write(friendly_error(error))
            st.caption(error)


# ---------------------------------------------------------------------------
# Completed research -- clean summary header + metric cards
# ---------------------------------------------------------------------------


def render_dashboard(final_state: ResearchState) -> None:
    report = final_state.get("final_report")
    confidence = final_state.get("confidence_score")

    if report is None or confidence is None:
        st.warning("Insufficient evidence was retrieved to support a reliable conclusion.")
        return

    st.markdown(
        f'<div class="result-title">{final_state["user_query"]}</div>'
        f'<div class="result-subtitle">Research complete</div>',
        unsafe_allow_html=True,
    )

    col_gauge, col_metrics = st.columns([1, 1])
    with col_gauge:
        st.plotly_chart(
            confidence_gauge_figure(confidence.overall, confidence.label),
            use_container_width=True,
        )
    with col_metrics:
        metric_row_1 = st.columns(2)
        metric_row_2 = st.columns(2)
        for col, (icon, label, value) in zip(
            metric_row_1 + metric_row_2,
            [
                ("book_open", "Sources", len(report.sources)),
                ("scale", "Contradictions", len(report.contradictions)),
                ("search_x", "Evidence Gaps", len(report.evidence_gaps)),
                ("lightbulb", "Insights", len(report.insights)),
            ],
        ):
            with col.container(border=True):
                st.markdown(
                    f'<div class="icon-label">{_svg_icon(icon, size=16, color="var(--text-secondary)")}'
                    f"<span>{label}</span></div>",
                    unsafe_allow_html=True,
                )
                st.markdown(f'<div style="font-size:26px;font-weight:700;margin-top:4px">{value}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Result tabs
# ---------------------------------------------------------------------------


def _render_claim_card(statement: str, citation_lookup, document_lookup) -> None:
    clean_text = strip_trailing_citation(statement)
    citation_count = len(extract_citations_from_text(statement))
    with st.container(border=True):
        st.markdown(f"**{clean_text}**")
        st.caption(f"Evidence: {citation_count} supporting source{'s' if citation_count != 1 else ''}")
        with st.expander("View evidence"):
            render_claim_trace(statement, citation_lookup, document_lookup)


def render_report_tabs(final_state: ResearchState) -> None:
    report = final_state.get("final_report")
    if report is None:
        return

    evidence_items = final_state.get("evidence") or []
    confidence = final_state.get("confidence_score")

    (
        summary_tab,
        evidence_tab,
        contradictions_tab,
        insights_tab,
        sources_tab,
        report_tab,
        analytics_tab,
    ) = st.tabs(
        ["Summary", "Evidence", "Contradictions", "Insights", "Sources", "Report", "Analytics"]
    )

    with summary_tab:
        citation_lookup = build_citation_lookup(evidence_items)
        document_lookup = build_document_lookup(report.sources)

        st.markdown('<div class="section-caption">Executive Summary</div>', unsafe_allow_html=True)
        st.write(report.executive_summary)

        st.markdown('<div class="section-caption">Key Findings</div>', unsafe_allow_html=True)
        for finding in report.key_findings:
            _render_claim_card(finding, citation_lookup, document_lookup)

        if report.effectiveness:
            st.markdown('<div class="section-caption">Benefits / Effectiveness</div>', unsafe_allow_html=True)
            for item in report.effectiveness:
                _render_claim_card(item, citation_lookup, document_lookup)

        if report.risks:
            st.markdown('<div class="section-caption">Risks &amp; Safety</div>', unsafe_allow_html=True)
            for item in report.risks:
                _render_claim_card(item, citation_lookup, document_lookup)

        if report.evidence_gaps:
            st.markdown('<div class="section-caption">Evidence Gaps</div>', unsafe_allow_html=True)
            for gap in report.evidence_gaps:
                st.markdown(f"- {gap}")

        st.markdown('<div class="section-caption">Conclusion</div>', unsafe_allow_html=True)
        st.write(report.conclusion)

    with evidence_tab:
        st.caption("Every piece of evidence behind this report, with its source and strength.")
        if not evidence_items:
            st.write("No evidence items available.")
        for item in evidence_items:
            with st.container(border=True):
                header_col, badge_col = st.columns([5, 1])
                header_col.markdown(f"**{item.claim}**")
                strength_key = item.strength.value
                badge_col.badge(
                    _EVIDENCE_STRENGTH_LABEL.get(strength_key, strength_key.title()),
                    color=_EVIDENCE_STRENGTH_BADGE_COLOR.get(strength_key, "gray"),
                )
                with st.expander("View details"):
                    st.write(item.supporting_text)
                    st.caption(f"Source: {item.source.value.upper()} · Study type: {item.study_type.value}")
                    st.caption(f"Citation: {item.citation}")

    with contradictions_tab:
        st.caption("Where credible sources genuinely disagree, explained in plain terms.")
        if not report.contradictions:
            st.info("No evidence conflicts were found among the retrieved sources.")
        for c in report.contradictions:
            with st.container(border=True):
                header_col, badge_col = st.columns([5, 1])
                header_col.markdown(f"**{c.topic}**")
                badge_col.badge(
                    c.severity.value.title(),
                    color=_CONTRADICTION_SEVERITY_BADGE_COLOR.get(c.severity.value, "gray"),
                )
                st.write(f"{c.claim_a} ({c.source_a})")
                st.write(f"{c.claim_b} ({c.source_b})")
                st.markdown("**Why results may differ**")
                st.write(c.possible_explanation)

    with insights_tab:
        st.caption("Trends and evidence gaps worth knowing about, clearly labelled where unproven.")
        if not report.insights:
            st.write("None identified.")
        for insight in report.insights:
            with st.container(border=True):
                title = "Hypothesis — not yet established" if insight.is_hypothesis else "Research Insight"
                header_col, badge_col = st.columns([5, 1])
                header_col.markdown(f"**{title}**")
                badge_col.badge(confidence_bucket_label(insight.confidence), color="blue")
                st.write(insight.insight)
                st.caption(f"Based on {len(insight.supporting_evidence)} source(s)")

    with sources_tab:
        st.caption("Every source this report draws from.")
        for doc in report.sources:
            with st.container(border=True):
                title_md = f"**[{doc.title}]({doc.url})**" if doc.url else f"**{doc.title}**"
                st.markdown(title_md)
                meta = [doc.source.value.upper()]
                if doc.publication_date:
                    meta.append(doc.publication_date)
                if doc.pmid:
                    meta.append(f"PMID {doc.pmid}")
                st.markdown(f'<span class="source-meta">{" · ".join(meta)}</span>', unsafe_allow_html=True)

    with report_tab:
        from agents.report import render_report_markdown  # local: keeps this a light import

        st.caption("Download the full report from the sidebar, under MedResearch AI.")
        st.markdown(render_report_markdown(report))

    with analytics_tab:
        col_sources, col_strength = st.columns(2)
        with col_sources.container(border=True):
            counts = source_counts_by_provider(report.sources)
            if counts:
                st.plotly_chart(
                    donut_chart_figure(counts, "Sources by provider"), use_container_width=True
                )
        with col_strength.container(border=True):
            counts = evidence_counts_by_strength(evidence_items)
            if counts:
                st.plotly_chart(
                    donut_chart_figure(counts, "Evidence strength distribution"),
                    use_container_width=True,
                )

        st.caption("Research Evidence Confidence breakdown")
        if confidence is not None:
            st.bar_chart(confidence.components.model_dump())
        st.caption("Study type distribution")
        study_type_counts = Counter(item.study_type.value for item in evidence_items)
        if study_type_counts:
            st.bar_chart(study_type_counts)

        st.caption(
            "How the final finding traces back through synthesis, supporting/"
            "contradicting evidence, sources, and the original question."
        )
        if evidence_items:
            st.plotly_chart(
                build_evidence_graph_figure(
                    final_state["user_query"],
                    report.sources,
                    evidence_items,
                    report.executive_summary,
                    report.conclusion,
                ),
                use_container_width=True,
            )
        else:
            st.write("No evidence available to graph.")


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


def main() -> None:
    st.set_page_config(page_title="MedResearch AI", page_icon="🩺", layout="wide")
    _inject_css()

    if "final_state" not in st.session_state:
        st.session_state.final_state = None
    if "question_input" not in st.session_state:
        st.session_state.question_input = ""
    # A click on an example card (rendered below the text_input) can't
    # assign st.session_state.question_input directly -- Streamlit forbids
    # writing to a widget's key after that widget has already been
    # instantiated in the same run. Stage it here instead and apply it on
    # the next run, before the text_input widget is created.
    if "pending_question" in st.session_state:
        st.session_state.question_input = st.session_state.pop("pending_question")

    sidebar_placeholder = st.sidebar.empty()
    render_sidebar(
        sidebar_placeholder,
        st.session_state.final_state["execution_logs"] if st.session_state.final_state else None,
        report=st.session_state.final_state.get("final_report") if st.session_state.final_state else None,
    )

    title_col, reset_col = st.columns([5, 1])
    with title_col:
        st.markdown('<div class="app-title">MedResearch AI</div>', unsafe_allow_html=True)
    with reset_col:
        if st.session_state.final_state is not None:
            st.write("")
            if st.button("New Research", icon=":material/refresh:"):
                st.session_state.final_state = None
                st.session_state.question_input = ""
                st.rerun()

    if st.session_state.final_state is None:
        st.markdown(
            '<div class="app-subtitle">Ask a healthcare question and get a clear, '
            "evidence-backed research report.</div>",
            unsafe_allow_html=True,
        )

        with st.container(border=True):
            st.markdown('<div class="composer-label">What would you like to research?</div>', unsafe_allow_html=True)
            question = st.text_input(
                "What would you like to research?",
                placeholder="e.g. What are the main causes and risk factors of hypertension?",
                key="question_input",
                label_visibility="collapsed",
            )
            _, cta_col = st.columns([4, 1])
            with cta_col:
                start = st.button(
                    "Start Research", type="primary", icon=":material/arrow_forward:",
                    use_container_width=True,
                )

        st.markdown('<div class="section-caption">Try asking about</div>', unsafe_allow_html=True)
        example_cols = st.columns(len(EXAMPLE_QUESTIONS))
        for col, (short_label, full_question) in zip(example_cols, EXAMPLE_QUESTIONS):
            with col:
                if st.button(short_label, key=f"example_{hash(full_question)}", use_container_width=True):
                    st.session_state.pending_question = full_question
                    st.rerun()
    else:
        question = st.session_state.question_input
        start = False

    progress_placeholder = st.empty()

    if start:
        if not question or not question.strip():
            st.error("Please enter a research question first.")
        else:
            with st.spinner("Getting the research team ready (first run only, ~30s)..."):
                from graph.workflow import build_workflow  # see note above: deliberately lazy

                app = build_workflow()
            state = create_initial_state(question.strip())
            with st.spinner("Researching your question..."):
                for chunk in app.stream(state):
                    for _node_name, update in chunk.items():
                        state.update(update)
                    render_sidebar(sidebar_placeholder, state["execution_logs"], in_progress=True)
                    render_progress(state["execution_logs"], True, progress_placeholder)
            st.session_state.final_state = state
            st.rerun()

    final_state = st.session_state.final_state
    if final_state is not None:
        render_progress(final_state["execution_logs"], False, progress_placeholder)
        render_warnings(final_state.get("errors") or [])
        render_dashboard(final_state)
        render_report_tabs(final_state)

    st.markdown(f'<div class="footer-note">{DISCLAIMER}</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()

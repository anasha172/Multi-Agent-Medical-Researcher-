# Hackathon Demo Script (Phase 26)

A ~5-minute walkthrough of MedResearch AI, narrating what the judges will
actually see on screen (not a generic script — every step below matches the
real UI built in `app.py`).

---

## Step 1 — Open the app

Say:

> "Healthcare research is difficult because the answer is rarely inside one
> paper. Our system uses multiple specialized AI agents to investigate the
> question, not a single chatbot response."

Point out the title, the pitch line, and the **Research Use Only** disclaimer
— visible before any question is even asked.

## Step 2 — Ask the demo question

Enter:

> What does current scientific evidence say about GLP-1 receptor agonists
> for obesity management, particularly weight-loss effectiveness,
> cardiovascular outcomes, adverse effects, and long-term safety?

Click **Start Research**.

## Step 3 — Show the Live Agent Execution panel

As it streams, say:

> "Instead of asking one LLM to answer this directly, a Query Planner
> agent first breaks the question into sub-questions and search queries —
> you can see it complete first, followed by Evidence Retriever, Critical
> Analysis, Contradiction Detector, Insight Generator, Report Builder, and
> Evidence Validator, each with its own status badge."

Note: the badge next to **Evidence Retriever** shows how many documents came
back — that single step runs PubMed and Tavily-restricted FDA/WHO/web
searches in parallel internally.

## Step 4 — Point out retrieval

Say:

> "We only retrieve from trusted sources — PubMed, and Tavily restricted to
> fda.gov, who.int, and ncbi.nlm.nih.gov. Nothing from the open web."

## Step 5 — Show Critical Analysis completing

Say:

> "The analysis agent evaluates study design, sample size, population, and
> limitations — a systematic review counts for more than a case report, and
> the number of sources never substitutes for evidence quality."

## Step 6 — Show the Research Dashboard

Once the run finishes, point at the **Research Evidence Confidence** gauge:

> "This is a transparent heuristic — 30% source quality, 25% evidence
> agreement, 20% study quality, 15% recency, 10% source diversity. It's a
> research-ranking score, not a clinical or diagnostic score."

Point at the source/evidence-strength charts below it.

## Step 7 — Open the Contradictions tab

Say:

> "The important part is that our system doesn't hide disagreement — it
> explicitly looks for it."

If a contradiction was found, expand its card:

> "It shows exactly what differs between the two sources, and a *possible*
> explanation — different follow-up duration or population — never stated
> as a definitive reason unless the evidence actually says so."

If none was found for this run, say the honest alternative:

> "For this particular retrieval, no major contradiction was detected among
> the sources — that's a valid outcome too, not a failure."

## Step 8 — Open the Analytics tab: the Evidence Graph

Say:

> "This is the evidence graph — question, to sources, to individual pieces
> of evidence colored by whether they support or contradict, into a
> synthesis, into the final finding. It's how we make the reasoning chain
> visually inspectable instead of a black box."

## Step 9 — Open the Summary tab and expand a finding

Click a key finding to expand it:

> "Every finding traces back to real evidence — click one and you see *why*
> it's supported: the supporting text, then the original source, with its
> title, journal, year, and link. Nothing here is a citation we invented."

## Step 10 — Close on the Conclusion and disclaimer

Read the conclusion aloud, then point at the disclaimer:

> "The report never tells the reader what to do — it describes what the
> evidence shows, including what remains uncertain. Finally, this is a
> research synthesis tool, not a diagnostic system — that's stated on
> every screen."

---

**If time is short**, Steps 3, 6, 7, and 9 are the four moments that carry
the whole pitch: live multi-agent execution, a transparent (not
black-box) confidence score, genuine contradiction detection, and
click-to-verify citation traceability.

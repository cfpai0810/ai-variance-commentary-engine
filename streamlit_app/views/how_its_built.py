# =============================================================================
# pages/how_its_built.py: "How it's built" (trust story, then technical depth)
# =============================================================================
# Two audiences on one page. Part 1 is for a finance leader: why an AI-assisted
# variance tool can be trusted (the separated layers, the flag-for-review model,
# the deterministic core, the audit trail). Part 2 is for a technical evaluator:
# the pipeline, the AI boundary, the shared builders, the safety properties, and
# the test coverage. Prose, not a README dump. Matches Project 4's page structure
# so the two read as a family, but every specific is Project 1's real design, and
# the governance model is flag-for-review, not confirm-before-run.
# =============================================================================

import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from streamlit_app.lib.theme import inject_css
from streamlit_app.lib.governance_flow import governance_flow_svg
from streamlit_app.lib.governance_lifecycle import governance_lifecycle_svg
from streamlit_app.lib.pipeline_flow import pipeline_flow_svg

st.markdown(inject_css(), unsafe_allow_html=True)

st.markdown("### How it's built")
st.write(
    "This tool was built on one idea: an AI system that touches financial numbers "
    "has to earn trust before it earns time. The sections below explain how that "
    "idea shapes the design, first for a finance reader and then in technical "
    "detail.")

# ── Part 1: the trust story (finance reader) ─────────────────────────────────
st.markdown("---")
st.markdown("#### Why you can trust the numbers")

st.write(
    "The tool never lets the language model do arithmetic. That is the whole "
    "idea. A language model is good at reading figures and describing them in "
    "clear prose. It is not a calculator, and it is not asked to be one. Every "
    "variance you see is computed by deterministic Python, the same way a "
    "spreadsheet would compute it, and the same input always produces the same "
    "output.")

st.markdown("**The work happens in separated layers.**")
components.html(governance_flow_svg(), height=300, scrolling=False)
st.write(
    "You pick a period; Python scopes the data to that month, computes every "
    "variance, and checks each line against its review threshold; the model reads "
    "the computed figures and writes the commentary; and Python decides whether "
    "the run needs a human to review it. The model never sees a number it is "
    "allowed to change, and it never produces one.")

st.markdown("**Anything the data cannot support is flagged, not explained away.**")
st.write(
    "When a line has a missing actual, a zero posting, or a variance beyond its "
    "review threshold, the tool does not ask the model to invent a confident "
    "story about it. It records the flag, leaves the variance uncomputed, and "
    'marks the run for review. It is better to say "this needs a human" than to '
    "narrate around a number that is missing or suspect.")

st.markdown("**Every run leaves a record.**")
st.write(
    "Each run is written to an audit record with a fingerprint (a SHA-256 hash) "
    "of the exact input data it used, the flags raised, the review status, the "
    "threshold policy, and the token usage. The hash is the lineage: it proves "
    "which figures produced this commentary, so a run can always be traced and "
    "reproduced. This is what a finance function needs before it will rely on a "
    "tool, assisted by AI or not.")

st.info(
    "In one line: the model reads the figures and writes the commentary; Python "
    "computes every variance and flags what needs a human; you review what is "
    "flagged. The intelligence is at the edges, and the numbers in the middle are "
    "deterministic and checkable.")

st.markdown("#### The governance lifecycle")
components.html(governance_lifecycle_svg(), height=310, scrolling=False)
st.write(
    "In a production deployment, review is the start of the record, not "
    "the end. Once a reviewer approves the commentary, the approved version "
    "becomes the immutable record: it is what everyone reads afterwards, "
    "and it cannot be edited. A later change is issued as a new, "
    "separately approved version, and the original approved commentary still "
    "stands unchanged. This live demo stops at flagging for review; it "
    "does not store or lock anything, so no data is retained. The "
    "lifecycle diagram above shows the full model this design is built "
    "towards.")

# ── Part 2: the technical detail (engineer / evaluator) ──────────────────────
st.markdown("---")
st.markdown("#### The technical detail")

st.write(
    "The system is a small, layered pipeline. Each stage has one responsibility, "
    "and the boundary between the model and the deterministic code is deliberate "
    "and strict.")

st.markdown("**The pipeline.**")
components.html(pipeline_flow_svg(), height=260, scrolling=False)
st.write(
    "Each stage has one job. The loader reads the profit-and-loss data and scopes "
    "it to the chosen period. The validator checks every line for the five "
    "conditions that raise a flag and applies the per-line review thresholds. The "
    "variance calculator computes actual-versus-budget and year-on-year figures, "
    "and leaves flagged lines uncomputed on purpose. The output layer writes the "
    "commentary, the PDF, the data-lineage hash, and the audit record.")

st.markdown("**The AI boundary is the important design choice.**")
st.write(
    "The language model appears in exactly one stage: it is handed the computed "
    "figures and the flags, and asked only to write the commentary. It is "
    "explicitly told not to calculate anything, and it has nothing to calculate "
    "with, because the numbers are already final by the time it sees them. "
    "Everything numeric, the variances, the flags, the thresholds, the hash, is "
    "deterministic Python. This is what makes the output reproducible and "
    "testable, and it means the model's known weakness, arithmetic, is never on "
    "the critical path.")

st.markdown("**One implementation, reused everywhere.**")
st.write(
    "The figures on the screen, in the PDF, in the trend chart, and in the audit "
    "come from the same functions. The PDF is built by one builder that the "
    "command-line tool writes to a file and the web serves as a download; the "
    "trend chart is one builder drawn on the screen and embedded in the report, "
    "and it asks the same validator the table does which months to flag; the data "
    "hash is one function used by both the command-line tool and the web page; "
    "and the review decision is one function shared by both. There is no second "
    "implementation to drift out of sync, so the figures on the screen, in the "
    "report, and in the record cannot disagree.")

st.markdown("**Safety properties that are enforced, not hoped for.**")
st.write(
    "A flagged line carries no computed variance anywhere: the table, the PDF, "
    "and the chart all show it as flagged rather than inventing a number for it. "
    "The commentary is stripped of stray typographic dashes by a normaliser "
    "before it is written, so the output style is guaranteed rather than left to "
    "the model. The threshold policy used for a run is recorded in the audit, so "
    "the flags are always explained by the policy that produced them. And the "
    "worked example is held to the real pipeline by tests: its commentary must "
    "match the captured run verbatim, its flags and its hash must equal what the "
    "pipeline produces for the same data, and its flagged rows must carry no "
    "variance. Each of these is covered by a test that fails if the property is "
    "broken.")

st.markdown("**Tested to a level a finance tool should be.**")
st.write(
    "The suite covers the flag logic and its five conditions, the per-line "
    "thresholds, the period scoping, the variance calculations, the review "
    "decision, the cost estimate, the shared builders, and the fabrication guards "
    "on the worked example. The web layer reuses the same tested pipeline "
    "unchanged; the pages orchestrate and render, they never recompute. Reports "
    "and charts are generated in memory for download rather than written to a "
    "shared file, so nothing one visitor does can affect another.")

st.markdown("**Built for a public, keyless demo.**")
st.write(
    "Everything here runs on a synthetic sample entity, so there is no "
    "confidential data anywhere in the app or its history. The worked example "
    "needs no API key, so the reasoning and the output are visible even without "
    "running a live analysis.")

st.divider()
st.caption(
    "The sample data is synthetic and the figures are illustrative. The "
    "architecture, the governance model, and the test coverage are real.")

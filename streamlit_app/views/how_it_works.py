# =============================================================================
# pages/how_it_works.py: the mechanics a finance evaluator wants to understand
# =============================================================================
# Explains the pipeline, what gets flagged, the per-line review thresholds, the
# review model, and the audit hash. No API key needed. Docs page: matches the
# family structure (title, intro, sections), no key gate rendered here.
# =============================================================================

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from streamlit_app.lib.theme import inject_css

st.markdown(inject_css(), unsafe_allow_html=True)

st.markdown("### How it works")
st.write(
    "The tool runs a fixed pipeline for the period you choose. It loads the "
    "data, scopes it to that month, computes the variances in Python, flags "
    "anything the data cannot support, asks the language model to write the "
    "commentary, and records the run. The model writes; it never calculates. "
    "Every figure in the output and the report is computed deterministically.")

st.markdown("---")

# ── What gets flagged ─────────────────────────────────────────────────────────
st.markdown("#### What gets flagged")
st.write(
    "Before any commentary is written, each line is checked. Five situations "
    "raise a flag: a missing actual, a missing budget, a zero budget, a zero "
    "actual, and a variance larger than that line's review threshold. A flagged "
    "line is not given a confident explanation it does not deserve; instead the "
    "tool records the flag and notes that the item needs review. This is "
    'deliberate: it is better to say "this needs a human" than to narrate around '
    "a number that is missing or suspect.")

# ── Per-line review thresholds ────────────────────────────────────────────────
st.markdown("#### Per-line review thresholds")
st.write(
    "A single variance threshold does not fit every line. A ten percent swing in "
    "revenue is material and worth flagging early; a volatile line like R&D "
    "routinely moves and only warrants attention past a much larger change. So "
    "each line has its own review threshold, with sensible defaults (revenue "
    "flags at ten percent, R&D at one hundred, others in between). You can adjust "
    "them for a run, and the policy used is shown on the output and written into "
    "the record, so the flags are always explained by the thresholds that "
    "produced them.")

# ── Review before you rely on it ──────────────────────────────────────────────
st.markdown("#### Review before you rely on it")
st.write(
    "When any line is flagged, or the commentary is truncated or unusually "
    "short, the tool marks the run as needing review and says why. A clean month "
    "says so plainly. The point is that the output declares its own limits rather "
    "than presenting every run as final.")

# ── A record for every run ────────────────────────────────────────────────────
st.markdown("#### A record for every run")
st.write(
    "Each run is recorded with a fingerprint (a hash) of the exact input data it "
    "used, the flags raised, the review status, the threshold policy, and the "
    "token usage with an estimated cost. The hash is the lineage: it proves "
    "which figures produced this commentary, so a run can always be traced and "
    "reproduced. On the web this record is kept for the session; run locally, it "
    "is written to a permanent audit log.")

st.divider()
st.caption("Sample data only. All figures are illustrative.")

# =============================================================================
# Home.py: the app shell and landing page (Streamlit entry point)
# =============================================================================
# Run locally: streamlit run streamlit_app/Home.py
# Docs-first nav (matching Project 4's family structure): Home, How it works,
# then the Variance Commentary tool. The shared foundation (theme, key gate,
# error wrapper, client seam) is reused directly from Project 4; only this shell
# and the tool/docs pages are Project-1 specific.
# =============================================================================

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from streamlit_app.lib.theme import inject_css
from streamlit_app.lib.key_gate import render_key_gate

from config import SAMPLE_DATA


def _home_page():
    """Render the landing page content."""
    st.markdown(inject_css(), unsafe_allow_html=True)

    # ── Header ───────────────────────────────────────────────────────────────
    st.markdown(
        '<div class="sc-header">'
        '<h1>Variance Commentary</h1>'
        "<p>Turn a month's budget-versus-actual figures into review-ready "
        'commentary, with every number computed by Python and every exception '
        'flagged before a person signs off.</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── The key gate (sidebar): returns a per-session client or None ─────────
    client = render_key_gate()
    st.session_state["vc_live_client"] = client

    # ── What this does ───────────────────────────────────────────────────────
    st.markdown("#### What this does")
    st.write(
        "Every month, finance teams write the same thing: the narrative that "
        "explains why actuals landed above or below budget. This tool drafts "
        "that commentary for a chosen period. You pick a month, and it computes "
        "the variance for every line, flags anything that needs a human eye, and "
        "writes a clear, CFO-ready commentary on what happened and why.")
    st.write(
        "One principle holds it together: the model reads the figures and writes "
        "the commentary; Python computes every variance; and anything the data "
        "cannot support, a missing actual, a zero posting, a variance beyond its "
        "review threshold, is flagged for review rather than explained away. The "
        "model only ever describes numbers it did not calculate and cannot "
        "change. And every run records a fingerprint of the exact data it used, "
        "so the commentary can always be traced back to the figures that "
        "produced it.")

    # ── The sample company ───────────────────────────────────────────────────
    st.markdown("#### The sample company")
    st.write(
        "The demo runs on Valencia Operations, a synthetic company built for the "
        "purpose, with twelve months of profit-and-loss data across seven lines. "
        "Because the figures are entirely fictional, nothing here touches real or "
        "confidential information. Different months tell different stories: some "
        "close cleanly, others carry a missing actual, a zero posting, or a large "
        "swing that needs review, so you can see how the tool behaves when the "
        "data is imperfect.")

    if Path(SAMPLE_DATA).exists():
        st.success(
            "Sample dataset loaded. All figures on this site are illustrative.")
    else:
        st.warning(
            "The sample data file is missing (data/sample_pnl.csv). The tool "
            "page needs it to build the period list.")

    # ── Using your own API key ───────────────────────────────────────────────
    st.markdown("#### Using your own API key")
    st.write(
        "The worked example runs with no key. To generate commentary yourself, "
        "you supply your own Anthropic API key, and each run bills your own "
        "Anthropic account a small amount (a single period is well under one US "
        "cent in practice; the tool shows an estimate for every run). The key is "
        "used only for your session and is not stored. On the web the data stays "
        "sample-only; to work on your own figures, run the project locally from "
        "GitHub.")

    # ── Where to start ───────────────────────────────────────────────────────
    st.markdown("#### Where to start")
    st.write(
        "Read How it works for the mechanics: which situations get flagged, how "
        "the per-line review thresholds work, and how each run is recorded. Or "
        "open Variance Commentary and try it: the worked example needs no key, "
        "and you can pick any of the twelve months to see the commentary change.")

    st.divider()
    st.caption("Sample data only. All figures are illustrative.")


# ── Multipage navigation (Streamlit >= 1.36), docs-first ──────────────────────
st.set_page_config(
    page_title="Variance Commentary",
    page_icon="•",
    layout="centered",
    initial_sidebar_state="expanded",
)

# The view files live in a folder NOT named "pages", so Streamlit's automatic
# pages/ navigation never triggers and st.navigation() below is the sole nav
# (with these explicit titles and this order, not filename-derived alphabetical).
VIEWS_DIR = Path(__file__).resolve().parent / "views"

pg = st.navigation([
    st.Page(_home_page, title="Home", icon=":material/home:"),
    st.Page(str(VIEWS_DIR / "how_it_works.py"),
            title="How it works", icon=":material/menu_book:"),
    st.Page(str(VIEWS_DIR / "variance_commentary.py"),
            title="Variance Commentary", icon=":material/description:"),
    st.Page(str(VIEWS_DIR / "your_own_data.py"),
            title="Your own data", icon=":material/upload_file:"),
    st.Page(str(VIEWS_DIR / "how_its_built.py"),
            title="How it's built", icon=":material/build:"),
])

pg.run()

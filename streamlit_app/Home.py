# =============================================================================
# Home.py: the app shell and landing page (Streamlit entry point)
# =============================================================================
# Run locally: streamlit run streamlit_app/Home.py
# Docs-first nav (matching Project 4's family structure): Home, How it works,
# then the Variance commentary tool. The shared foundation (theme, key gate,
# error wrapper, client seam) is reused directly from Project 4; only this shell
# and the tool/docs pages are Project-1 specific.
# =============================================================================

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from streamlit_app.lib.theme import header_html, inject_css
from streamlit_app.lib.key_gate import render_key_gate

from config import SAMPLE_DATA


def _home_page():
    """Render the landing page content: the banner, the worked example button,
    then three short blocks (what it does, the governance promise, the pages)."""
    st.markdown(inject_css(), unsafe_allow_html=True)

    st.markdown(header_html(
        "Variance Commentary",
        "Turn a month's budget-versus-actual figures into review-ready "
        "commentary. Python computes the variances, and every exception is "
        "flagged before a person signs off."),
        unsafe_allow_html=True)

    # One click to the worked example, which needs no key: the Variance
    # commentary page opens on it, its first tab.
    if st.button("See the worked example"):
        st.switch_page(VARIANCE_PAGE)

    # ── The key gate (sidebar): returns a per-session client or None ─────────
    client = render_key_gate()
    st.session_state["vc_live_client"] = client

    st.markdown("#### What it does")
    st.markdown(
        "- Reads a month's budget and actual figures for seven profit and loss "
        "lines.\n"
        "- Computes each line's variance in Python and flags what needs a "
        "person: a missing or zero figure, or a variance beyond the line's "
        "review threshold. A flagged line shows no variance.\n"
        "- Drafts the commentary from those figures with the model (Claude, via "
        "the Anthropic API) and your own key.\n"
        "- Produces a PDF of the figures, the flags and the commentary, a DRAFT "
        "until a named reviewer signs it.")

    st.markdown("#### The governance promise")
    st.markdown(
        "- **Python computes.** Every variance is calculated in code, and the "
        "same input gives the same output.\n"
        "- **A rule flags.** What needs review is decided by rules in code and "
        "a threshold per line, not by the model's opinion.\n"
        "- **The model describes.** It writes about figures it was given and "
        "cannot change them. This version does not check the numbers in its "
        "wording.\n"
        "- **The reviewer signs.** Nothing is final until a named reviewer reads "
        "it and signs.")

    st.markdown("#### Pages")
    st.page_link(HOW_IT_WORKS, label="How it works: what gets flagged, the "
                 "review thresholds and the record of each run")
    st.page_link(VARIANCE_PAGE, label="Variance commentary: a worked example "
                 "for March 2026, and a run on any of the twelve months with "
                 "your own key")
    st.page_link(OWN_DATA, label="Your own data: the CSV format and how to "
                 "run it locally")
    st.page_link(HOW_ITS_BUILT, label="How it's built: why the numbers can be "
                 "trusted, the pipeline and the tests")

    # ── Using your own API key (closed until opened) ─────────────────────────
    with st.expander("Using your own API key"):
        st.write(
            "The worked example runs with no key. To generate commentary yourself, "
            "you supply your own Anthropic API key, and each run bills your own "
            "Anthropic account a small amount (a single period costs about 1.9 US "
            "cents at the configured rates; the tool shows an estimate for every "
            "run). The key is used only for your session and is not stored. On the "
            "web the data stays sample-only; to work on your own figures, run the "
            "project locally from GitHub.")

    st.divider()
    st.caption("Sample data only: Valencia Operations is a fictional company, "
               "with twelve months of profit and loss data across seven lines. "
               "All figures are illustrative.")

    if not Path(SAMPLE_DATA).exists():
        st.warning(
            "The sample data file is missing (data/sample_pnl.csv). The tool "
            "page needs it to build the period list.")


# ── Multipage navigation (Streamlit >= 1.36), docs-first ──────────────────────
st.set_page_config(
    page_title="Variance Commentary",
    page_icon=":material/bar_chart:",
    layout="centered",
    initial_sidebar_state="auto",
)

# The view files live in a folder NOT named "pages", so Streamlit's automatic
# pages/ navigation never triggers and st.navigation() below is the sole nav
# (with these explicit titles and this order, not filename-derived alphabetical).
# Each page's address comes from its file name, so a title can change without
# moving a published link.
VIEWS_DIR = Path(__file__).resolve().parent / "views"
HOW_IT_WORKS = st.Page(str(VIEWS_DIR / "how_it_works.py"),
                       title="How it works", icon=":material/menu_book:")
VARIANCE_PAGE = st.Page(str(VIEWS_DIR / "variance_commentary.py"),
                        title="Variance commentary", icon=":material/bar_chart:")
OWN_DATA = st.Page(str(VIEWS_DIR / "your_own_data.py"),
                   title="Your own data", icon=":material/upload_file:")
HOW_ITS_BUILT = st.Page(str(VIEWS_DIR / "how_its_built.py"),
                        title="How it's built", icon=":material/build:")

pg = st.navigation([
    st.Page(_home_page, title="Home", icon=":material/home:"),
    HOW_IT_WORKS,
    VARIANCE_PAGE,
    OWN_DATA,
    HOW_ITS_BUILT,
])

pg.run()

# =============================================================================
# lib/pipeline_flow.py - the pipeline diagram (matches governance_flow's language)
# =============================================================================
# Same visual grammar as governance_flow.py: purple = the model (used only for
# language, never numbers), green = deterministic engine, blue = data. Drawn in
# HTML by lib/flow_diagram.py, so it reads on a phone. Shows the AI boundary:
# the model appears in exactly ONE of five stages; everything numeric is
# deterministic. Pure function so any page can render it and it stays
# consistent.
# =============================================================================

from streamlit_app.lib.flow_diagram import Role, Stage, flow_html
from streamlit_app.lib.governance_flow import ENGINE, MODEL
from streamlit_app.lib.theme import DARK_BLUE, LIGHT_BLUE

DATA = Role(DARK_BLUE, LIGHT_BLUE)

LABEL = ("The pipeline: a deterministic loader reads the profit-and-loss data and "
         "scopes it to the chosen period; a deterministic validator checks every "
         "line for the five flag conditions and applies the per-line thresholds; "
         "a deterministic calculator computes the variances and leaves flagged "
         "lines uncomputed; the model reads the computed figures and writes the "
         "commentary; and a deterministic output layer writes the PDF, the data "
         "hash, and the audit record. Only the commentary stage uses the model; "
         "everything numeric is deterministic.")

STAGES = (
    Stage("Load", "read P&L, scope to month", "deterministic", DATA),
    Stage("Validate", "five checks, thresholds", "deterministic", ENGINE),
    Stage("Compute", "variances, skip flagged", "deterministic", ENGINE),
    Stage("Commentary", "figures to words", "model, language", MODEL),
    Stage("Output", "PDF, hash, audit record", "deterministic", ENGINE),
)


def pipeline_flow_html():
    """Return the pipeline diagram as HTML for st.markdown."""
    return flow_html(
        LABEL, STAGES,
        heading="The model appears in one stage only. Everything numeric is "
                "deterministic.",
        note="The commentary stage is handed already-final figures; the model has "
             "nothing to calculate with.",
        key=((MODEL, "Model, for language"),
             (ENGINE, "Deterministic code, for numbers")))

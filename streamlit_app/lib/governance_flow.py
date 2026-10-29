# =============================================================================
# lib/governance_flow.py - the signature diagram (Project 1: flag for review)
# =============================================================================
# The flag-for-review governance model as a flow. A person opens and closes every
# run; the model works only in between and never touches a figure. Colour encodes
# WHO OWNS each step: the person (blue), the model for language (purple), the
# deterministic engine for numbers (green). This is Project 1's model, NOT a
# confirm-before-run gate: there is no approval before a run, only a flag for
# review after it. Drawn in HTML by lib/flow_diagram.py, so it reads on a phone.
# =============================================================================

from streamlit_app.lib.flow_diagram import Role, Stage, flow_html
from streamlit_app.lib.theme import DARK_BLUE, GREEN, LIGHT_BLUE

PERSON = Role(DARK_BLUE, LIGHT_BLUE)
MODEL  = Role("#6B4FA8", "#F0ECF8")     # purple: the model handles language, not numbers
ENGINE = Role(GREEN, "#E8F3E9")

LABEL = ("How a run is governed: you pick a period, Python computes every "
         "variance and checks each line against its threshold, the model reads "
         "the figures and writes the commentary, Python marks any run that needs "
         "a human, and you review what is flagged. Every run is written to the "
         "audit record with a hash of the input data.")

STAGES = (
    Stage("YOU PICK A PERIOD", "A month to report on", "the person", PERSON),
    Stage("PYTHON COMPUTES", "Every variance, checks thresholds", "no model here",
          ENGINE),
    Stage("THE MODEL WRITES", "Reads the figures, writes commentary",
          "words, not numbers", MODEL),
    Stage("MARKED FOR REVIEW", "Python flags what needs a human", "no model here",
          ENGINE),
    Stage("YOU REVIEW", "You check the flagged lines", "the person", PERSON),
)


def governance_flow_html():
    """Return the governance flow diagram as HTML for st.markdown."""
    return flow_html(
        LABEL, STAGES,
        heading="You open and close every run. The model works only in between.",
        note="Every run is written to the audit record, with a hash of the input "
             "data, so it can be traced and reproduced.",
        key=((PERSON, "You"), (MODEL, "The model, for language"),
             (ENGINE, "Deterministic code, for numbers")))

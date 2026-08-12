# =============================================================================
# lib/policy.py - the percent/fraction boundary for the threshold control
# =============================================================================
# The core pipeline always works in FRACTIONS (0.10). The UI always shows
# PERCENTAGES (10). Convert once, here, at the boundary - never twice. A double
# conversion turns 10% into 0.001 and flags almost everything, so this single
# choke point is deliberately small and tested.
#
# Pure functions only: no Streamlit, no IO, so they import and test cleanly.
# =============================================================================

# Short labels for the one-line policy note (the account keys are the full P&L
# line names; the note reads better abbreviated).
SHORT_LABELS = {
    "Revenue": "Revenue",
    "COGS": "COGS",
    "Marketing Spend": "Marketing",
    "Headcount Cost": "Headcount",
    "IT Infrastructure": "IT",
    "Legal & Compliance": "Legal",
    "R&D Expense": "R&D",
}


def build_policy_from_ui(percent_map, default_percent):
    """Convert UI percentages to the fraction policy the pipeline expects.

    Converts ONCE (percent / 100). '_default' is always present, so
    validate_and_flag's .get(account, policy['_default']) fallback never fails.

    percent_map:     {account: percent} e.g. {'Revenue': 10.0}
    default_percent: the global default as a percent e.g. 50.0
    returns:         {account: fraction, ..., '_default': fraction}
    """
    # Snap to whole percents so the provenance note and the flag string (which
    # step1 renders via {:.0%}) always show the same number - there is no
    # sub-percent precision left to lose. round() once, here, at the single
    # boundary where percents become fractions; do not round anywhere else.
    policy = {account: round(pct) / 100.0 for account, pct in percent_map.items()}
    policy["_default"] = round(default_percent) / 100.0
    return policy


def _pct(fraction):
    """Format a fraction as a percentage string, dropping a trailing '.0'."""
    value = fraction * 100.0
    text = "{:.0f}".format(value) if value == int(value) else "{:.1f}".format(value)
    return text + "%"


def policy_note(policy):
    """One-line provenance note, percentages only, no dashes. e.g.
    'Flagging policy: Revenue 10%, COGS 15%, ..., default 50%'."""
    parts = []
    for account, fraction in policy.items():
        if account == "_default":
            continue
        parts.append("{} {}".format(SHORT_LABELS.get(account, account),
                                    _pct(fraction)))
    parts.append("default {}".format(_pct(policy["_default"])))
    return "Flagging policy: " + ", ".join(parts)

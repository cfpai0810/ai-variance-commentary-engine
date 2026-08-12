# =============================================================================
# lib/example_variance.py - the keyless worked example (real, not fabricated)
# =============================================================================
# The example a cold visitor sees without an API key. It must show exactly what
# the live tool produces for March, so every value traces to a committed real
# source:
#   - commentary: VERBATIM from docs/sample_output.txt (the only AI-generated part)
#   - table, flags, hash, policy: the deterministic recompute of the committed
#     March rows through the same pure pipeline functions the live path uses.
#
# Nothing is hand-authored. The commentary is read from the file; the numbers are
# computed. No API call.
# =============================================================================

import json
from pathlib import Path

from config import SAMPLE_DATA, DEFAULT_ENTITY
from src.step1_data_loader import (
    load_pnl, filter_to_period, validate_and_flag, calculate_variances,
)

ROOT = Path(__file__).resolve().parent.parent.parent
DOCS = ROOT / "docs"
EXAMPLE_PERIOD = "March 2026"


def _extract_commentary(sample_text):
    """The verbatim model commentary is everything from EXECUTIVE SUMMARY onward;
    the lines before it are the file's metadata header, not commentary."""
    return sample_text[sample_text.index("EXECUTIVE SUMMARY"):].strip()


def load_example():
    """Build the worked example from the committed real sources. Commentary is
    verbatim from docs/sample_output.txt; the table, flags, hash and policy are the
    deterministic recompute of the committed March rows through the same pure
    functions the live path uses. No API call; nothing fabricated."""
    df = load_pnl(SAMPLE_DATA)
    df = filter_to_period(df, EXAMPLE_PERIOD)
    df, flags = validate_and_flag(df)              # config policy
    df = calculate_variances(df, flags)

    commentary = _extract_commentary(
        (DOCS / "sample_output.txt").read_text(encoding="utf-8"))
    audit = json.loads(
        (DOCS / "audit_log_sample.jsonl").read_text(encoding="utf-8"))

    return {
        "period": EXAMPLE_PERIOD,
        "entity": DEFAULT_ENTITY,
        "commentary": commentary,
        "df": df,
        "flags": flags,
        "policy": audit["thresholds"],
        "input_hash": audit["input_hash"],
        "input_tokens": audit["input_tokens"],
        "output_tokens": audit["output_tokens"],
        "stop_reason": audit["stop_reason"],
        "generated_at": audit["run_id"],
        "requires_review": audit["requires_review"],
    }

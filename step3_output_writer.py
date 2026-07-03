# =============================================================================
# output_writer.py — Layer 4: Output Writing and Audit Trail
# =============================================================================
# Responsibilities:
#   - Write commentary to a timestamped text file
#   - Compute SHA256 hash of the input file for audit trail
#   - Append one JSONL record to the audit log per run
#   - Set human review flag when flags are raised or output truncated
#
# This layer knows about: file paths, audit logs, timestamps
# This layer does NOT know about: Claude, prompts, DataFrames
# =============================================================================

import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

from config import (
    OUTPUT_DIR,
    AUDIT_LOG,
    DEFAULT_PERIOD,
    DEFAULT_ENTITY,
    MODEL,
)


# =============================================================================
# FUNCTION 1: Write commentary file and audit log
# =============================================================================
def write_output(commentary, input_file, flags, tok_in, tok_out, stop_reason):
    """
    Write the commentary to a text file and append one record to the audit log.

    Finance context: Every AI-generated output must be traceable. The
    audit log answers the four questions a CFO or auditor will ask:
    - Which data produced this output?  (input_hash)
    - Which model was used?             (model)
    - Were any data problems found?     (flags_raised)
    - Has a human reviewed this?        (human_reviewed - always False on creation)

    The input_hash is a SHA256 hash of the raw CSV file bytes. Hashing
    the file directly means the hash is stable and reproducible: the
    same file always produces the same hash, proving which exact data
    version produced which output.

    Args:
        commentary:  string returned by call_claude()
        input_file:  Path to the CSV that was processed
        flags:       list of flag strings from validate_and_flag()
        tok_in:      input token count from call_claude()
        tok_out:     output token count from call_claude()
        stop_reason: stop reason string from call_claude()

    Returns:
        output_path: Path to the written commentary file
    """
    input_file = Path(input_file)

    # Ensure output folder exists - no error if already present
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Build a filesystem-safe UTC timestamp
    # UTC avoids ambiguity across time zones
    # Underscores replace colons - colons are illegal in Windows filenames
    now     = datetime.now(timezone.utc)
    ts_file = now.strftime("%Y-%m-%d_%H-%M-%S")
    ts_log  = now.isoformat()

    # ── Write the commentary text file ───────────────────────────────────────
    output_filename = "variance_commentary_{}.txt".format(ts_file)
    output_path     = OUTPUT_DIR / output_filename

    # Named format keys used throughout - safer than positional {} arguments
    # because order cannot be accidentally swapped
    header = (
        "VARIANCE COMMENTARY - GENERATED OUTPUT\n"
        "{sep}\n"
        "Generated:  {ts}\n"
        "Period:     {period}\n"
        "Entity:     {entity}\n"
        "Input file: {fname}\n"
        "Model:      {model}\n"
        "Tokens:     {tok_in:,} in / {tok_out:,} out\n"
        "Flags:      {nflags} raised\n"
        "{sep}\n\n"
    ).format(
        sep    = "=" * 60,
        ts     = ts_log,
        period = DEFAULT_PERIOD,
        entity = DEFAULT_ENTITY,
        fname  = input_file.name,
        model  = MODEL,
        tok_in = tok_in,
        tok_out= tok_out,
        nflags = len(flags),
    )

    output_path.write_text(header + commentary, encoding="utf-8")

    # ── Compute SHA256 hash of the raw input file ─────────────────────────────
    # Read as raw bytes - not through pandas - so the hash is stable
    # The same file always produces the same hash regardless of how
    # pandas internally represents the data
    with open(input_file, "rb") as f:
        input_hash = "sha256:" + hashlib.sha256(f.read()).hexdigest()

    # ── Determine if human review is required ─────────────────────────────────
    # Required when: flags were raised (data problems found)
    #             OR response was truncated (output may be incomplete)
    requires_review = len(flags) > 0 or stop_reason == "max_tokens"

    # ── Build the audit record ────────────────────────────────────────────────
    audit_record = {
        "run_id":          ts_log,
        "project":         "variance-commentary-engine",
        "period":          DEFAULT_PERIOD,
        "entity":          DEFAULT_ENTITY,
        "input_file":      str(input_file),
        "input_hash":      input_hash,
        "output_file":     str(output_path),
        "model":           MODEL,
        "input_tokens":    tok_in,
        "output_tokens":   tok_out,
        "stop_reason":     stop_reason,
        "flags_raised":    flags,
        "human_reviewed":  False,
        "requires_review": requires_review,
    }

    # ── Append to JSONL audit log ─────────────────────────────────────────────
    # 'a' mode appends - never overwrites previous runs
    # Each line is one complete JSON record - JSONL format
    # One file, one line per run, permanent history
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(audit_record) + "\n")

    # ── Confirmation print ────────────────────────────────────────────────────
    print("[OK] Output written")
    print("     Commentary: {}".format(output_path))
    print("     Audit log:  {}".format(AUDIT_LOG))
    print("     Input hash: {}...".format(input_hash[:30]))
    print("     Requires human review: {}".format(requires_review))
    if requires_review:
        print("     Reason: {} flag(s) raised".format(len(flags)))

    return output_path
# =============================================================================
# main.py — Orchestrator (Step 2 of Pass 2 — ai_engine.py complete)
# =============================================================================

import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

from data_loader import load_pnl, validate_and_flag, calculate_variances
from ai_engine   import build_prompt, call_claude
from config import (
    MODEL,
    OUTPUT_DIR,
    SAMPLE_DATA,
    AUDIT_LOG,
    DEFAULT_PERIOD,
    DEFAULT_ENTITY,
)


# =============================================================================
# STEP 6: Write output file and audit log
# =============================================================================
def write_output(commentary, input_file, flags, tok_in, tok_out, stop_reason):
    """
    Write the commentary to a text file and append one record to the audit log.

    Finance context: Every AI-generated output must be traceable. The audit
    log answers the four questions a CFO or auditor will ask:
    - Which data produced this output?  (input_hash)
    - Which model was used?             (model)
    - Were any data problems found?     (flags_raised)
    - Has a human reviewed this?        (human_reviewed — always False on creation)

    The input_hash is a SHA256 hash of the raw CSV file bytes — not the
    DataFrame. Hashing the file directly means the hash is stable and
    reproducible: the same file always produces the same hash.

    Args:
        commentary:   string returned by call_claude()
        input_file:   Path to the CSV that was processed
        flags:        list of flag strings from validate_and_flag()
        tok_in:       input token count from call_claude()
        tok_out:      output token count from call_claude()
        stop_reason:  stop reason string from call_claude()

    Returns:
        output_path: Path to the written commentary file
    """
    import hashlib
    import json
    from datetime import datetime, timezone

    input_file = Path(input_file)

    # ── Ensure output folder exists ───────────────────────────────────────────
    # exist_ok=True means no error if the folder already exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── Build a filesystem-safe timestamp ─────────────────────────────────────
    # Use UTC time so the log is unambiguous across time zones
    # Replace colons with underscores — colons are illegal in Windows filenames
    now       = datetime.now(timezone.utc)
    ts_file   = now.strftime("%Y-%m-%d_%H-%M-%S")   # for the filename
    ts_log    = now.isoformat()                       # for the audit log

    # ── Write the commentary text file ───────────────────────────────────────
    output_filename = f"variance_commentary_{ts_file}.txt"
    output_path     = OUTPUT_DIR / output_filename

    # Write a header block above the commentary for human readers
    header = (
        f"VARIANCE COMMENTARY — GENERATED OUTPUT\n"
        f"{'='*60}\n"
        f"Generated:  {ts_log}\n"
        f"Period:     {DEFAULT_PERIOD}\n"
        f"Entity:     {DEFAULT_ENTITY}\n"
        f"Input file: {input_file.name}\n"
        f"Model:      {MODEL}\n"
        f"Tokens:     {tok_in:,} in / {tok_out:,} out\n"
        f"Flags:      {len(flags)} raised\n"
        f"{'='*60}\n\n"
    )

    output_path.write_text(
        header + commentary,
        encoding="utf-8"
    )

    # ── Compute SHA256 hash of the raw input file ─────────────────────────────
    # Read the file as raw bytes — not through pandas — so the hash is stable
    # The same file always produces the same hash regardless of how pandas
    # internally represents the data
    with open(input_file, "rb") as f:
        raw_bytes  = f.read()
        input_hash = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()

    # ── Determine human review requirement ────────────────────────────────────
    # Human review is required if any flags were raised or if the response
    # was truncated — both indicate the output needs checking before use
    requires_review = len(flags) > 0 or stop_reason == "max_tokens"

    # ── Build the audit record ────────────────────────────────────────────────
    audit_record = {
        "run_id":         ts_log,
        "project":        "variance-commentary-engine",
        "period":         DEFAULT_PERIOD,
        "entity":         DEFAULT_ENTITY,
        "input_file":     str(input_file),
        "input_hash":     input_hash,
        "output_file":    str(output_path),
        "model":          MODEL,
        "input_tokens":   tok_in,
        "output_tokens":  tok_out,
        "stop_reason":    stop_reason,
        "flags_raised":   flags,
        "human_reviewed": False,
        "requires_review": requires_review,
    }

    # ── Append to audit log ───────────────────────────────────────────────────
    # 'a' mode appends — never overwrites previous runs
    # Each line is one complete JSON record — JSONL format
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(audit_record) + "\n")

    # ── Confirmation print ────────────────────────────────────────────────────
    print(f"\n[OK] Output written")
    print(f"     Commentary: {output_path}")
    print(f"     Audit log:  {AUDIT_LOG}")
    print(f"     Input hash: {input_hash[:30]}...")
    print(f"     Requires human review: {requires_review}")
    if requires_review:
        print(f"     Reason: {len(flags)} flag(s) raised")

    return output_path

# =============================================================================
# MAIN — Pass 1 complete
# =============================================================================
if __name__ == '__main__':

    # Step 1: Load
    df = load_pnl(SAMPLE_DATA)

    # Step 2: Validate
    df, flags = validate_and_flag(df)

    # Step 3: Calculate variances
    df = calculate_variances(df, flags)

    # Step 4: Build prompts
    system_prompt, user_prompt = build_prompt(
        df, flags, DEFAULT_PERIOD, DEFAULT_ENTITY
    )

    # Step 5: Call Claude
    commentary, tok_in, tok_out, stop_reason = call_claude(
        system_prompt, user_prompt
    )

    # Step 6: Write output and audit log
    output_path = write_output(
        commentary, SAMPLE_DATA, flags, tok_in, tok_out, stop_reason
    )

    print(f"\n[DONE] Pipeline complete.")
    print(f"       Open {output_path} to read the commentary.")
    print(f"       Open {AUDIT_LOG} to review the audit log.")
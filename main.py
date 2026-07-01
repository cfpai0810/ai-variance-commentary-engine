# =============================================================================
# main.py — Project 1: AI Variance Commentary Engine
# Pass 1: flat script, console output, understand every line
# =============================================================================

import pandas as pd
import anthropic
import os
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from config import (
    ANTHROPIC_API_KEY,
    MODEL,
    MAX_TOKENS,
    DATA_DIR,
    OUTPUT_DIR,
    SAMPLE_DATA,
    AUDIT_LOG,
    DEFAULT_PERIOD,
    DEFAULT_ENTITY,
    LARGE_VARIANCE_THRESHOLD,
)

# ── Initialise the Claude client once at module level ─────────────────────────
# Creating the client here means it is reused for every call in the session.
# Never recreate the client inside a function — it wastes time and memory.
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── Required columns — any CSV missing these is rejected immediately ───────────
REQUIRED_COLUMNS = {'date', 'account', 'department', 'actual', 'budget', 'prior_year'}


# =============================================================================
# STEP 1: Load the P&L data
# =============================================================================
def load_pnl(filepath):
    """
    Load a P&L CSV file and return a clean, typed DataFrame.

    Finance context: This is the equivalent of opening your P&L export
    from the ERP. We enforce column presence and data types upfront —
    garbage in, garbage out. A missing column or wrong type here would
    silently corrupt every variance calculation downstream.

    Args:
        filepath: Path to the CSV file (string or Path object)

    Returns:
        pandas DataFrame with validated columns and correct dtypes

    Raises:
        FileNotFoundError: if the file does not exist
        ValueError: if required columns are missing or file is empty
    """
    filepath = Path(filepath)

    # 1. Check the file exists before pandas tries to open it
    #    pandas gives a confusing error on missing files — we give a clear one
    if not filepath.exists():
        raise FileNotFoundError(
            f"Data file not found: {filepath}\n"
            f"Expected location: {filepath.resolve()}\n"
            f"Check the filename and folder path."
        )

    # 2. Read the CSV with explicit dtypes
    #    actual, budget, prior_year are float (not int) because:
    #    - float naturally handles NaN (missing values) — int cannot
    #    - real P&L exports often contain decimals
    #    - a blank cell in a float column becomes NaN automatically
    df = pd.read_csv(
        filepath,
        dtype={
            'date':       'str',
            'account':    'str',
            'department': 'str',
            'actual':     'float64',
            'budget':     'float64',
            'prior_year': 'float64',
        }
    )

    # 3. Strip whitespace from string columns
    #    ERP exports often have trailing spaces — "Sales " != "Sales"
    for col in ['date', 'account', 'department']:
        if col in df.columns:
            df[col] = df[col].str.strip()

    # 4. Validate that all required columns are present
    actual_columns  = set(df.columns)
    missing_columns = REQUIRED_COLUMNS - actual_columns

    if missing_columns:
        raise ValueError(
            f"CSV is missing required columns: {sorted(missing_columns)}\n"
            f"Columns found in file: {sorted(actual_columns)}\n"
            f"Check that the CSV header row matches the expected format."
        )

    # 5. Check the file has at least one data row
    if len(df) == 0:
        raise ValueError(
            f"Data file is empty: {filepath}\n"
            f"The file was found but contains no data rows."
        )

    print(f"[OK] Loaded {len(df)} rows from {filepath.name}")
    print(f"     Columns: {list(df.columns)}")
    print(f"     Missing actuals: {df['actual'].isna().sum()} row(s)")
    print(f"     Missing budgets:  {df['budget'].isna().sum()} row(s)")

    return df


# =============================================================================
# STEP 2: Validate data and flag edge cases
# =============================================================================
def validate_and_flag(df):
    """
    Scan every row for edge cases and return a list of flags.

    Finance context: Before sending data to Claude, we need to know
    which rows have problems. We never drop or fix the data — we flag it.
    The flag travels forward to the prompt so Claude knows to handle
    those rows differently in the commentary.

    Four edge cases we check for:
    1. Missing actual  — blank cell in the actual column
    2. Missing budget  — blank cell in the budget column
    3. Zero budget     — division by zero would crash the next step
    4. Large variance  — >50% deviation needs stronger language

    Args:
        df: DataFrame returned by load_pnl()

    Returns:
        (df, flags) — same DataFrame unchanged + list of flag strings
    """
    flags = []

    for _, row in df.iterrows():
        dept   = row['department']
        actual = row['actual']
        budget = row['budget']

        # 1. Missing actual — blank cell came through as NaN
        if pd.isna(actual):
            flags.append(f"MISSING_ACTUAL: {dept}")
            continue  # skip remaining checks — no actual to work with

        # 2. Missing budget — rare but possible
        if pd.isna(budget):
            flags.append(f"MISSING_BUDGET: {dept}")
            continue  # skip remaining checks — no budget to work with

        # 3. Zero budget — cannot calculate variance %
        #    Different from missing: zero is a real value, not blank
        if budget == 0:
            flags.append(f"ZERO_BUDGET: {dept}")
            continue  # skip variance check — division by zero

        # 4. Zero actual — department spent nothing against a real budget
        #    Different from LARGE_VARIANCE — needs its own flag and language
        if actual == 0:
            flags.append(f"ZERO_ACTUAL: {dept} (budget was {budget:,.0f})")
            continue  # skip variance check — not a meaningful variance

        # 5. Large variance — deviation beyond threshold in either direction
        #    abs() catches both overspend and underspend
        variance_pct = (actual - budget) / budget
        if abs(variance_pct) > LARGE_VARIANCE_THRESHOLD:
            direction = "over budget" if variance_pct < 0 else "above budget"
            flags.append(
                f"LARGE_VARIANCE: {dept} "
                f"({variance_pct:+.1%} {direction})"
            )

    print(f"\n[OK] Validation complete")
    print(f"     Rows checked: {len(df)}")
    print(f"     Flags raised: {len(flags)}")
    if flags:
        for flag in flags:
            print(f"     --> {flag}")

    return df, flags

# =============================================================================
# STEP 3: Calculate variances — Python does ALL the arithmetic
# =============================================================================
def calculate_variances(df, flags):
    """
    Add variance columns to the DataFrame for every row.

    CRITICAL DESIGN RULE: Python calculates all numbers.
    Claude only interprets and narrates. The LLM never does arithmetic.

    Finance context: This mirrors what you do in Excel before writing
    commentary — you calculate the variance column first, then write
    the narrative. Here Python does the Excel work. Claude does the
    narrative work. They never swap roles.

    Three calculations per row:
    - variance_abs:      actual - budget              (absolute £/€ movement)
    - variance_pct:      (actual - budget) / budget   (percentage vs budget)
    - prior_year_pct:    (actual - prior_year) / prior_year  (YoY movement)

    Flagged rows (MISSING_ACTUAL, MISSING_BUDGET, ZERO_BUDGET, ZERO_ACTUAL)
    receive None for all variance columns — never a wrong number.

    Args:
        df:    DataFrame returned by validate_and_flag()
        flags: list of flag strings from validate_and_flag()

    Returns:
        DataFrame with three new columns added:
        variance_abs, variance_pct, prior_year_pct
    """

    # Work on a copy — never mutate the DataFrame passed in
    df = df.copy()

    # Build a set of flagged departments for fast lookup
    # e.g. {'Admin', 'Technology'} — used to skip bad rows below
    flagged_depts = set()
    for flag in flags:
        # Each flag is like "MISSING_ACTUAL: Admin" or "ZERO_BUDGET: Technology"
        # Split on ': ' and take the department name after the colon
        if ': ' in flag:
            dept_part = flag.split(': ')[1]
            # Strip trailing content like "(budget was 45,000)" if present
            dept_name = dept_part.split(' (')[0].strip()
            flagged_depts.add(dept_name)

    # Initialise all three variance columns with None
    # None means "not calculated" — distinct from zero which means "no variance"
    df['variance_abs']   = None
    df['variance_pct']   = None
    df['prior_year_pct'] = None

    # Calculate row by row
    # Using iterrows() for clarity — readable and explicit for a learning context
    for idx, row in df.iterrows():
        dept       = row['department']
        actual     = row['actual']
        budget     = row['budget']
        prior_year = row['prior_year']

        # Skip flagged rows — they have missing or invalid data
        # Their variance columns stay as None
        if dept in flagged_depts:
            continue

        # ── Absolute variance ─────────────────────────────────────────────────
        # Simple subtraction — always safe once we know actual and budget exist
        variance_abs = actual - budget
        df.at[idx, 'variance_abs'] = variance_abs

        # ── Percentage variance vs budget ─────────────────────────────────────
        # Budget guard: already flagged in Step 2, but double-check here
        # because defence-in-depth matters in a finance pipeline
        if pd.notna(budget) and budget != 0:
            df.at[idx, 'variance_pct'] = (actual - budget) / budget
        # else: stays None — no percentage calculated

        # ── Prior year variance ───────────────────────────────────────────────
        # Prior year can be zero or missing — check both
        # Step 2 does NOT check prior_year, so we must guard here
        if pd.notna(prior_year) and prior_year != 0:
            df.at[idx, 'prior_year_pct'] = (actual - prior_year) / prior_year
        # else: stays None — no prior year comparison available

    # ── Summary print ─────────────────────────────────────────────────────────
    calculated = df['variance_abs'].notna().sum()
    skipped    = df['variance_abs'].isna().sum()

    print(f"\n[OK] Variances calculated")
    print(f"     Rows calculated: {calculated}")
    print(f"     Rows skipped (flagged): {skipped}")
    print(f"\n     {'Department':<25} {'Actual':>12} {'Budget':>12} "
          f"{'Var £/€':>12} {'Var %':>8} {'vs PY':>8}")
    print(f"     {'-'*25} {'-'*12} {'-'*12} {'-'*12} {'-'*8} {'-'*8}")

    for _, row in df.iterrows():
        actual_str  = f"{row['actual']:>12,.0f}"  if pd.notna(row['actual'])       else f"{'MISSING':>12}"
        budget_str  = f"{row['budget']:>12,.0f}"  if pd.notna(row['budget'])       else f"{'MISSING':>12}"
        var_abs_str = f"{row['variance_abs']:>+12,.0f}" if pd.notna(row['variance_abs']) else f"{'N/A':>12}"
        var_pct_str = f"{row['variance_pct']:>+8.1%}"  if pd.notna(row['variance_pct']) else f"{'N/A':>8}"
        py_str      = f"{row['prior_year_pct']:>+8.1%}" if pd.notna(row['prior_year_pct']) else f"{'N/A':>8}"

        print(f"     {row['department']:<25} {actual_str} {budget_str} "
              f"{var_abs_str} {var_pct_str} {py_str}")

    return df

# =============================================================================
# STEP 4: Build the system prompt and user prompt
# =============================================================================
def build_prompt(df, flags, period, entity):
    """
    Build the system prompt and user prompt for the Claude API call.

    Finance context: This is where you hand the brief to Claude.
    The system prompt is the standing contract — written once, reused every run.
    The user prompt is the variable layer — changes with each period's data.

    Anthropic best practice: data goes inside XML tags, query goes at the end.
    This improves response quality by up to 30% vs unstructured prompts.

    Args:
        df:     DataFrame with variance columns from calculate_variances()
        flags:  list of flag strings from validate_and_flag()
        period: reporting period string e.g. 'March 2026'
        entity: entity name string e.g. 'Valencia Operations'

    Returns:
        (system_prompt string, user_prompt string)
    """

    # ── Guard: use defaults if period or entity are empty ─────────────────────
    if not period or not period.strip():
        period = DEFAULT_PERIOD
    if not entity or not entity.strip():
        entity = DEFAULT_ENTITY

    # =========================================================================
    # SYSTEM PROMPT — fixed contract, never changes between runs
    # Five mandatory sections: role, success criteria, constraints,
    # uncertainty handling, output format
    # =========================================================================
    system_prompt = """You are a senior FP&A analyst at a European company, \
preparing management accounts commentary for the CFO and Board.

<success_criteria>
- Identify the specific department and account driving each variance
- Use direction-aware language: favourable variances are framed as \
opportunities or achievements, unfavourable variances include a root cause \
and a recommended corrective action
- Commentary is concise, professional, and CFO-ready — no filler phrases, \
no corporate jargon
- Prior year comparisons are included where data is available
- The tone is analytical and confident, not hedged or vague
</success_criteria>

<constraints>
- NEVER invent, estimate, or extrapolate any number not present in the data
- NEVER round figures differently from how they are provided
- If a row is flagged, acknowledge the flag explicitly — do not write \
commentary as if the data is complete
- All amounts are in EUR unless stated otherwise
- Do not use phrases like "it is worth noting" or "it should be highlighted" \
— state the point directly
</constraints>

<uncertainty_handling>
- If a data field is missing or flagged, write: \
[FLAG: reason] — e.g. [FLAG: Missing actual for Legal & Compliance]
- Do not attempt to estimate or fill a missing value
- If a variance is very large (>50%), note that it requires urgent CFO review
</uncertainty_handling>

<output_format>
Produce output in exactly this structure — no deviation:

EXECUTIVE SUMMARY
[3 sentences maximum. Overall performance vs budget. \
Biggest positive driver. Biggest negative driver or risk.]

LINE ITEM COMMENTARY
[One paragraph per department. Format each paragraph as:]
[Department — Account]: [2-3 sentences. Variance amount and %. \
Root cause or explanation. Prior year comparison if available. \
Recommended action if unfavourable.]

DATA FLAGS
[List each flag on its own line. If no flags, write: No flags raised.]
</output_format>"""

    # =========================================================================
    # USER PROMPT — variable layer, rebuilt every run
    # Structure: context → data (XML tags) → flags → query
    # Anthropic docs: put data before the query for best results
    # =========================================================================

    # ── Build the formatted data rows for injection ───────────────────────────
    data_rows = []
    for _, row in df.iterrows():
        dept = row['department']
        acct = row['account']

        # Format actual — handle missing
        if pd.isna(row['actual']):
            actual_str = "MISSING"
        else:
            actual_str = f"€{row['actual']:,.0f}"

        # Format budget — always present (validated in Step 1)
        budget_str = f"€{row['budget']:,.0f}"

        # Format variance columns — None means flagged/skipped
        if pd.notna(row['variance_abs']) and pd.notna(row['variance_pct']):
            var_str = (
                f"€{row['variance_abs']:+,.0f} "
                f"({row['variance_pct']:+.1%})"
            )
        else:
            var_str = "N/A — see flags"

        # Format prior year comparison
        if pd.notna(row['prior_year_pct']):
            py_str = f"{row['prior_year_pct']:+.1%} vs prior year"
        else:
            py_str = "N/A"

        data_rows.append(
            f"  {dept} | {acct} | "
            f"Actual: {actual_str} | Budget: {budget_str} | "
            f"Variance: {var_str} | Prior Year: {py_str}"
        )

    data_block = "\n".join(data_rows)

    # ── Build the flags block ─────────────────────────────────────────────────
    if flags:
        flags_block = "\n".join(f"  - {flag}" for flag in flags)
    else:
        flags_block = "  No flags raised."

    # ── Assemble the full user prompt ─────────────────────────────────────────
    user_prompt = f"""REPORTING CONTEXT
Period:  {period}
Entity:  {entity}
Currency: EUR

<financial_data>
{data_block}
</financial_data>

<data_flags>
{flags_block}
</data_flags>

Using the financial data and flags above, produce the variance commentary \
in the exact output format specified."""

    # ── Preview print — lets you read both prompts before the API call ────────
    print("\n[OK] Prompts built")
    print(f"     Period: {period} | Entity: {entity}")
    print(f"     Data rows injected: {len(data_rows)}")
    print(f"     Flags in prompt: {len(flags)}")
    print(f"\n     --- USER PROMPT PREVIEW ---")
    print(user_prompt)
    print(f"     --- END PREVIEW ---")

    return system_prompt, user_prompt

# =============================================================================
# STEP 5: Call the Claude API
# =============================================================================
def call_claude(system_prompt, user_prompt):
    """
    Send the system and user prompts to Claude and return the response.

    Finance context: This is the equivalent of handing the formatted brief
    to an analyst and receiving the commentary back. We capture everything
    needed for the audit log: tokens, stop reason, and request ID.

    Error handling:
    - AuthenticationError: API key is wrong or missing — fix .env
    - RateLimitError: too many requests — wait and retry manually
    - APIStatusError 5xx: Anthropic server error — SDK retries 2x automatically
    - max_tokens stop_reason: response was truncated — flag it, do not use

    Args:
        system_prompt: the fixed contract prompt from build_prompt()
        user_prompt:   the variable data prompt from build_prompt()

    Returns:
        (response_text, input_tokens, output_tokens, stop_reason)

    Raises:
        RuntimeError with a clear human-readable message on any API failure
    """
    print(f"\n[..] Calling Claude API ({MODEL})...")

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_prompt}
            ]
        )

    except anthropic.AuthenticationError:
        # Wrong or missing API key — most common setup error
        raise RuntimeError(
            "Authentication failed. Check that your ANTHROPIC_API_KEY "
            "is set correctly in your .env file and starts with 'sk-ant-'."
        )

    except anthropic.RateLimitError:
        # Too many requests — wait before retrying manually
        raise RuntimeError(
            "Rate limit reached. Wait 60 seconds then run the script again. "
            "If this happens repeatedly, check your Anthropic usage dashboard."
        )

    except anthropic.APIStatusError as e:
        # Server-side error — SDK already retried 2x automatically
        raise RuntimeError(
            f"Anthropic API error after retries: {e.status_code} — {e.message}\n"
            f"Request ID: {e.request_id}\n"
            f"If this persists, report the Request ID to Anthropic support."
        )

    except anthropic.APIConnectionError:
        # Network issue — no internet connection or DNS failure
        raise RuntimeError(
            "Could not connect to Anthropic API. "
            "Check your internet connection and try again."
        )

    # ── Extract the response text ─────────────────────────────────────────────
    # response.content is a list — guard against empty list before accessing [0]
    if not response.content:
        raise RuntimeError(
            "Claude returned an empty response — no content in the message. "
            "This is unexpected. Check your prompt and try again."
        )

    response_text = response.content[0].text
    input_tokens  = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    stop_reason   = response.stop_reason

    # ── Check stop reason — warn if response was truncated ───────────────────
    # stop_reason == 'end_turn'   → Claude finished naturally — good
    # stop_reason == 'max_tokens' → Claude was cut off — commentary is incomplete
    if stop_reason == "max_tokens":
        print(
            f"\n[WARN] Response was truncated — Claude hit the max_tokens limit "
            f"({MAX_TOKENS} tokens).\n"
            f"       The commentary may be incomplete. "
            f"Consider increasing MAX_TOKENS in config.py."
        )

    # ── Summary print ─────────────────────────────────────────────────────────
    approx_cost = (input_tokens * 0.000003) + (output_tokens * 0.000015)

    print(f"[OK] Claude responded")
    print(f"     Stop reason:   {stop_reason}")
    print(f"     Input tokens:  {input_tokens:,}")
    print(f"     Output tokens: {output_tokens:,}")
    print(f"     Approx cost:   €{approx_cost:.4f}")
    print(f"\n{'='*60}")
    print(f"VARIANCE COMMENTARY — {DEFAULT_PERIOD}")
    print(f"{'='*60}")
    print(response_text)
    print(f"{'='*60}")

    return response_text, input_tokens, output_tokens, stop_reason

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
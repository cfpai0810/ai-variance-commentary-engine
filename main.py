# =============================================================================
# main.py — Project 1: AI Variance Commentary Engine
# Pass 1: flat script, console output, understand every line
# =============================================================================

import pandas as pd
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from config import (
    DATA_DIR,
    SAMPLE_DATA,
    DEFAULT_PERIOD,
    DEFAULT_ENTITY,
    LARGE_VARIANCE_THRESHOLD,
)

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
# MAIN — grows one step at a time
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
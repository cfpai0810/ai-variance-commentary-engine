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
# MAIN — grows one step at a time
# =============================================================================
if __name__ == '__main__':

    # Step 1: Load
    df = load_pnl(SAMPLE_DATA)

    # Step 2: Validate
    df, flags = validate_and_flag(df)
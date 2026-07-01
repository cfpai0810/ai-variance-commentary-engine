# main.py — Project 1: AI Variance Commentary Engine
# Pass 1: flat script, console output, understand every line

import pandas as pd
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Constants ──────────────────────────────────────────────────────────────────
from config import DATA_DIR, SAMPLE_DATA

REQUIRED_COLUMNS = {'date', 'account', 'department', 'actual', 'budget', 'prior_year'}


# ── STEP 1: Load the P&L data ──────────────────────────────────────────────────
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
        ValueError: if required columns are missing
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
    #    Do this AFTER loading so we can give a specific error message
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


# ── MAIN (temporary test block) ────────────────────────────────────────────────
if __name__ == '__main__':
    df = load_pnl(SAMPLE_DATA)
    print("\nFirst 3 rows:")
    print(df.head(3).to_string())
    print(f"\nData types:\n{df.dtypes}")
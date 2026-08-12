import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Optional at import time. The CLI builds its client from this key when present;
# the web supplies a per-session key via the key gate. Import must NOT fail when
# no key is set, so a keyless / bring-your-own-key web deployment can load the
# pipeline and still show the keyless example.
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')

MODEL      = 'claude-sonnet-4-6'
MAX_TOKENS = 2048

# Cost-estimate rates. These are an ESTIMATE input, not a bill; Anthropic's
# metering is authoritative.
#
# Model: claude-sonnet-4-6
# Rate:  $3.00 per million input tokens, $15.00 per million output tokens.
# Verified: August 2026. Re-verify at https://www.anthropic.com/pricing
# IMPORTANT: this rate is tied to the model above. If MODEL changes (for example
# to a newer Sonnet), update these rates to match, or the estimate will be wrong.
COST_INPUT_USD_PER_MTOK  = 3.00
COST_OUTPUT_USD_PER_MTOK = 15.00

# Assumed EUR/USD for display. The API bills in USD; this is a fixed assumption
# for the euro figure, clearly labelled as such wherever shown. Re-verify or
# adjust as needed; it is deliberately not fetched live.
ASSUMED_USD_PER_EUR = 1.08

BASE_DIR    = Path(__file__).parent
DATA_DIR    = BASE_DIR / 'data'
OUTPUT_DIR  = BASE_DIR / 'output'

SAMPLE_DATA = DATA_DIR / 'sample_pnl.csv'
AUDIT_LOG   = OUTPUT_DIR / 'audit_log.jsonl'

DEFAULT_PERIOD = 'March 2026'
DEFAULT_ENTITY = 'Valencia Operations'

# Currency of the P&L figures. The arithmetic is currency-agnostic; these two
# values only label and describe the figures (in the prompt, the table, the trend
# chart, and the report). Ships as euros; set both to match your own data (for
# example 'USD' and '$'). Note: this is the DATA currency, separate from the
# Anthropic API cost estimate, which is billed in USD and shown in EUR.
CURRENCY_CODE   = 'EUR'
CURRENCY_SYMBOL = '€'

# Global default: applied to any account without a specific override.
LARGE_VARIANCE_THRESHOLD = 0.50

# Per-account overrides (fractions, not percentages). Keyed by the ACCOUNT
# label (the P&L line), matching the 'account' column in the data. Material
# lines flag early; volatile lines flag late. The core never sees a percentage.
VARIANCE_THRESHOLDS = {
    "Revenue": 0.10,             # a 10% revenue swing is material
    "COGS": 0.15,
    "Marketing Spend": 0.30,
    "Headcount Cost": 0.15,
    "IT Infrastructure": 0.40,
    "Legal & Compliance": 0.50,
    "R&D Expense": 1.00,         # volatile; only flag past a 100% swing
}
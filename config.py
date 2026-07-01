import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
if not ANTHROPIC_API_KEY:
    raise ValueError(
        "ANTHROPIC_API_KEY not found. "
        "Check that .env exists in the project root."
    )

MODEL      = 'claude-sonnet-4-6'
MAX_TOKENS = 2048

BASE_DIR    = Path(__file__).parent
DATA_DIR    = BASE_DIR / 'data'
OUTPUT_DIR  = BASE_DIR / 'output'

SAMPLE_DATA = DATA_DIR / 'sample_pnl.csv'
AUDIT_LOG   = OUTPUT_DIR / 'audit_log.jsonl'

DEFAULT_PERIOD = 'March 2026'
DEFAULT_ENTITY = 'Valencia Operations'

LARGE_VARIANCE_THRESHOLD = 0.50
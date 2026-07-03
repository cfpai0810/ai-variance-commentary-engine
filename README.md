# AI Variance Commentary Engine

**AI-powered FP&A variance commentary — from raw P&L data to CFO-ready
narrative in under 15 seconds.**

Built as Project 1 of a 9-project AI Finance portfolio demonstrating
Finance Engineer capabilities for Head of FP&A and Finance Transformation roles.

---

## What it does

Takes a standard P&L CSV export (actuals vs budget vs prior year), validates
every row for data quality issues, calculates all variances in Python, and uses
the Claude API to generate structured CFO-grade management accounts commentary.

**Time saved:** Monthly close narrative from 4-6 hours to under 15 seconds.
**Cost per run:** Approximately €0.02.
**Audit trail:** SHA256 hash of input data logged on every run.

---

## How to run

```bash
# 1. Clone the repository
git clone https://github.com/cfpai0810/ai-variance-commentary-engine.git
cd ai-variance-commentary-engine

# 2. Create and activate virtual environment
python -m venv venv
venv\Scripts\activate        # Windows PowerShell
source venv/bin/activate     # Mac/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Add your Anthropic API key
cp .env.example .env
# Edit .env: ANTHROPIC_API_KEY=sk-ant-your-key-here

# 5. Run the pipeline
python main.py
```

---

## Sample output

See [`docs/sample_output.txt`](docs/sample_output.txt) for a full example.
See [`docs/audit_log_sample.jsonl`](docs/audit_log_sample.jsonl) for the audit trail.

---

## Project structure

Follow the steps — each file does exactly one job:

```
main.py                    Orchestrator — runs the full pipeline
config.py                  Layer 1: all configuration and paths
step1_data_loader.py       Layer 2: load CSV, validate, calculate variances
step2_ai_engine.py         Layer 3: build prompts, call Claude API
step3_output_writer.py     Layer 4: write output file and audit log

data/sample_pnl.csv        Synthetic test data with all edge cases
docs/sample_output.txt     Example commentary output
docs/audit_log_sample.jsonl  Example audit log record
output/                    Generated files (gitignored)
tests/                     Test suite (Phase 5)
```

---

## Architecture

**Critical design rule: Python calculates all numbers. Claude only narrates.**

This means every figure in the output can be traced back to a specific
Python calculation — making the output auditable and CFO-ready.

```
P&L CSV
   ↓
step1_data_loader.py   Load + validate + calculate variances (Python)
   ↓
step2_ai_engine.py     Build structured prompt + call Claude API
   ↓
step3_output_writer.py Write commentary file + append audit log
   ↓
output/variance_commentary_YYYY-MM-DD.txt  + audit_log.jsonl
```

**Edge cases handled automatically:**

| Flag | Condition | Behaviour |
|------|-----------|-----------|
| MISSING_ACTUAL | Blank actual cell | Flagged, skipped, never invented |
| MISSING_BUDGET | Blank budget cell | Flagged, skipped |
| ZERO_BUDGET | Budget = 0 | Flagged, % variance shows N/A |
| ZERO_ACTUAL | Actual = 0 | Flagged separately from large variance |
| LARGE_VARIANCE | Deviation > 50% | Flagged, urgent CFO review language |

---

## Audit trail

Every run appends one record to `output/audit_log.jsonl`:

```json
{
  "run_id": "2026-07-03T06:39:45+00:00",
  "input_hash": "sha256:c3a41176...",
  "model": "claude-sonnet-4-6",
  "input_tokens": 895,
  "output_tokens": 1114,
  "flags_raised": ["MISSING_ACTUAL: Admin"],
  "human_reviewed": false,
  "requires_review": true
}
```

Human review is triggered automatically when flags are raised or output
is truncated.

---

## Tech stack

Python · pandas · Claude API (claude-sonnet-4-6) · python-dotenv · hashlib

---

## CV bullet

*Built AI-powered variance commentary engine using Claude API and Python,
reducing FP&A monthly close narrative time by ~80% while adding full audit
trail and automated data quality flagging.*

---

## Part of the AI Finance Portfolio

| # | Project | Status |
|---|---------|--------|
| 1 | AI Variance Commentary Engine | Complete |
| 2 | Driver-Based Rolling Forecast Pipeline | Building |
| 3 | Anomaly Detection and Alert Agent | Planned |
| 4 | NL Scenario Modelling Copilot | Planned |
| 5 | Budget Challenge Assistant | Planned |
| 6 | Agentic Board Pack Generator | Planned |
| 7 | Anaplan to Snowflake to LLM Pipeline | Planned |
| 8 | Cuenta y Cocina Live AI Finance | Planned |
| 9 | AI Governance Playbook | Planned |
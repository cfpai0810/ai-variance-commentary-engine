# AI Variance Commentary Engine

**AI-powered FP&A variance commentary — from raw P&L data to CFO-ready narrative in under 15 seconds.**

Built as Project 1 of a 9-project AI Finance portfolio demonstrating Finance Engineer capabilities
for Head of FP&A and Finance Transformation roles.

---

## What it does

Takes a standard P&L CSV export (actuals vs budget vs prior year), validates every row for
data quality issues, calculates all variances in Python, and uses the Claude API to generate
structured CFO-grade management accounts commentary — executive summary, line-item narrative,
and a data flags section for rows requiring human review.

**Time saved:** Monthly close narrative from 4-6 hours to under 15 seconds.
**Cost per run:** Approximately EUR 0.02.
**Audit trail:** SHA256 hash of input data logged on every run.

---

## Sample output

See [docs/sample_output.txt](docs/sample_output.txt) for a full example of generated commentary.

See [docs/audit_log_sample.jsonl](docs/audit_log_sample.jsonl) for an example audit log record.

---

## How to run

Clone the repository and install dependencies:

```bash
git clone https://github.com/cfpai0810/ai-variance-commentary-engine.git
cd ai-variance-commentary-engine
```

Create and activate a virtual environment:

```bash
python -m venv venv
```

```bash
# Windows PowerShell
venv\Scripts\activate

# Mac / Linux
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Add your Anthropic API key:

```bash
cp .env.example .env
```

Open `.env` and add your key:

```
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

Run the pipeline:

```bash
python main.py
```

---

## Project structure

```
main.py                       Run this to execute the full pipeline
config.py                     Layer 1: all configuration and file paths
requirements.txt              All dependencies with pinned versions

src/
  step1_data_loader.py        Layer 2: load CSV, validate rows, calculate variances
  step2_ai_engine.py          Layer 3: build prompts, call Claude API
  step3_output_writer.py      Layer 4: write output file and append audit log

data/
  sample_pnl.csv              Synthetic test data covering all edge cases

docs/
  sample_output.txt           Example commentary output
  audit_log_sample.jsonl      Example audit log record

output/                       Generated files (gitignored)
tests/                        Test suite added in Phase 5
```

---

## Architecture

Critical design rule: Python calculates all numbers. Claude only interprets and narrates.
This means every figure in the output can be traced back to a specific Python calculation,
making the output auditable and CFO-ready.

```
P&L CSV input
      |
      v
step1_data_loader.py    Load CSV + validate schema + calculate variances (Python only)
      |
      v
step2_ai_engine.py      Build structured prompt + call Claude API
      |
      v
step3_output_writer.py  Write commentary file + append one record to audit log
      |
      v
output/variance_commentary_YYYY-MM-DD.txt
output/audit_log.jsonl
```

Edge cases handled automatically:

| Flag | Condition | System behaviour |
|------|-----------|-----------------|
| MISSING_ACTUAL | Blank actual cell | Flagged, skipped, never invented |
| MISSING_BUDGET | Blank budget cell | Flagged, skipped |
| ZERO_BUDGET | Budget = 0 | Flagged, percentage variance shows N/A |
| ZERO_ACTUAL | Actual = 0 | Flagged separately, prevents false large-variance alert |
| LARGE_VARIANCE | Deviation > 50% | Flagged, urgent CFO review language triggered |

---

## Input data format

Standard P&L CSV with these columns:

```
date, account, department, actual, budget, prior_year
```

See `data/sample_pnl.csv` for a working example including all edge case rows.

---

## Audit trail

Every run appends one record to `output/audit_log.jsonl`:

```json
{
  "run_id": "2026-07-03T06:39:45+00:00",
  "project": "variance-commentary-engine",
  "period": "March 2026",
  "entity": "Valencia Operations",
  "input_file": "data/sample_pnl.csv",
  "input_hash": "sha256:c3a41176d88fdd785d7f891b5c2a3e4f",
  "output_file": "output/variance_commentary_2026-07-03_06-39-45.txt",
  "model": "claude-sonnet-4-6",
  "input_tokens": 895,
  "output_tokens": 1114,
  "stop_reason": "end_turn",
  "flags_raised": ["MISSING_ACTUAL: Admin", "ZERO_ACTUAL: Technology"],
  "human_reviewed": false,
  "requires_review": true
}
```

The `input_hash` field proves which exact data version produced which output.
Human review is triggered automatically when flags are raised or output is truncated.

---

## Tech stack

Python 3.11 | pandas | Claude API claude-sonnet-4-6 | python-dotenv | hashlib | reportlab

---

## CV bullet

Built AI-powered variance commentary engine using Claude API and Python, reducing FP&A
monthly close narrative time by 80% while adding full audit trail and automated data
quality flagging.

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
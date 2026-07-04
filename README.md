# AI Variance Commentary Engine

**AI-powered FP&A variance commentary — from raw P&L data to CFO-ready PDF report in under 15 seconds.**

Built as Project 1 of a 9-project AI Finance portfolio demonstrating Finance Engineer capabilities for Head of FP&A and Finance Transformation roles.

---

## What it does

Takes a standard P&L CSV export (actuals vs budget vs prior year), validates every row for data quality issues, calculates all variances in Python, and uses the Claude API to generate structured CFO-grade management accounts commentary. The output is both a plain-text file and a formatted A4 PDF report with an executive summary, numbers-first variance table, line-item narrative, and a data flags action table.

**Time saved:** Monthly close narrative from 4–6 hours to under 15 seconds.
**Cost per run:** Approximately EUR 0.02.
**Audit trail:** SHA256 hash of input data, row count, and both output paths logged on every run.

---

## Sample output

See [`docs/sample_output.txt`](docs/sample_output.txt) for a full example of the generated text commentary.

The pipeline also produces a formatted A4 PDF report with five sections: cover header, executive summary, variance summary table with FAV/UNF status indicators, line-item commentary with inline flag boxes, and a data flags action table.

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
venv\Scripts\Activate.ps1

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

The pipeline produces two output files in `output/`:
- `variance_commentary_YYYY-MM-DD_HH-MM-SS.txt` — plain-text commentary with run metadata header
- `variance_commentary_YYYY-MM-DD_HH-MM-SS.pdf` — formatted A4 PDF report

---

## Project structure

```
main.py                       Run this to execute the full pipeline
config.py                     Layer 1: all configuration and file paths
requirements.txt              All dependencies with pinned versions

src/
  step1_data_loader.py        Layer 2: load CSV, validate rows, calculate variances
  step2_ai_engine.py          Layer 3: build prompts, call Claude API
  step3_output_writer.py      Layer 4: write text file, PDF report, and audit log

data/
  sample_pnl.csv              Synthetic test data covering all edge cases

docs/
  sample_output.txt           Example text commentary output

output/                       Generated files (gitignored)
tests/
  test_pipeline.py            55 assertions across 6 test cases — no API calls needed
```

---

## Architecture

Critical design rule: Python calculates all numbers. Claude only interprets and narrates. Every figure in the output can be traced back to a specific Python calculation — making the output auditable and CFO-ready.

```
P&L CSV input
      |
      v
step1_data_loader.py    Load CSV + validate schema + calculate variances (Python)
      |
      v
step2_ai_engine.py      Build structured prompt + call Claude API
      |
      v
step3_output_writer.py  Write text file + formatted PDF + append audit log
      |
      v
output/variance_commentary_YYYY-MM-DD.txt   (plain text)
output/variance_commentary_YYYY-MM-DD.pdf   (formatted A4 PDF)
output/audit_log.jsonl                      (append-only audit trail)
```

Edge cases handled automatically before any data reaches Claude:

| Flag | Condition | Behaviour |
|------|-----------|-----------|
| MISSING_ACTUAL | Blank actual cell | Flagged, skipped, never invented |
| MISSING_BUDGET | Blank budget cell | Flagged, skipped |
| ZERO_BUDGET | Budget = 0 | Flagged, percentage variance shows — |
| ZERO_ACTUAL | Actual = 0 | Flagged separately, prevents false large-variance alert |
| LARGE_VARIANCE | Deviation > 50% | Flagged, urgent CFO review language triggered |

PDF status indicators are revenue-aware:
- Revenue line, actual > budget → green dot (FAV)
- Cost line, actual > budget → red dot (UNF — overspend)
- Cost line, actual < budget → green dot (FAV — underspend)
- Any flagged row → amber triangle ([!])

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
  "run_id":          "2026-07-04T07:49:09+00:00",
  "project":         "variance-commentary-engine",
  "period":          "March 2026",
  "entity":          "Valencia Operations",
  "input_file":      "data/sample_pnl.csv",
  "input_rows":      7,
  "input_hash":      "sha256:c3a41176d88fdd785d7f891b5c2a3e4f",
  "output_file":     "output/variance_commentary_2026-07-04_07-49-09.txt",
  "pdf_file":        "output/variance_commentary_2026-07-04_07-49-09.pdf",
  "model":           "claude-sonnet-4-6",
  "input_tokens":    895,
  "output_tokens":   1128,
  "stop_reason":     "end_turn",
  "flags_raised":    ["MISSING_ACTUAL: Admin", "ZERO_ACTUAL: Technology"],
  "human_reviewed":  false,
  "requires_review": true
}
```

Human review is triggered automatically when flags are raised, output is truncated, or output token count is suspiciously low. The `input_hash` field proves which exact data version produced which output.

---

## Test suite

55 assertions across 6 test cases. No real API calls — runs in under 2 seconds:

```bash
pytest tests/test_pipeline.py -v
```

Test cases follow the methodology protocol:
- Happy path — clean data, full pipeline, audit log correct
- Favourable variance — green dot for revenue over, cost under
- Unfavourable variance — red dot for cost over, revenue under
- Missing value — NaN detected, flagged, skipped, never invented
- Zero actual — ZERO_ACTUAL raised, not LARGE_VARIANCE
- Large variance — threshold detection, flag text, audit record

---

## Tech stack

Python 3.11 · pandas · Claude API claude-sonnet-4-6 · python-dotenv · reportlab · hashlib · pytest

---

## CV bullet

Built AI-powered FP&A variance commentary engine in Python using Claude API, generating structured PDF management accounts reports from raw P&L data in under 15 seconds, with automated data quality flagging, revenue-aware status indicators, and full SHA256 audit trail.

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
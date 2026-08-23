# AI Variance Commentary Engine

A practical demonstration of how AI can be leveraged to transform
traditional finance workflows - taking a task that typically takes
4-6 hours and completing it in under 15 seconds, with higher
consistency and a built-in audit trail.

**Live demo:** [ai-variance-commentary-engine.streamlit.app](https://ai-variance-commentary-engine.streamlit.app)

---

## What it does

Takes a standard P&L CSV export (actuals vs budget vs prior year),
validates every row for data quality issues, calculates all variances
in Python, and uses the Claude API to generate structured management
accounts commentary. The output is both a plain-text file and a
formatted A4 PDF report with five sections: executive summary,
variance summary table, line-item narrative, data flag boxes, and
a consolidated action table.

**Time per run:** Under 15 seconds.
**API cost per run:** Approximately EUR 0.02.
**Audit trail:** Every run logs input hash, row count, token usage,
and both output paths to a permanent JSONL audit file.

---

## Sample output

See [`docs/sample_output.txt`](docs/sample_output.txt) for a full
example of the generated text commentary.

See [`docs/sample_report.pdf`](docs/sample_report.pdf) for a full
example of the generated PDF report.

The PDF report contains five sections:

- Cover block with entity, period, model, and run metadata
- Executive summary - 3-sentence narrative of overall performance
- Variance summary table - all line items with actuals, budgets,
  variances, and colour-coded status at a glance
- Line item commentary - one paragraph per department with root
  cause analysis and recommended action
- Data flags action table - each flagged row with a specific
  action required before the accounts can be signed off

---

## How to run

Clone and install:

```bash
git clone https://github.com/cfpai0810/ai-variance-commentary-engine.git
cd ai-variance-commentary-engine
python -m venv venv
venv\Scripts\Activate.ps1        # Windows PowerShell
pip install -r requirements.txt
```

Add your Anthropic API key to a `.env` file:

```
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

Run:

```bash
python main.py
```

The pipeline produces two files in `output/`:

- `variance_commentary_YYYY-MM-DD_HH-MM-SS.txt` - plain-text commentary with run metadata header
- `variance_commentary_YYYY-MM-DD_HH-MM-SS.pdf` - formatted A4 PDF report

---

## Project structure

```
main.py                       Orchestrator - runs the full pipeline
config.py                     All configuration and file paths
requirements.txt              Pinned dependencies

src/
  step1_data_loader.py        Load CSV, validate rows, calculate variances
  step2_ai_engine.py          Build prompts, call Claude API
  step3_output_writer.py      Write text file, PDF report, and audit log

data/
  sample_pnl.csv              Synthetic test data with all edge cases

docs/
  sample_output.txt           Example text commentary output
  sample_report.pdf           Example PDF report output

output/                       Generated files (gitignored)
tests/
  test_pipeline.py            55 assertions, 6 test cases, no API calls
```

---

## Architecture

**Core design rule:** Python calculates all numbers. Claude only
interprets and narrates. This makes every figure in the output
traceable to a specific calculation - not to the language model.

```
P&L CSV input
      |
      v
step1_data_loader.py
  Load CSV with explicit dtypes
  Validate schema and row count
  Flag edge cases before calculation
  Calculate variances in Python
      |
      v
step2_ai_engine.py
  Build structured system prompt + data prompt
  Call Claude API with XML-tagged financial data
  Capture token counts and stop reason
      |
      v
step3_output_writer.py
  Write plain-text commentary with header
  Write formatted A4 PDF report
  Append one record to audit_log.jsonl
      |
      v
output/variance_commentary_YYYY-MM-DD.txt
output/variance_commentary_YYYY-MM-DD.pdf
output/audit_log.jsonl
```

**Edge case handling - before any data reaches Claude:**

| Flag | Condition | What the system does |
|------|-----------|----------------------|
| MISSING_ACTUAL | Blank actual cell | Flags the row, skips calculation, never invents a value |
| MISSING_BUDGET | Blank budget cell | Flags the row, skips calculation |
| ZERO_BUDGET | Budget = 0 | Flags the row, skips percentage calculation |
| ZERO_ACTUAL | Actual = 0 | Flagged separately - prevents a false large-variance alert |
| LARGE_VARIANCE | Deviation beyond that line's threshold (per-account policy, default 50%) | Flagged with the threshold named in the flag; routed to CFO review |

**PDF status column:**

The status column in the variance summary table uses coloured symbols
to show direction at a glance:

| Situation | Symbol | Meaning |
|-----------|--------|---------|
| Revenue line, actual above budget | Green dot | More revenue than planned |
| Revenue line, actual below budget | Red dot | Revenue shortfall |
| Cost line, actual above budget | Red dot | Overspend against plan |
| Cost line, actual below budget | Green dot | Underspend - saving |
| Any flagged row | Amber triangle | Data quality issue - see flags section |

---

## Input format

The tool reads a single P&L CSV with exactly these six columns (read by name, so
column order does not matter):

| Column | Meaning | Notes |
| --- | --- | --- |
| `date` | The month the row belongs to | ISO `YYYY-MM-DD` (for example `2026-03-31`); rows are grouped into periods by year and month. |
| `account` | The P&L line | For example `Revenue`, `COGS`, `R&D Expense`. |
| `department` | The label shown for the line | For example `Sales`, `Operations`, `Product`. |
| `actual` | The actual figure | A number; blank (missing) or `0` (zero posting) is flagged for review. |
| `budget` | The budget figure | A number; blank or zero is flagged. |
| `prior_year` | The prior-year figure | A number, for the year-on-year comparison. |

See `data/sample_pnl.csv` for a working example with all five edge-case rows.

---

## Running on your own data

The steps above run on the synthetic sample. To run on your own figures:

- **Swap in your file.** Replace `data/sample_pnl.csv` with your own CSV (same six
  columns), or point `SAMPLE_DATA` in `config.py` at a file elsewhere.
- **Run the web app locally** (the most forgiving route, since the period picker
  adapts to whatever months your data contains):
  ```bash
  pip install -r requirements.txt
  streamlit run streamlit_app/Home.py
  ```
  Open the Variance Commentary page, pick a period, and generate. Paste your
  Anthropic key in the sidebar, or set `ANTHROPIC_API_KEY`.
- **Or run the CLI** with `python main.py`; it uses `DEFAULT_PERIOD` from
  `config.py`. If your data does not contain that month, change it, or the run
  stops with an error listing the periods your file has.

A few constraints:

- The six column names must match exactly; a missing or renamed column stops the
  load. Dates must be `YYYY-MM-DD`. `actual`, `budget`, and `prior_year` must be
  numeric (`actual` and `budget` may be blank for a missing figure); text in these
  columns stops the load.
- **Per-line thresholds are matched by account name.** The defaults fit the
  sample's line names; if yours differ they fall back to the single default. Edit
  `VARIANCE_THRESHOLDS` in `config.py` for your lines, or set them in the web app's
  Flagging thresholds panel for a run.
- **Currency is configurable and ships as euros.** The maths is currency-agnostic,
  but the commentary, the table, the trend chart, and the report label figures in
  the currency set in `config.py` (`CURRENCY_CODE` and `CURRENCY_SYMBOL`). Set them
  (for example `USD` and `$`) to match your data; the model is told the currency,
  so it describes the figures correctly.

**What leaves your machine.** The figures, the variances, and the flags are all
computed locally. Only the selected period's figures are sent to the Anthropic
API, in your own account under your own key, so the model can describe them;
nothing goes to this project's authors, and your key is not stored. The commentary
is the only step that uses the API; everything else is local and needs no key.

---

## Human review

The pipeline sets a `requires_review` flag in the audit log and prints
a warning block in the terminal whenever any of the following occur:

- **One or more data flags were raised** - the commentary is based on
  incomplete data and must be checked before presenting to the Board
- **API response was truncated** (`stop_reason = max_tokens`) - the
  commentary may be cut off mid-sentence
- **Output token count unusually low** (under 200 tokens) - the model
  may have produced an incomplete response

When `requires_review` is `true`, the reviewer should:

1. Open the PDF report and read the **DATA FLAGS** section
2. Resolve each flagged item with the relevant department
3. Re-run the pipeline with corrected data
4. Set `human_reviewed` to `true` in the audit log record before filing

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
  "output_file":     "output/variance_commentary_2026-07-04.txt",
  "pdf_file":        "output/variance_commentary_2026-07-04.pdf",
  "model":           "claude-sonnet-4-6",
  "input_tokens":    895,
  "output_tokens":   1128,
  "stop_reason":     "end_turn",
  "flags_raised":    [
    "LARGE_VARIANCE: Sales (+13.6% above budget, threshold 10%)",
    "ZERO_ACTUAL: Technology (budget was 45,000)",
    "MISSING_ACTUAL: Admin",
    "LARGE_VARIANCE: Product (+122.5% above budget, threshold 100%)"
  ],
  "thresholds": {
    "Revenue": 0.10, "COGS": 0.15, "Marketing Spend": 0.30,
    "Headcount Cost": 0.15, "IT Infrastructure": 0.40,
    "Legal & Compliance": 0.50, "R&D Expense": 1.00, "_default": 0.50
  },
  "human_reviewed":  false,
  "requires_review": true
}
```

The `input_hash` field (SHA256 of the scoped input rows for the period)
proves which exact data produced which output. The same rows always
produce the same hash, making the audit trail tamper-evident.

---

## Test suite

55 assertions across 6 test cases. No real API calls. Runs in under 2 seconds:

```bash
pytest tests/test_pipeline.py -v
```

The 6 test cases follow the standard validation protocol:
happy path, favourable result, unfavourable result,
missing value, zero actual, and large variance.

---

## Tech stack

Python 3.11 · pandas · Anthropic Claude API · python-dotenv ·
reportlab · hashlib · pytest

---

## Related projects

| # | Project | Status |
|---|---------|--------|
| 1 | AI Variance Commentary Engine | This project |
| 2 | Driver-Based Rolling Forecast Pipeline | Complete |
| 3 | Anomaly Detection and Alert Agent | Complete |
| 4 | NL Scenario Modelling Copilot | Complete |
| 5 | Reconciliation and Tie-Out Assistant | Planned |
| 6 | Agentic Board Pack Generator | Planned |
| 7 | Planning-to-Warehouse-to-LLM Pipeline | Planned |
| 8 | 13-Week Cash Flow Forecasting Agent | Planned |
| 9 | Multi-Entity Consolidation and FX Engine | Planned |
| 10 | AI Governance Playbook | Planned |
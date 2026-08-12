# =============================================================================
# pages/your_own_data.py: running the tool on your own figures (download + local)
# =============================================================================
# The public app runs on synthetic sample data only. This page tells a visitor
# how to download the project and run it locally on their own CSV: the data
# format, where the file goes, how to run it, the constraints, and what stays
# private. Docs page, no key gate.
# =============================================================================

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from streamlit_app.lib.theme import inject_css

st.markdown(inject_css(), unsafe_allow_html=True)

st.markdown("### Running on your own data")
st.write(
    "The public web app runs on synthetic sample data only. To generate "
    "commentary on your own figures, download this project and run it locally "
    "with your own Anthropic API key. This page explains the data format, where "
    "your file goes, how to run it, and the constraints to be aware of.")

# ── The data format ──────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("#### The data format")
st.write(
    "The tool reads a single CSV of profit-and-loss data. It must have exactly "
    "these six columns, with these names:")
st.markdown(
    "| Column | Meaning | Notes |\n"
    "| --- | --- | --- |\n"
    "| `date` | The month the row belongs to | A month-end date in ISO form, "
    "`YYYY-MM-DD` (for example `2026-03-31`). Rows are grouped into periods by "
    "year and month. |\n"
    "| `account` | The profit-and-loss line | For example `Revenue`, `COGS`, "
    "`R&D Expense`. See per-line thresholds below. |\n"
    "| `department` | The label shown for the line | For example `Sales`, "
    "`Operations`, `Product`. |\n"
    "| `actual` | The actual figure | A number. May be blank (a missing actual) "
    "or `0` (a zero posting); both are flagged for review. |\n"
    "| `budget` | The budget figure | A number. A blank or zero budget is "
    "flagged. |\n"
    "| `prior_year` | The prior-year figure | A number, used for the "
    "year-on-year comparison. |")
st.write(
    "Your file can contain as many months as you like. Each period is all the "
    "rows that share a year and month, and the period picker lists whatever "
    "months your data contains. A few rows of a valid file:")
st.code(
    "date,account,department,actual,budget,prior_year\n"
    "2026-01-31,Revenue,Sales,1160000,1100000,1030000\n"
    "2026-01-31,COGS,Operations,448000,440000,418000\n"
    "2026-01-31,Marketing Spend,Marketing,80000,78000,70000",
    language="text")

# ── Where your file goes ─────────────────────────────────────────────────────
st.markdown("---")
st.markdown("#### Where your file goes")
st.write(
    "Replace the sample file at `data/sample_pnl.csv` with your own, keeping the "
    "same path and the same six columns. That is the simplest route. If you would "
    "rather keep your file elsewhere, change the `SAMPLE_DATA` path in "
    "`config.py` to point at it.")

# ── Running it ───────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("#### Running it")
st.write(
    "You need your own Anthropic API key for either route (the key makes the "
    "calls that write the commentary; the arithmetic is all local). The tool "
    "reads it from the `ANTHROPIC_API_KEY` environment variable, and the web app "
    "also accepts the key pasted into the sidebar for the session.")
st.write("**The web app, locally.** From the project root:")
st.code("pip install -r requirements.txt\nstreamlit run streamlit_app/Home.py",
        language="bash")
st.write(
    "Open the Variance Commentary page. The period picker lists the months found "
    "in your file; pick one and generate the commentary. This is the most "
    "forgiving route, because the picker adapts to whatever months your data "
    "contains.")
st.write("**The command-line tool.**")
st.code("python main.py", language="bash")
st.write(
    "The command-line run uses the default period set in `config.py` "
    "(`DEFAULT_PERIOD`). If your data does not contain that month, change it to a "
    "period your file has; if the period is not in the data, the run stops with "
    "an error that lists the periods your file does contain. It writes its "
    "results to the `output/` folder: the commentary as a text file, the report "
    "as a PDF, and a line appended to the audit log. The web app shows everything "
    "on the page and offers the PDF as a download instead.")

# ── Constraints ──────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("#### Constraints worth knowing")
st.markdown(
    "- **The six column names must match exactly.** A missing or renamed column "
    "stops the load with an error. The column order does not matter (they are "
    "read by name).\n"
    "- **Dates must be `YYYY-MM-DD`.** The period grouping reads the year and "
    "month from the start of the date, so a different format will not resolve "
    "into periods.\n"
    "- **Numbers must be numeric.** `actual`, `budget`, and `prior_year` must be "
    "numbers, except that `actual` and `budget` may be left blank to represent a "
    "missing figure (which the tool flags). Text in these columns stops the "
    "load.\n"
    "- **Per-line review thresholds are matched by account name.** The tool ships "
    "with sensible thresholds for the sample's account names (Revenue flags at "
    "ten percent, R&D at one hundred). If your lines are named differently, they "
    "fall back to the single default threshold. To get per-line thresholds on "
    "your own lines, edit the `VARIANCE_THRESHOLDS` map in `config.py`, or set "
    "them in the web app's Flagging thresholds panel for a run.\n"
    "- **Currency is configurable, and ships as euros.** The maths is "
    "currency-agnostic, but the commentary, the table, the trend chart, and the "
    "report label the figures in the currency set in `config.py` "
    "(`CURRENCY_CODE` and `CURRENCY_SYMBOL`). If your data is in another "
    "currency, set those two values (for example `USD` and `$`) so the words and "
    "labels match your numbers; the model is told the currency, so it describes "
    "the figures correctly.\n"
    "- **The maths is local; the commentary is not.** The figures, the variances, "
    "and the flags are all computed in Python on your machine. To write the "
    "commentary, the tool sends the selected period's figures to the Anthropic "
    "API in the prompt. So the model never calculates anything, but it does "
    "receive the numbers it describes.")

# ── Privacy ──────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("#### What stays private, and what does not")
st.write(
    "Running locally, your data file stays on your machine, and the public web "
    "app never sees it. The one thing that does leave your machine is the set of "
    "figures for a period you generate commentary on: those are sent to the "
    "Anthropic API, in your own account, under your own key, so the model can "
    "describe them. Nothing is sent to this project's authors or to the public "
    "app, and your key is used only to make those calls and is not stored.")
st.write(
    "If you would rather your figures never leave your machine at all, the "
    "commentary step is the only part that uses the API; the variance "
    "computation, the flags, the table, and the audit are all local and need no "
    "key.")

st.divider()
st.caption(
    "The public app runs on synthetic sample data only. These instructions are "
    "for running the project locally on your own figures.")

# =============================================================================
# trend_chart.py - the 12-month Actual vs Budget trend (one builder, two sinks)
# =============================================================================
# The one chart that earns its place: it shows what the single-period table
# cannot, how a line tracked against budget across the whole year. Built once
# here with matplotlib and used by BOTH the web page (st.pyplot) and the PDF
# (savefig -> reportlab), so the two surfaces are identical - the same shared
# builder pattern as build_pdf_bytes and hash_input.
#
# Honesty rule: the chart respects the same flags the table does, by reusing the
# pipeline's validate_and_flag per month (never a separate re-implementation):
#   - missing actual -> a GAP (no point, no interpolation across it)
#   - zero actual    -> a point at zero with a distinct amber flagged marker
#   - budget is always present, so it is a clean continuous dashed line.
# =============================================================================

import io
from contextlib import redirect_stdout

import matplotlib
matplotlib.use("Agg")                # non-interactive: server + PDF, no display
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import numpy as np

from src.step1_data_loader import validate_and_flag
from config import CURRENCY_CODE

# Theme palette (hex, matching theme.py / step3_output_writer)
_ACTUAL     = "#1A3A5C"   # dark blue, the Actual line
_BUDGET     = "#898781"   # muted grey, the Budget line (dashed)
_AMBER_FILL = "#FAEEDA"   # the table's amber flagged fill
_AMBER_EDGE = "#854F0B"   # the table's amber (the flagged triangle colour)
_GRID       = "#D3D1C7"
_TEXT       = "#1A1A19"
_MUTED      = "#898781"

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _flag_kind_for(df_12mo, date, dept):
    """Reuse the pipeline's flag logic for one month; return the flag kind for
    the given department that month ('MISSING_ACTUAL', 'ZERO_ACTUAL', ...) or
    None. validate_and_flag prints a summary, so its stdout is suppressed here."""
    month_rows = df_12mo[df_12mo["date"] == date]
    with redirect_stdout(io.StringIO()):
        _, flags = validate_and_flag(month_rows)
    for f in flags:
        kind, _, rest = f.partition(": ")
        if rest.split(" (")[0].strip() == dept:
            return kind
    return None


def build_trend_chart(df_12mo, account):
    """Return a matplotlib figure: 12-month Actual vs Budget for one line.

    Missing-actual months are gaps (no point, no interpolation); zero-actual
    months are plotted at zero with an amber flagged marker; budget is a clean
    continuous dashed line. Uses the theme palette. Pure apart from building the
    figure. The caller owns the figure and should close it after use."""
    sub = (df_12mo[df_12mo["account"] == account]
           .sort_values("date").reset_index(drop=True))

    x = list(range(len(sub)))
    actual_y, budget_y = [], []
    flag_x, flag_y = [], []
    for i, r in sub.iterrows():
        kind = _flag_kind_for(df_12mo, r["date"], r["department"])
        budget_y.append(float(r["budget"]))
        if kind == "MISSING_ACTUAL":
            actual_y.append(np.nan)                    # gap: no point, no line across
        elif kind == "ZERO_ACTUAL":
            actual_y.append(0.0)
            flag_x.append(i)
            flag_y.append(0.0)                         # amber flagged marker
        else:
            actual_y.append(float(r["actual"]))

    fig, ax = plt.subplots(figsize=(7.0, 3.1), dpi=150)
    ax.plot(x, budget_y, linestyle="--", color=_BUDGET, linewidth=1.6,
            label="Budget", zorder=2)
    ax.plot(x, actual_y, linestyle="-", color=_ACTUAL, linewidth=2.0,
            marker="o", markersize=3.5, label="Actual", zorder=3)
    if flag_x:
        # Solid amber triangle (the table's flag colour), large enough to read at
        # a glance, so a flagged zero is not lost against the drop to the baseline.
        ax.plot(flag_x, flag_y, linestyle="none", marker="^", markersize=13,
                markerfacecolor=_AMBER_EDGE, markeredgecolor=_AMBER_EDGE,
                markeredgewidth=0, label="Flagged month", zorder=5)
        # Explain the drop where it happens, not only in the footnote.
        for _fx in flag_x:
            ax.annotate("flagged", xy=(_fx, 0), xytext=(0, 13),
                        textcoords="offset points", ha="center",
                        fontsize=7, fontweight="bold", color=_AMBER_EDGE,
                        zorder=6)

    ax.set_title("{}: Actual vs Budget, 2026".format(account),
                 fontsize=11, fontweight="bold", color=_ACTUAL, loc="left")
    ax.set_ylabel(CURRENCY_CODE, fontsize=9, color=_TEXT)
    ax.set_xticks(x)
    ax.set_xticklabels(_MONTHS[:len(x)], fontsize=8, color=_TEXT)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: "{:,.0f}".format(v)))
    ax.tick_params(axis="y", labelsize=8, colors=_TEXT)
    ax.set_ylim(bottom=0)
    ax.grid(True, axis="y", color=_GRID, linewidth=0.6, alpha=0.7)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(_GRID)
    ax.spines["bottom"].set_color(_GRID)
    # Pinned to one corner for every line; a subtle white backdrop keeps it
    # readable when a flat, high line runs behind it.
    ax.legend(loc="upper left", fontsize=8, frameon=True, framealpha=0.9,
              facecolor="white", edgecolor="none")

    fig.tight_layout()
    if flag_x:
        fig.subplots_adjust(bottom=0.26)
        fig.text(0.01, 0.02,
                 "Amber marks a flagged month; see the variance table.",
                 ha="left", fontsize=7.5, color=_MUTED)
    return fig


def trend_png_bytes(df_12mo, account):
    """Convenience for the PDF path: build the chart and return PNG bytes."""
    fig = build_trend_chart(df_12mo, account)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    return buf.getvalue()

# =============================================================================
# pages/variance_commentary.py - the variance commentary tool
# =============================================================================
#   load_pnl -> filter_to_period -> validate_and_flag -> calculate_variances
#   -> build_prompt -> call_claude(client=per-session)
#
# The page orchestrates and renders only; it never recomputes a variance. All
# heavy logic is the existing, tested pipeline (src/step1..step3). The API is
# called ONLY when Generate is clicked, never on a passive rerun: the result is
# stored in session state and rendered from there.
#
# Two tabs, one renderer: "Run it yourself" (live, needs a key) and "View a
# worked example" (a saved real March run, no key). Both call _render_result, so
# the example looks exactly like a live run.
# =============================================================================

import sys
from pathlib import Path

import streamlit as st
import pandas as pd
import html as _html
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from streamlit_app.lib.theme import (
    inject_css, DARK_BLUE, MID_BLUE, LIGHT_BLUE, RULE, NEAR_WHITE,
    AMBER, AMBER_BG, FLAG_RED, MUTED, BODY_DARK,
)
from streamlit_app.lib.key_gate import render_key_gate
from streamlit_app.lib.errors import friendly_message
from streamlit_app.lib.policy import build_policy_from_ui, policy_note
from streamlit_app.lib.example_variance import load_example
from streamlit_app.lib.cost import estimate_cost, format_cost

from config import (
    SAMPLE_DATA, DEFAULT_ENTITY, DEFAULT_PERIOD,
    VARIANCE_THRESHOLDS, LARGE_VARIANCE_THRESHOLD,
)
from src.step1_data_loader import (
    load_pnl, filter_to_period, available_periods,
    validate_and_flag, calculate_variances,
)
from src.step2_ai_engine import build_prompt, call_claude
from src.step3_output_writer import (          # reuse tested helpers, never recompute
    _normalise_dashes, get_status, compute_requires_review,
    hash_input, build_pdf_bytes, parse_sections, extract_label,
)
from src.trend_chart import build_trend_chart   # shared 12-month trend builder
from matplotlib import pyplot as plt

st.markdown(inject_css(), unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown(
    '<div class="sc-header">'
    '<h1>Variance Commentary</h1>'
    '<p>Generate the management-accounts commentary for a period. Python '
    'computes every variance; the model writes the narrative; you review it.</p>'
    '</div>',
    unsafe_allow_html=True,
)

# ── Key gate (sidebar): returns a per-session client or None ──────────────────
client = render_key_gate()


@st.cache_data(show_spinner="Loading the sample P&L...")
def _load_full():
    """Load the full 12-month sample once and cache it, to build the picker.
    filter_to_period() copies before scoping, so this cached frame is never
    mutated."""
    return load_pnl(SAMPLE_DATA)


@st.cache_data(show_spinner=False)
def _example():
    """The keyless worked example (deterministic; no API). Cached per session."""
    return load_example()


try:
    full_df = _load_full()
except Exception as exc:
    st.error("Could not load the sample P&L. " + friendly_message(exc))
    st.stop()

labels = [label for _, label in available_periods(full_df)]
default_idx = labels.index(DEFAULT_PERIOD) if DEFAULT_PERIOD in labels else 0

# ── Session state (vc_ namespace, to avoid cross-page collisions) ─────────────
if "vc_result" not in st.session_state:
    st.session_state.vc_result = None      # last live result
if "vc_audit" not in st.session_state:
    st.session_state.vc_audit = []         # session-only lineage record (no file)


# =============================================================================
# Presentation helpers (no variance is computed here)
# =============================================================================
def _fmt_int(x):
    """Whole-unit figure with thousand separators, or a plain hyphen if absent."""
    return "-" if pd.isna(x) else "{:,.0f}".format(x)


def _css_colour(c):
    """step3's get_status returns a reportlab Color (built for the PDF). Convert
    it to a CSS hex so the same status colour renders in the browser. This keeps
    one source of truth for status: we reuse get_status and only re-express its
    colour for the web."""
    return "#{:02x}{:02x}{:02x}".format(
        int(round(c.red * 255)), int(round(c.green * 255)),
        int(round(c.blue * 255)))


def _variance_table_html(df, flags):
    """Render the tested calculate_variances output as an HTML table. Computes
    nothing. The Status column's glyph AND colour come from step3's revenue-aware
    get_status (its reportlab colour re-expressed as CSS), so screen and PDF read
    from the same status function. Flagged rows have no computed variance, so their
    variance cells are blank and the amber Status marker (plus an amber row tint)
    flags the row; the reason is in the Flags raised list above."""
    head = ("Account", "Department", "Actual", "Budget", "Variance",
            "Variance %", "Prior-year %", "Status")
    num_cols = {"Actual", "Budget", "Variance", "Variance %", "Prior-year %"}

    body = []
    for _, r in df.iterrows():
        flagged = pd.isna(r["variance_abs"])
        symbol, colour, _bg = get_status(
            r["account"], None if flagged else r["variance_abs"])
        variance = "" if flagged else "{:+,.0f}".format(r["variance_abs"])
        var_pct = "" if flagged else "{:+.1%}".format(r["variance_pct"])
        py = "" if pd.isna(r["prior_year_pct"]) else "{:+.1%}".format(
            r["prior_year_pct"])
        cells = {
            "Account": r["account"], "Department": r["department"],
            "Actual": _fmt_int(r["actual"]), "Budget": _fmt_int(r["budget"]),
            "Variance": variance, "Variance %": var_pct, "Prior-year %": py,
        }
        # Highlight the whole flagged row in amber so it reads as flagged at a
        # glance. Inline background overrides the zebra stripe.
        bg = "background:{};".format(AMBER_BG) if flagged else ""
        tds = []
        for col in head[:-1]:
            align = "right" if col in num_cols else "left"
            tds.append("<td style='{}text-align:{}'>{}</td>".format(
                bg, align, _html.escape(str(cells[col]))))
        tds.append(
            "<td style='{}text-align:center;color:{};font-weight:700;"
            "font-size:1.15rem'>{}</td>".format(bg, _css_colour(colour), symbol))
        body.append("<tr>" + "".join(tds) + "</tr>")

    ths = "".join("<th style='text-align:{}'>{}</th>".format(
        "right" if h in num_cols else "left", h) for h in head)
    return (
        "<style>"
        ".vc-wrap{{overflow-x:auto;}}"
        ".vc-table{{border-collapse:collapse;width:100%;font-size:0.84rem;"
        "font-variant-numeric:tabular-nums;}}"
        ".vc-table th{{background:{blue};color:#fff;padding:7px 9px;"
        "font-weight:600;white-space:nowrap;}}"
        ".vc-table td{{padding:6px 9px;border-bottom:1px solid {rule};"
        "white-space:nowrap;}}"
        ".vc-table tbody tr:nth-child(even) td{{background:{stripe};}}"
        "</style>"
        "<div class='vc-wrap'><table class='vc-table'>"
        "<thead><tr>{ths}</tr></thead><tbody>{body}</tbody></table></div>"
    ).format(blue=DARK_BLUE, rule=RULE, stripe=NEAR_WHITE,
             ths=ths, body="".join(body))


def _flag_chip_html(flag_text):
    """One flag rendered as a coloured chip. Amber for LARGE_VARIANCE (a computed
    variance past its threshold), red for a data-quality flag (missing/zero) - the
    same severity mapping the PDF's flag boxes use."""
    cls = "vc-flag-amber" if "LARGE_VARIANCE" in flag_text else "vc-flag-red"
    return "<div class='vc-flag {}'>▲ {}</div>".format(
        cls, _html.escape(flag_text))


def _commentary_html(commentary, df):
    """Re-present the model's commentary as structured, scannable HTML: an
    executive-summary callout, one card per line item (bold Department | Account
    label, a status dot straight from get_status so it matches the table, the
    prose, and any flag lifted into a coloured chip), then the data flags.

    It only RE-PRESENTS the model's text - it never rewrites a word. The split
    into sections and line items reuses step3's parse_sections and extract_label,
    the exact same parsing the PDF uses, so screen and report stay in step. All
    model text is HTML-escaped."""
    sections = parse_sections(commentary)

    # Status dot per account, from the same revenue-aware get_status the variance
    # table reads - so a line's dot on screen matches its dot in the table.
    status_map = {}
    for _, r in df.iterrows():
        sym, col, _bg = get_status(
            r["account"],
            None if pd.isna(r["variance_abs"]) else r["variance_abs"])
        status_map[str(r["account"])] = (sym, _css_colour(col))

    parts = []

    exec_txt = sections["executive_summary"].strip()
    if exec_txt:
        parts.append(
            "<div class='vc-comm-exec'>"
            "<div class='vc-comm-kicker'>Executive summary</div>"
            "<p>{}</p></div>".format(_html.escape(exec_txt)))

    line_items = sections["line_items"].strip()
    if line_items:
        parts.append(
            "<div class='vc-comm-kicker vc-comm-h'>Line-item commentary</div>")
        for line in [l.strip() for l in line_items.split("\n") if l.strip()]:
            if line.startswith("---") or line.startswith("##") or line == "--":
                continue
            label, body = extract_label(line)
            if label is None:
                parts.append(
                    "<p class='vc-comm-plain'>{}</p>".format(_html.escape(line)))
                continue
            # extract_label already strips the model's matched outer brackets, so
            # the heading reads cleanly and the account resolves for the status-dot
            # lookup below. The pipe separator is intended and stays.
            account = label.split(" | ")[-1].strip()
            sym, col = status_map.get(account, ("", MUTED))
            # Separate the prose from any [FLAG:...] marker(s) in the body.
            fi = body.find("[FLAG:")
            prose = (body if fi == -1 else body[:fi]).strip()
            chip = ""
            if fi != -1:
                flag_txt = body[fi:].strip()
                if flag_txt.startswith("[FLAG:"):
                    flag_txt = flag_txt[len("[FLAG:"):]
                flag_txt = flag_txt.rstrip("]").strip()
                chip = _flag_chip_html(flag_txt)
            dot = ("<span class='vc-dot' style='color:{}'>{}</span>".format(col, sym)
                   if sym else "")
            parts.append(
                "<div class='vc-comm-card'>"
                "<div class='vc-comm-label'>{dot}{label}</div>"
                "<p class='vc-comm-body'>{prose}</p>{chip}</div>".format(
                    dot=dot, label=_html.escape(label),
                    prose=_html.escape(prose), chip=chip))

    data_flags = sections["data_flags"].strip()
    if data_flags:
        # Only a line that names a flag type becomes a coloured chip. A clean
        # month's "No data quality issues identified." names none, so it renders
        # as plain text - not a stray red alert chip.
        FLAG_TYPES = ("LARGE_VARIANCE", "ZERO_ACTUAL", "MISSING_ACTUAL",
                      "ZERO_BUDGET", "MISSING_BUDGET")
        chips, plains = [], []
        for raw in data_flags.split("\n"):
            s = raw.strip().lstrip("-").strip()
            if not s:
                continue
            if any(t in s for t in FLAG_TYPES):
                chips.append(_flag_chip_html(s))
            else:
                plains.append(s)
        if chips or plains:
            parts.append(
                "<div class='vc-comm-kicker vc-comm-h'>Data flags</div>")
            for p in plains:
                parts.append(
                    "<p class='vc-comm-plain'>{}</p>".format(_html.escape(p)))
            parts.extend(chips)

    style = (
        "<style>"
        ".vc-comm{{font-size:0.92rem;line-height:1.5;color:{body};}}"
        ".vc-comm p{{margin:0;}}"
        ".vc-comm-kicker{{font-size:0.72rem;letter-spacing:0.06em;"
        "text-transform:uppercase;font-weight:700;color:{mid};margin-bottom:6px;}}"
        ".vc-comm-h{{margin-top:20px;padding-bottom:5px;"
        "border-bottom:1px solid {rule};}}"
        ".vc-comm-exec{{background:{light};border-left:4px solid {dark};"
        "border-radius:6px;padding:12px 15px;margin-bottom:4px;}}"
        ".vc-comm-card{{border:1px solid {rule};border-radius:8px;"
        "padding:11px 15px;margin:11px 0;background:#fff;}}"
        ".vc-comm-label{{font-weight:700;color:{dark};font-size:0.95rem;"
        "margin-bottom:5px;}}"
        ".vc-dot{{margin-right:8px;font-size:1.05rem;vertical-align:-1px;}}"
        ".vc-comm-body{{color:{body};}}"
        ".vc-comm-plain{{margin:9px 0;color:{body};}}"
        ".vc-flag{{border-radius:6px;padding:8px 12px;margin:9px 0 0;"
        "font-size:0.82rem;line-height:1.45;border:1px solid transparent;}}"
        ".vc-flag-amber{{background:{amberbg};color:{amber};border-color:#E8C88A;}}"
        ".vc-flag-red{{background:#FFF0F0;color:{red};border-color:#FFCCCC;}}"
        ".vc-comm-h + .vc-flag{{margin-top:9px;}}"
        "</style>"
    ).format(body=BODY_DARK, mid=MID_BLUE, rule=RULE, light=LIGHT_BLUE,
             dark=DARK_BLUE, amberbg=AMBER_BG, amber=AMBER, red=FLAG_RED)

    return style + "<div class='vc-comm'>" + "".join(parts) + "</div>"


def _render_result(res, key_prefix):
    """Render one result dict (live OR example) with the shared surfaces, so the
    two paths look identical: period/entity, policy note, review panel, variance
    table, commentary, and a PDF download. Pure rendering; no API call.

    Order: what happened (review status, then the figures) before what it means
    (the commentary), so a reviewer can check the words against the numbers."""
    st.subheader("{} - {}".format(res["period"], res["entity"]))
    st.caption(policy_note(res["policy"]))

    # 1. Review panel (shared decision from step3; no recompute)
    required, reasons = compute_requires_review(
        res["flags"], res["stop_reason"], res["output_tokens"])
    st.markdown("#### Review status")
    if required:
        st.warning("Human review required before this commentary is used.")
        for reason in reasons:
            st.markdown("- " + reason)
        if res["flags"]:
            st.markdown("**Flags raised:**")
            for f in res["flags"]:
                st.markdown("- " + f)
    else:
        st.caption("No review flags for this period.")

    # 2. Variance table (revenue-aware status straight from step3)
    st.markdown("#### Variance table")
    st.markdown(_variance_table_html(res["df"], res["flags"]),
                unsafe_allow_html=True)
    st.caption(
        "The Status dot shows favourability: green favourable, red adverse, "
        "amber for a flagged line with no computed variance. Every figure is "
        "computed in Python.")

    # 2b. 12-month trend (full-year context; not the single period above). The
    # selector picks the line, defaulting to Revenue. Changing it re-draws the
    # chart deterministically; it does not call the API.
    st.markdown("#### 12-month trend")
    _accounts = list(VARIANCE_THRESHOLDS.keys())
    _account = st.selectbox(
        "Line", _accounts,
        index=_accounts.index("Revenue") if "Revenue" in _accounts else 0,
        key="vc_trend_" + key_prefix)
    _fig = build_trend_chart(full_df, _account)
    st.pyplot(_fig)
    plt.close(_fig)

    # 3. Commentary - re-presented as structured cards (never reworded). Same
    # parse_sections/extract_label the PDF uses, so the two surfaces stay in step.
    st.markdown("#### Commentary")
    st.markdown(_commentary_html(res["commentary"], res["df"]),
                unsafe_allow_html=True)
    st.caption(format_cost(res["input_tokens"], res["output_tokens"]))

    # 4. PDF download, built from this result (no fresh API call, no file written)
    try:
        pdf_bytes = build_pdf_bytes(
            res["commentary"], res["df"], res["flags"],
            res["input_tokens"], res["output_tokens"],
            res["period"], res["entity"], res["generated_at"],
            policy_note_text=policy_note(res["policy"]),
            df_12mo=full_df)
        st.download_button(
            "Download PDF", data=pdf_bytes,
            file_name="variance_commentary_{}.pdf".format(
                res["period"].replace(" ", "_")),
            mime="application/pdf", key="vc_pdf_" + key_prefix)
    except Exception as exc:
        st.caption("The PDF is unavailable this session: " + friendly_message(exc))


# =============================================================================
# Tabs: live run, and the keyless worked example
# =============================================================================
tab_live, tab_example = st.tabs(["Run it yourself", "View a worked example"])

with tab_live:
    # ── Scope controls ────────────────────────────────────────────────────────
    st.markdown("#### Choose a period")
    period = st.selectbox(
        "Reporting period", labels, index=default_idx, key="vc_period")
    st.caption("Entity: {} (fixed in this phase)".format(DEFAULT_ENTITY))

    # ── Flagging thresholds (optional; per-line defaults handle the common case)
    # Read AT GENERATE time, like the period. Changing a value without clicking
    # Generate does not re-run and does not call the API.
    with st.expander("Flagging thresholds"):
        st.caption(
            "A line is flagged when its variance from budget exceeds its "
            "threshold. Each value is a percentage: for example, Revenue 10% "
            "flags any revenue variance beyond 10% in either direction. Change "
            "any value and regenerate to see the flags update.")

        def _reset_thresholds():
            for _acct, _frac in VARIANCE_THRESHOLDS.items():
                st.session_state["vc_thr_" + _acct] = _frac * 100.0
            st.session_state["vc_thr__default"] = LARGE_VARIANCE_THRESHOLD * 100.0

        # Initialise each input to its config percentage once, before the widget
        # reads it. Using key only (no value=) avoids the double-set warning and
        # lets Reset write session state cleanly.
        for _acct, _frac in VARIANCE_THRESHOLDS.items():
            st.session_state.setdefault("vc_thr_" + _acct, _frac * 100.0)
        st.session_state.setdefault(
            "vc_thr__default", LARGE_VARIANCE_THRESHOLD * 100.0)

        # Two columns so the eight inputs read as a tidy grid, not a tall list.
        _cols = st.columns(2)
        percent_map = {}
        for _i, _acct in enumerate(VARIANCE_THRESHOLDS):
            with _cols[_i % 2]:
                percent_map[_acct] = st.number_input(
                    _acct + " (%)", min_value=0.0, max_value=500.0, step=5.0,
                    format="%.0f", key="vc_thr_" + _acct)
        default_percent = st.number_input(
            "Default (%), any line without its own threshold",
            min_value=0.0, max_value=500.0, step=5.0,
            format="%.0f", key="vc_thr__default")

        st.button("Reset to defaults", on_click=_reset_thresholds)

    if client is None:
        st.info(
            "Paste your Anthropic API key in the sidebar to generate commentary, "
            "or open the worked-example tab to see a full result with no key.")

    # ── Generate (the ONLY place the API is called) ──────────────────────────
    if st.button("Generate commentary", type="primary"):
        if client is None:
            st.warning(
                "Paste your API key in the sidebar to run a live generation.")
        else:
            with st.spinner("Generating commentary..."):
                try:
                    policy = build_policy_from_ui(percent_map, default_percent)
                    scoped = filter_to_period(full_df, period)
                    scoped, flags = validate_and_flag(scoped, thresholds=policy)
                    scoped = calculate_variances(scoped, flags)
                    system_p, user_p = build_prompt(
                        scoped, flags, period, DEFAULT_ENTITY)
                    commentary, in_tokens, out_tokens, stop_reason = call_claude(
                        system_p, user_p, client=client)
                    commentary = _normalise_dashes(commentary)

                    generated_at = datetime.now(timezone.utc).isoformat()
                    input_hash = hash_input(scoped)     # data lineage; same as CLI
                    review_required, _ = compute_requires_review(
                        flags, stop_reason, out_tokens)

                    st.session_state.vc_result = {
                        "period": period,
                        "entity": DEFAULT_ENTITY,
                        "commentary": commentary,
                        "df": scoped,           # variance columns from calculate_variances
                        "flags": flags,
                        "policy": policy,       # fractions; provenance
                        "stop_reason": stop_reason,
                        "input_tokens": in_tokens,
                        "output_tokens": out_tokens,
                        "input_hash": input_hash,
                        "generated_at": generated_at,
                    }
                    # Session-only audit record. No file is written, and the API
                    # key is never stored here (only hash, flags, tokens, policy).
                    st.session_state.vc_audit.insert(0, {
                        "generated_at": generated_at,
                        "period": period,
                        "entity": DEFAULT_ENTITY,
                        "input_hash": input_hash,
                        "flags": flags,
                        "requires_review": review_required,
                        "policy": policy,
                        "input_tokens": in_tokens,
                        "output_tokens": out_tokens,
                        "stop_reason": stop_reason,
                        # Raw tokens above stay authoritative; the estimate can be
                        # recomputed from them if rates change.
                        "cost": estimate_cost(in_tokens, out_tokens),
                    })
                except Exception as exc:
                    st.session_state.vc_result = None
                    st.error(friendly_message(exc))

    if st.session_state.vc_result:
        st.divider()
        _render_result(st.session_state.vc_result, "live")

    # ── Session audit (this tab only: your live runs this session) ───────────
    if st.session_state.vc_audit:
        n = len(st.session_state.vc_audit)
        with st.expander("Session audit ({} run{})".format(
                n, "" if n == 1 else "s")):
            st.caption(
                "This session's live runs, most recent first. Session-only: it "
                "is cleared when the session ends, and your API key is never "
                "stored here. The CLI keeps the persistent audit log on disk.")
            for rec in st.session_state.vc_audit:
                st.markdown("**{} - {}**  ({} UTC)".format(
                    rec["period"], rec["entity"],
                    rec["generated_at"][:19].replace("T", " ")))
                st.markdown(
                    "Data lineage (sha256): `{}`".format(rec["input_hash"]))
                st.caption(policy_note(rec["policy"]))
                st.markdown(
                    "Flags: {}  |  Review required: {}  |  Tokens: {:,} in / "
                    "{:,} out  |  Stop: {}".format(
                        len(rec["flags"]),
                        "yes" if rec["requires_review"] else "no",
                        rec["input_tokens"], rec["output_tokens"],
                        rec["stop_reason"]))
                st.caption(format_cost(rec["input_tokens"], rec["output_tokens"]))
                st.divider()

with tab_example:
    st.info("This is a saved example run for March 2026. It needs no API key.")
    try:
        example = _example()
    except Exception as exc:
        st.error("Could not load the worked example. " + friendly_message(exc))
        example = None
    if example:
        _render_result(example, "example")
        with st.expander("Example audit record"):
            st.markdown(
                "Data lineage (sha256): `{}`".format(example["input_hash"]))
            st.caption(policy_note(example["policy"]))
            st.markdown(
                "Flags: {}  |  Review required: {}  |  Tokens: {:,} in / {:,} out"
                "  |  Stop: {}".format(
                    len(example["flags"]),
                    "yes" if example["requires_review"] else "no",
                    example["input_tokens"], example["output_tokens"],
                    example["stop_reason"]))
            st.caption(
                format_cost(example["input_tokens"], example["output_tokens"]))
        st.caption(
            "Every figure here is computed from the committed March rows; the "
            "commentary is the saved text from that real run. Nothing is "
            "fabricated.")

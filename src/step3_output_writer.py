# =============================================================================
# step3_output_writer.py — Layer 4: Output Writing and Audit Trail
# =============================================================================
# Responsibilities:
#   - write_output(): write commentary to timestamped text file + audit log
#   - write_pdf():    format commentary into professional A4 PDF
#
# PDF layout:
#   1. Cover header        — entity, period, run metadata
#   2. Executive Summary   — 3-sentence narrative
#   3. Variance Summary    — numbers-first table with dot/triangle status
#   4. Line Item Commentary — clean labels + body + inline flag boxes
#   5. Data Flags          — compact action table
#   6. Footer
#
# Key design decisions:
#   - Em dash — for missing/unavailable numeric values (not "MISSING")
#   - Green dot ● for favourable, red dot ● for unfavourable, △ for flagged
#   - Revenue-aware status: cost overspend = red, cost underspend = green
#   - All backgrounds use Table+TableStyle (not ParagraphStyle.backColor)
#   - All HexColor objects defined once at module level, never double-wrapped
#   - extract_label() splits on ' | ' not first ':' - avoids [FLAG: conflict
#   - clean_markdown() strips ** ## --- artefacts from Claude output
# =============================================================================

import re
import hashlib
import json
from io import BytesIO
from pathlib import Path
from datetime import datetime, timezone
from xml.sax.saxutils import escape as _xml_escape

import pandas as pd

from reportlab.lib.pagesizes import A4
from reportlab.lib.units     import cm
from reportlab.lib           import colors
from reportlab.lib.styles    import ParagraphStyle
from reportlab.lib.enums     import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus      import (
    SimpleDocTemplate, Paragraph, Spacer,
    HRFlowable, Table, TableStyle, KeepTogether, Image
)
from reportlab.lib.utils     import ImageReader

from config import (
    OUTPUT_DIR,
    AUDIT_LOG,
    DEFAULT_PERIOD,
    DEFAULT_ENTITY,
    MODEL,
    LARGE_VARIANCE_THRESHOLD,
    VARIANCE_THRESHOLDS,
)

# ── Page geometry ─────────────────────────────────────────────────────────────
PAGE_W = A4[0] - 4 * cm

# ── Colour palette ────────────────────────────────────────────────────────────
DARK_BLUE   = colors.HexColor("#1A3A5C")
MID_BLUE    = colors.HexColor("#2D6A9F")
LIGHT_BLUE  = colors.HexColor("#EAF2FB")
GREEN       = colors.HexColor("#1D6B0F")
GREEN_BG    = colors.HexColor("#EAF3DE")
FLAG_RED    = colors.HexColor("#A32D2D")
FLAG_BG     = colors.HexColor("#FFF0F0")
FLAG_BORDER = colors.HexColor("#FFCCCC")
AMBER       = colors.HexColor("#854F0B")
AMBER_BG    = colors.HexColor("#FAEEDA")
AMBER_BDR   = colors.HexColor("#E8C88A")
BODY_DARK   = colors.HexColor("#1A1A19")
MUTED       = colors.HexColor("#898781")
RULE_COLOR  = colors.HexColor("#D3D1C7")
ROW_ALT     = colors.HexColor("#F8F7F2")
TBL_HEADER  = colors.HexColor("#E6F1FB")

# ── Reusable paragraph styles ─────────────────────────────────────────────────
S_BODY    = ParagraphStyle("Body",   fontName="Helvetica", fontSize=10,
                textColor=BODY_DARK, leading=16)
S_META    = ParagraphStyle("Meta",   fontName="Helvetica", fontSize=8,
                textColor=MUTED, leading=13, alignment=TA_CENTER)
S_TBL     = ParagraphStyle("Tbl",    fontName="Helvetica", fontSize=9,
                textColor=BODY_DARK, leading=12)
S_TBL_HDR = ParagraphStyle("TblHdr", fontName="Helvetica-Bold", fontSize=9,
                textColor=DARK_BLUE, leading=12)
S_TBL_NUM = ParagraphStyle("TblNum", fontName="Helvetica", fontSize=9,
                textColor=BODY_DARK, leading=12, alignment=TA_RIGHT)

# ── Display constants ─────────────────────────────────────────────────────────
EM = "\u2014"   # — em dash: used for missing/unavailable numeric values


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def _esc(text):
    """XML-escape dynamic text before it goes inside a reportlab Paragraph.

    reportlab parses Paragraph content as mini-XML, so a bare '&' immediately
    followed by a name character (as in 'R&D Expense') is read as the start of
    an entity reference and mangled - 'R&D Expense' renders as 'R&D; Expense'.
    Escaping &, <, > fixes it. Safe to apply to every account/department/
    commentary token because clean_markdown has already stripped Claude's
    markdown down to plain text: there is no intended reportlab markup in the
    content to double-escape (the <b>/<font> tags are added around it, here)."""
    return _xml_escape(str(text))


def clean_markdown(text):
    """
    Strip Claude markdown artefacts before PDF rendering.
    ReportLab does not interpret markdown — ** ## --- render as literal chars.
    """
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)             # **bold** -> bold
    text = re.sub(r'^#{1,3}\s*', '', text, flags=re.MULTILINE)  # ## heading
    text = re.sub(r'^---+\s*$',   '', text, flags=re.MULTILINE) # --- rule
    text = re.sub(r'^\*\s+',      '', text, flags=re.MULTILINE) # * bullet
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def extract_label(line):
    """
    Safely extract the 'Department | Account' label from a line item.

    Splits on ' | ' to find the label boundary, NOT on the first colon.
    The first-colon approach broke on flagged lines because '[FLAG:'
    also contains a colon, producing corrupt labels like:
        'Technology | IT Infrastructure: [FLAG'  <- wrong

    This correctly produces:
        label = 'Technology | IT Infrastructure'
        body  = '[FLAG: ZERO_ACTUAL ...]'

    The pipe is unambiguous: it never appears in a department or account
    name and does not collide with '[FLAG:'. Legacy em/en dash separators
    are still accepted so any pre-existing output remains parseable.

    The model brackets its labels ('[Department | Account]'); a matched outer
    '[ ]' pair is stripped so both the PDF and the web cards show a clean label
    ('Sales | Revenue', not '[Sales | Revenue]'). Only a matched pair is stripped;
    a lone unmatched bracket is left as-is. This is a display transform on the
    label only: it never touches the stored commentary, so the verbatim
    fabrication guard is unaffected.

    Returns (label, body) or (None, line) if no pattern found.
    """
    # Pipe is the current separator; em/en dash kept as legacy tolerance.
    sep = None
    if ' | ' in line:
        sep = ' | '
    elif ' \u2014 ' in line:
        sep = ' \u2014 '
    elif ' \u2013 ' in line:
        sep = ' \u2013 '

    if sep is None:
        return None, line

    sep_pos   = line.index(sep)
    colon_pos = line[sep_pos:].find(': ')

    if colon_pos == -1:
        return None, line

    label_end = sep_pos + colon_pos
    label     = re.sub(r'\*\*([^*]+)\*\*', r'\1',
                       line[:label_end].strip()).strip('*').strip()
    # Strip a matched outer bracket pair (the model wraps labels in '[ ]'). Done
    # after the markdown strip so a bold-wrapped label ('**[A | B]**') also cleans
    # up. Matched only: a lone '[' or ']' is left as-is.
    if label.startswith("[") and label.endswith("]"):
        label = label[1:-1].strip()
    body      = line[label_end + 2:].strip()

    return label, body


def get_status(account, variance_abs):
    """
    Return (symbol, text_color, background_color) for the status column.

    Symbols:
      ● (U+25CF) filled circle — green for FAV, red for UNF
      △ (U+25B3) triangle      — amber for flagged/data quality issue
      – (U+2013) en dash       — muted for zero variance

    Revenue-aware logic:
      Revenue lines: actual > budget -> green ● (more revenue = good)
                     actual < budget -> red   ● (less revenue = bad)
      Cost lines:    actual > budget -> red   ● (overspend = bad)
                     actual < budget -> green ● (underspend/saving = good)
    """
    if variance_abs is None or pd.isna(variance_abs):
        return "\u25b3", AMBER, AMBER_BG       # △ amber triangle

    is_revenue = "revenue" in str(account).lower()

    if variance_abs > 0:
        if is_revenue:
            return "\u25cf", GREEN,    GREEN_BG   # ● green
        else:
            return "\u25cf", FLAG_RED, FLAG_BG    # ● red
    elif variance_abs < 0:
        if is_revenue:
            return "\u25cf", FLAG_RED, FLAG_BG    # ● red
        else:
            return "\u25cf", GREEN,    GREEN_BG   # ● green
    else:
        return "\u2013", MUTED, colors.white       # – en dash (zero)


def parse_sections(commentary):
    """
    Parse Claude commentary into three named sections after cleaning markdown.
    Falls back gracefully — puts full text in executive_summary if no headers.
    """
    commentary = clean_markdown(commentary)

    sections = {
        "executive_summary": "",
        "line_items":        "",
        "data_flags":        "",
    }
    markers = {
        "executive_summary": "EXECUTIVE SUMMARY",
        "line_items":        "LINE ITEM COMMENTARY",
        "data_flags":        "DATA FLAGS",
    }

    text      = commentary.strip()
    positions = {}
    for key, marker in markers.items():
        idx = text.find(marker)
        if idx != -1:
            positions[key] = idx

    if not positions:
        sections["executive_summary"] = text
        return sections

    sorted_keys = sorted(positions, key=lambda k: positions[k])
    for i, key in enumerate(sorted_keys):
        start = positions[key] + len(markers[key])
        end   = positions[sorted_keys[i + 1]] if i + 1 < len(sorted_keys) else len(text)
        sections[key] = text[start:end].strip()

    return sections


def _muted_para(text):
    """
    Render em dash in muted grey; render all other text in body dark.
    Used for missing/unavailable numeric cells — lets the status symbol
    carry the visual alert instead of text in the number column.
    """
    if text == EM:
        return Paragraph(
            '<font color="#898781">{}</font>'.format(text),
            S_TBL_NUM
        )
    return Paragraph(text, S_TBL_NUM)


# =============================================================================
# PDF COMPONENT BUILDERS
# =============================================================================

def _cover_block(period, entity, ts, tok_in, tok_out, nflags):
    """Full-width dark blue cover — title row + metadata row."""
    rows = [
        [Paragraph(
            '<font color="white"><b>VARIANCE COMMENTARY  -  {}</b></font>'.format(
                _esc(period.upper())),
            ParagraphStyle("CT", fontName="Helvetica-Bold", fontSize=18,
                textColor=colors.white, alignment=TA_CENTER)
        )],
        [Paragraph(
            '<font color="#AACCEE">{}  ·  AI Generated  ·  {}  ·  '
            '{:,}/{:,} tokens  ·  {} flag(s)</font>'.format(
                _esc(entity), MODEL, tok_in, tok_out, nflags),
            ParagraphStyle("CS", fontName="Helvetica", fontSize=9,
                textColor=colors.HexColor("#AACCEE"), alignment=TA_CENTER)
        )],
    ]
    t = Table(rows, colWidths=[PAGE_W])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), DARK_BLUE),
        ("TOPPADDING",    (0, 0), (0, 0),   18),
        ("BOTTOMPADDING", (0, 0), (0, 0),   6),
        ("TOPPADDING",    (0, 1), (0, 1),   4),
        ("BOTTOMPADDING", (0, 1), (0, 1),   14),
        ("LEFTPADDING",   (0, 0), (-1, -1), 20),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 20),
    ]))
    return t


def _section_header(title):
    """Full-width mid-blue section header band."""
    t = Table([[Paragraph(
        '<font color="white"><b>{}</b></font>'.format(title),
        ParagraphStyle("SH", fontName="Helvetica-Bold", fontSize=11,
            textColor=colors.white, leading=14)
    )]], colWidths=[PAGE_W])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), MID_BLUE),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


def _variance_table(df):
    """
    Numbers-first variance summary table.

    Columns: Department | Account | Actual | Budget | Variance | Var % | Status
    Status:  ● green (FAV) | ● red (UNF) | △ amber (flagged)
    Missing numeric values: — em dash in muted grey (not 'MISSING')
    Last column width computed to fill remaining page width exactly.
    """
    last_col = PAGE_W - (2.2 + 3.5 + 2.3 + 2.3 + 2.3 + 1.8) * cm
    cw = [2.2*cm, 3.5*cm, 2.3*cm, 2.3*cm, 2.3*cm, 1.8*cm, last_col]

    headers = ["Department", "Account", "Actual", "Budget",
               "Variance", "Var %", "Status"]
    rows = [[Paragraph("<b>{}</b>".format(h), S_TBL_HDR) for h in headers]]

    for i, (_, row) in enumerate(df.iterrows()):
        flagged = pd.isna(row["variance_abs"])

        # Numeric cell values — em dash for missing/unavailable
        actual_str = EM if pd.isna(row["actual"]) else "{:,.0f}".format(row["actual"])
        budget_str = EM if pd.isna(row["budget"]) else "{:,.0f}".format(row["budget"])
        var_str    = EM if flagged else "{:+,.0f}".format(row["variance_abs"])
        pct_str    = EM if flagged else "{:+.1%}".format(row["variance_pct"])

        # Status symbol and colours
        symbol, stc, sbg = get_status(
            row["account"],
            row["variance_abs"] if not flagged else None
        )

        rows.append([
            Paragraph(_esc(row["department"]), S_TBL),
            Paragraph(_esc(row["account"]),    S_TBL),
            _muted_para(actual_str),
            _muted_para(budget_str),
            _muted_para(var_str),
            _muted_para(pct_str),
            Paragraph(
                '<font color="{}">{}</font>'.format(
                    stc.hexval() if hasattr(stc, "hexval") else "#000000",
                    symbol
                ),
                ParagraphStyle("ST", fontName="Helvetica", fontSize=14,
                    textColor=stc, alignment=TA_CENTER, leading=14)
            ),
        ])

    style = [
        ("BACKGROUND",    (0, 0),  (-1, 0),  TBL_HEADER),
        ("LINEBELOW",     (0, 0),  (-1, 0),  1,   MID_BLUE),
        ("TOPPADDING",    (0, 0),  (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0),  (-1, -1), 5),
        ("LEFTPADDING",   (0, 0),  (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0),  (-1, -1), 6),
        ("LINEBELOW",     (0, 1),  (-1, -1), 0.5, RULE_COLOR),
        ("VALIGN",        (0, 0),  (-1, -1), "MIDDLE"),
    ]
    for i in range(1, len(rows)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))

    t = Table(rows, colWidths=cw)
    t.setStyle(TableStyle(style))
    return t


def _flag_summary_table(flags):
    """
    Compact data flags action table — three columns.
    Columns: Flag type | Department | Action required
    Replaces repeated flag boxes — information appears once, cleanly.
    """
    if not flags:
        return Paragraph("No data quality issues identified.", S_BODY)

    cw = [2.8 * cm, 3.2 * cm, PAGE_W - 6.0 * cm]

    ACTIONS = {
        "ZERO_ACTUAL":    "Confirm whether spend was deferred, miscoded, or not incurred. Investigate before period close.",
        "MISSING_ACTUAL": "Submit actual figure immediately. Report cannot be signed off with missing data.",
        "LARGE_VARIANCE": "Provide written explanation to CFO before Board submission. Confirm whether full-year budget requires restatement.",
        "ZERO_BUDGET":    "Confirm cost centre is correctly set up. Verify whether expenditure was anticipated.",
        "MISSING_BUDGET": "Confirm budget allocation. Variance cannot be calculated without a budget figure.",
    }

    rows = [[
        Paragraph("<b>Flag type</b>",      S_TBL_HDR),
        Paragraph("<b>Department</b>",      S_TBL_HDR),
        Paragraph("<b>Action required</b>", S_TBL_HDR),
    ]]

    for flag in flags:
        if ": " in flag:
            flag_type = flag.split(": ")[0].strip()
            dept_part = flag.split(": ")[1].split(" (")[0].strip()
        else:
            flag_type = flag
            dept_part = ""

        action  = ACTIONS.get(flag_type,
                    "Review and confirm with department head before period close.")
        tc_hex  = "#854F0B" if "LARGE_VARIANCE" in flag_type else "#A32D2D"

        rows.append([
            Paragraph(
                '<font color="{}"><b>{}</b></font>'.format(tc_hex, _esc(flag_type)),
                S_TBL
            ),
            Paragraph(_esc(dept_part), S_TBL),
            Paragraph(action,    S_TBL),
        ])

    style = [
        ("BACKGROUND",    (0, 0), (-1, 0),  TBL_HEADER),
        ("LINEBELOW",     (0, 0), (-1, 0),  1,   MID_BLUE),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("LINEBELOW",     (0, 1), (-1, -1), 0.5, RULE_COLOR),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]
    for i in range(1, len(rows)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))

    t = Table(rows, colWidths=cw)
    t.setStyle(TableStyle(style))
    return t


def _line_item(label, body):
    """Standard line item: light blue label row + white body row."""
    rows = [
        [Paragraph(
            '<b>{}</b>'.format(_esc(label)),
            ParagraphStyle("LIL", fontName="Helvetica-Bold", fontSize=10,
                textColor=MID_BLUE, leading=14)
        )],
        [Paragraph(
            _esc(body),
            ParagraphStyle("LIB", fontName="Helvetica", fontSize=10,
                textColor=BODY_DARK, leading=15)
        )],
    ]
    t = Table(rows, colWidths=[PAGE_W])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (0, 0),    LIGHT_BLUE),
        ("BACKGROUND",    (0, 1), (0, 1),    colors.white),
        ("LEFTPADDING",   (0, 0), (-1, -1),  10),
        ("RIGHTPADDING",  (0, 0), (-1, -1),  10),
        ("TOPPADDING",    (0, 0), (0, 0),    6),
        ("BOTTOMPADDING", (0, 0), (0, 0),    4),
        ("TOPPADDING",    (0, 1), (0, 1),    4),
        ("BOTTOMPADDING", (0, 1), (0, 1),    8),
        ("LINEBELOW",     (0, -1), (-1, -1), 0.5, RULE_COLOR),
    ]))
    return KeepTogether(t)


def _flag_inline(text, severity="error"):
    """
    Compact inline flag box shown below a flagged line item label.
    severity='error'   -> red   (MISSING_ACTUAL, ZERO_ACTUAL, ZERO_BUDGET)
    severity='warning' -> amber (LARGE_VARIANCE)
    """
    if severity == "error":
        bg, tc, bdr = FLAG_BG, FLAG_RED, FLAG_BORDER
    else:
        bg, tc, bdr = AMBER_BG, AMBER, AMBER_BDR

    t = Table([[Paragraph(
        '<b>[!]</b>  {}'.format(_esc(text)),
        ParagraphStyle("FI", fontName="Helvetica", fontSize=9,
            textColor=tc, leading=13)
    )]], colWidths=[PAGE_W])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), bg),
        ("LEFTPADDING",   (0, 0), (-1, -1), 12),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW",     (0, 0), (-1, -1), 0.5, bdr),
    ]))
    return t


def _normalise_dashes(text):
    """Replace em/en dashes with plain hyphens in model-generated prose.

    Applies to commentary text only. Does NOT touch the nil-value glyph used in
    the PDF's number columns (EM), which is a separate, intentional accounting
    symbol. Idempotent, so it is safe to apply at every writer entry point.
    """
    return text.replace("—", "-").replace("–", "-")


# Below this many output tokens, a full 7-line commentary is suspiciously
# short and likely incomplete. Same value the CLI has always used.
LOW_TOKEN_FLOOR = 200


def compute_requires_review(flags, stop_reason, output_tokens,
                            low_token_floor=LOW_TOKEN_FLOOR):
    """Return (requires_review: bool, reasons: list[str]).

    Pure. No file IO, so both the CLI writer and the web page can share it.
    Trips when any of:
      - data flags were raised
      - the model output was truncated (stop_reason indicates max_tokens)
      - the output was suspiciously short (output_tokens < low_token_floor)

    The short-output reason is suppressed when the output was truncated, so a
    truncated-and-short run reads as one clear cause, not two. This preserves
    the exact boolean the CLI has always recorded.
    """
    reasons = []
    if flags:
        reasons.append("Data flags were raised for this period.")
    truncated = (stop_reason == "max_tokens")
    if truncated:
        reasons.append("The commentary was truncated (hit the token limit).")
    if output_tokens < low_token_floor and not truncated:
        reasons.append("The commentary was unusually short.")
    return (len(reasons) > 0, reasons)


INPUT_COLUMNS = ["date", "account", "department", "actual", "budget", "prior_year"]


def hash_input(df):
    """Return 'sha256:<hex>' of the canonical input data. Pure, no file IO, so
    the CLI writer and the web audit can share it. Hashes only the input columns
    in a fixed order, so the hash is stable regardless of any computed columns
    added downstream and identical for the CLI and the web on the same scoped
    data (this proves data lineage)."""
    canonical = df[INPUT_COLUMNS].to_csv(index=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# =============================================================================
# FUNCTION 1: Write commentary text file and audit log
# =============================================================================
def write_output(commentary, input_file, flags, tok_in, tok_out, stop_reason, input_rows=0, thresholds=None, df=None):
    """
    Write commentary to a timestamped text file and append one JSONL
    audit record per run. SHA256 hash of input file proves data lineage.

    thresholds: optional per-line policy dict {account: fraction, '_default':
    fraction}. Resolved and recorded in the audit so the flagging policy used
    for the run becomes part of the provenance. When None, the config policy is
    resolved and recorded.
    """
    commentary = _normalise_dashes(commentary)
    input_file = Path(input_file)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Resolve the per-line threshold policy actually used for this run, mirroring
    # step1's _resolve_thresholds so the record shows the real policy even when
    # thresholds is None.
    # COUPLING: this must match the policy passed to validate_and_flag for the
    # same run, or the recorded policy will not match the flags it produced.
    if thresholds is None:
        policy = dict(VARIANCE_THRESHOLDS)
        policy["_default"] = LARGE_VARIANCE_THRESHOLD
    else:
        policy = dict(thresholds)
        policy.setdefault("_default", LARGE_VARIANCE_THRESHOLD)

    now     = datetime.now(timezone.utc)
    ts_file = now.strftime("%Y-%m-%d_%H-%M-%S")
    ts_log  = now.isoformat()

    output_filename = "variance_commentary_{}.txt".format(ts_file)
    output_path     = OUTPUT_DIR / output_filename

    header = (
        "VARIANCE COMMENTARY - GENERATED OUTPUT\n"
        "{sep}\n"
        "Generated:  {ts}\n"
        "Period:     {period}\n"
        "Entity:     {entity}\n"
        "Input file: {fname}\n"
        "Model:      {model}\n"
        "Tokens:     {tok_in:,} in / {tok_out:,} out\n"
        "Flags:      {nflags} raised\n"
        "{sep}\n\n"
    ).format(
        sep     = "=" * 60,
        ts      = ts_log,
        period  = DEFAULT_PERIOD,
        entity  = DEFAULT_ENTITY,
        fname   = input_file.name,
        model   = MODEL,
        tok_in  = tok_in,
        tok_out = tok_out,
        nflags  = len(flags),
    )

    output_path.write_text(header + commentary, encoding="utf-8")

    # Data lineage: hash the scoped input rows when the caller provides the df
    # (shared with the web via hash_input); otherwise hash the file bytes.
    if df is not None:
        input_hash = hash_input(df)
    else:
        with open(input_file, "rb") as f:
            input_hash = "sha256:" + hashlib.sha256(f.read()).hexdigest()

    # Shared pure decision, so the CLI and the web page never diverge on when
    # review is required. The audit still records the boolean below.
    requires_review, _review_reasons = compute_requires_review(
        flags, stop_reason, tok_out)

    audit_record = {
        "run_id":          ts_log,
        "project":         "variance-commentary-engine",
        "period":          DEFAULT_PERIOD,
        "entity":          DEFAULT_ENTITY,
        "input_file":      str(input_file),
        "input_rows":      input_rows,
        "input_hash":      input_hash,
        "output_file":     str(output_path),
        "pdf_file":        None,
        "model":           MODEL,
        "input_tokens":    tok_in,
        "output_tokens":   tok_out,
        "stop_reason":     stop_reason,
        "flags_raised":    flags,
        "thresholds":      policy,   # the per-line flagging policy used for this run
        "human_reviewed":  False,
        "requires_review": requires_review,
    }

    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(audit_record) + "\n")

    print("[OK] Output written")
    print("     Commentary: {}".format(output_path))
    print("     Audit log:  {}".format(AUDIT_LOG))
    print("     Input hash: {}...".format(input_hash[:30]))
    print("     Requires human review: {}".format(requires_review))
    if requires_review:
        print("     Reason: {} flag(s) raised".format(len(flags)))

    return output_path

def update_audit_pdf(pdf_path):
    """
    Update the most recent audit log record with the PDF output path.

    Called by write_pdf() after the PDF is successfully created.
    Reads the last line of audit_log.jsonl, adds the pdf_file field,
    and rewrites that line in place.

    Finance context: The audit trail must record both outputs — the text
    commentary and the PDF report — so any output can be traced to the
    exact run that produced it.
    """
    if not AUDIT_LOG.exists():
        return

    lines = AUDIT_LOG.read_text(encoding="utf-8").strip().split("\n")
    if not lines or not lines[-1].strip():
        return

    last_record           = json.loads(lines[-1])
    last_record["pdf_file"] = str(pdf_path)
    lines[-1]             = json.dumps(last_record)

    AUDIT_LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")

# =============================================================================
# FUNCTION 2: Build the PDF as bytes (shared), then write it (CLI)
# =============================================================================
def build_pdf_bytes(commentary, df, flags, tok_in, tok_out, period, entity,
                    ts_log, policy_note_text=None, df_12mo=None):
    """Build the A4 PDF and return it as bytes. One layout, two sinks: the CLI
    write_pdf writes these bytes to disk; the web serves them from a download
    button. No file is written here.

    commentary is dash-normalised (the same text shown on screen). period, entity
    and ts_log identify the run on the cover. policy_note_text, when given, adds a
    one-line flagging-policy note under DATA FLAGS for provenance parity with the
    screen."""
    commentary = _normalise_dashes(commentary)
    sections = parse_sections(commentary)
    story = []

    # 1. Cover
    story.append(_cover_block(period, entity, ts_log, tok_in, tok_out, len(flags)))
    story.append(Spacer(1, 0.4 * cm))

    # 2. Executive Summary
    story.append(_section_header("EXECUTIVE SUMMARY"))
    story.append(Spacer(1, 0.2 * cm))
    if sections["executive_summary"]:
        story.append(Paragraph(
            _esc(sections["executive_summary"].replace("\n", " ")), S_BODY))
    else:
        story.append(Paragraph("No executive summary available.", S_META))
    story.append(Spacer(1, 0.35 * cm))

    # 3. Variance Summary Table
    story.append(_section_header("VARIANCE SUMMARY"))
    story.append(Spacer(1, 0.2 * cm))
    story.append(_variance_table(df))
    story.append(Spacer(1, 0.35 * cm))

    # 3b. Twelve-month trend (Revenue by default; needs the full-year data). The
    # single-period table shows one month; this gives that month its context.
    if df_12mo is not None:
        from src.trend_chart import build_trend_chart
        import matplotlib.pyplot as _plt
        story.append(_section_header("12-MONTH TREND"))
        story.append(Spacer(1, 0.2 * cm))
        _fig = build_trend_chart(df_12mo, "Revenue")
        _imgbuf = BytesIO()
        _fig.savefig(_imgbuf, format="png", dpi=150)
        _plt.close(_fig)
        _imgbuf.seek(0)
        _iw, _ih = ImageReader(_imgbuf).getSize()
        _imgbuf.seek(0)
        story.append(Image(_imgbuf, width=PAGE_W, height=PAGE_W * _ih / _iw))
        story.append(Spacer(1, 0.35 * cm))

    # 4. Line Item Commentary
    story.append(_section_header("LINE ITEM COMMENTARY"))
    story.append(Spacer(1, 0.2 * cm))
    if sections["line_items"]:
        raw_lines = [line.strip()
                     for line in sections["line_items"].split("\n")
                     if line.strip()]
        for line in raw_lines:
            if line.startswith("---") or line.startswith("##") or line == "--":
                continue
            label, body = extract_label(line)
            if label is None:
                story.append(Paragraph(_esc(line), S_BODY))
                continue
            if "[FLAG:" in body:
                severity = "warning" if "LARGE_VARIANCE" in body else "error"
                story.append(Spacer(1, 0.1 * cm))
                story.append(KeepTogether([
                    Paragraph(
                        '<font color="#2D6A9F"><b>{}</b></font>'.format(_esc(label)),
                        ParagraphStyle("FLL", fontName="Helvetica-Bold",
                            fontSize=10, textColor=MID_BLUE,
                            leading=14, spaceBefore=4)),
                    _flag_inline(body, severity),
                ]))
            else:
                story.append(Spacer(1, 0.1 * cm))
                story.append(_line_item(label, body))
    story.append(Spacer(1, 0.35 * cm))

    # 5. Data Flags
    story.append(_section_header("DATA FLAGS"))
    story.append(Spacer(1, 0.2 * cm))
    story.append(_flag_summary_table(flags))

    # Provenance: the flagging policy this run used (parity with the screen).
    if policy_note_text:
        story.append(Spacer(1, 0.15 * cm))
        story.append(Paragraph(_esc(policy_note_text), S_META))
    story.append(Spacer(1, 0.4 * cm))

    # 6. Footer
    story.append(HRFlowable(width="100%", thickness=0.5, color=RULE_COLOR))
    story.append(Spacer(1, 0.15 * cm))
    story.append(Paragraph(
        "AI Variance Commentary Engine  ·  {}  ·  {}  ·  "
        "Human review: {}".format(
            MODEL, ts_log[:10],
            "Required - {} flag(s) raised".format(len(flags)) if flags
            else "Not required"),
        S_META))

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        rightMargin=2 * cm, leftMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
        title="Variance Commentary - {}".format(period),
        author="AI Variance Commentary Engine")
    doc.build(story)
    return buf.getvalue()


# =============================================================================
# FUNCTION 3: Write the PDF to a file (CLI: build bytes -> write)
# =============================================================================
def write_pdf(commentary, df, flags, tok_in, tok_out, df_12mo=None):
    """Format the commentary into a professional A4 PDF file. Builds the bytes
    with build_pdf_bytes (shared with the web) and writes them to a timestamped
    path. Returns pdf_path."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    now     = datetime.now(timezone.utc)
    ts_file = now.strftime("%Y-%m-%d_%H-%M-%S")
    ts_log  = now.isoformat()

    pdf_path = OUTPUT_DIR / "variance_commentary_{}.pdf".format(ts_file)

    pdf_bytes = build_pdf_bytes(
        commentary, df, flags, tok_in, tok_out,
        DEFAULT_PERIOD, DEFAULT_ENTITY, ts_log, policy_note_text=None,
        df_12mo=df_12mo)
    pdf_path.write_bytes(pdf_bytes)

    update_audit_pdf(pdf_path)

    print("[OK] PDF written")
    print("     PDF:  {}".format(pdf_path))
    print("     Size: {:.1f} KB".format(pdf_path.stat().st_size / 1024))
    return pdf_path
# =============================================================================
# lib/flow_diagram.py: a flow of stages in HTML and CSS, readable on a phone
# =============================================================================
# One renderer and its CSS for the flow diagrams of the series. A diagram is an
# ordered list of stages: in a window 640 px wide or more, a row of boxes with an
# arrow between each; below that, one box under another with a down arrow
# between them. The row also needs 600 px for the diagram itself (a 640 px window
# gives it 608): where an open sidebar leaves less, the stages stay stacked
# rather than break words. The text wraps inside its box, so it keeps its size
# at any width, and the page keeps no fixed-height frame.
#
# The words, the order and the colours all come from the caller: this module
# holds none of an app's own words, so the same file serves every app byte for
# byte. Each box takes its role's colours (border, title and foot in the
# stroke, the box in the fill). An optional boundary between two stages marks
# where one zone ends and the next begins, with a label for each zone, in both
# layouts. The list's accessible name says what the diagram shows.
# =============================================================================

from dataclasses import dataclass
from html import escape
from urllib.parse import quote

BREAKPOINT = 640      # px of window width: a row from here up, stacked below
ROW_MIN = 600         # px the diagram itself needs for a row of boxes


@dataclass(frozen=True)
class Role:
    """The colours of one kind of stage: the stroke for its border, title and
    foot, and the fill for its box."""
    stroke: str
    fill: str


@dataclass(frozen=True)
class Stage:
    """One box: a title, a line of text, and a foot that says who owns the
    stage. An empty text or foot is left out."""
    title: str
    text: str
    foot: str
    role: Role


@dataclass(frozen=True)
class Boundary:
    """Where one zone ends and the next begins: just before stage `index`.
    `before` names the zone up to there and `after` the zone from there."""
    index: int
    before: str
    after: str


def _span(cls, words, colour=""):
    style = f' style="color:{colour}"' if colour else ""
    return f'<span class="{cls}"{style}>{escape(words)}</span>'


def flow_html(label, stages, *, heading="", note="", key=(), boundary=None):
    """The diagram as one line of HTML, for st.markdown(unsafe_allow_html=True).

    `label` is the accessible name of the list of stages; `heading` is the line
    above the boxes and `note` the line below them; `key` is the colour key, as
    (role, words) pairs; `boundary` is an optional Boundary."""
    if boundary is not None and not 0 < boundary.index < len(stages):
        raise ValueError("a boundary sits between two stages")
    items = []
    for i, stage in enumerate(stages):
        cls, parts = "fd-stage", []
        if boundary is not None and i == 0:
            parts.append(_span("fd-zone", boundary.before))
        if boundary is not None and i == boundary.index:
            cls = "fd-stage fd-cross"
            parts.append(_span("fd-zone", boundary.after))
        parts.append(_span("fd-title", stage.title, stage.role.stroke))
        if stage.text:
            parts.append(_span("fd-text", stage.text))
        if stage.foot:
            parts.append(_span("fd-foot", stage.foot, stage.role.stroke))
        style = f"border-color:{stage.role.stroke};background:{stage.role.fill}"
        items.append(f'<li class="{cls}" style="{style}">{" ".join(parts)}</li>')
    zoned = " fd-zoned" if boundary is not None else ""
    out = ['<figure class="fd">']
    if heading:
        out.append(f'<p class="fd-head">{escape(heading)}</p>')
    out.append(f'<ol class="fd-flow{zoned}" aria-label="{escape(label)}">'
               f'{"".join(items)}</ol>')
    if note:
        out.append(f'<p class="fd-note">{escape(note)}</p>')
    if key:
        swatches = "".join(
            f'<li><span class="fd-swatch" aria-hidden="true" style="border-color:'
            f'{role.stroke};background:{role.fill}"></span> {escape(words)}</li>'
            for role, words in key)
        out.append(f'<ul class="fd-key">{swatches}</ul>')
    out.append("</figure>")
    return "".join(out)


def _chevron(colour, down):
    """An arrow head as a CSS image, pointing right or down."""
    box, path = ("0 0 10 8", "M1 1L5 7L9 1") if down else ("0 0 8 10", "M1 1L7 5L1 9")
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='{box}'>"
           f"<path d='{path}' fill='none' stroke='{colour}' stroke-width='1.6' "
           f"stroke-linecap='round' stroke-linejoin='round'/></svg>")
    return f'url("data:image/svg+xml,{quote(svg, safe="")}")'


def flow_css(ink, muted, rule):
    """The CSS for flow_html, for the app's inject_css(). `ink` is the text
    colour, `muted` the arrows and the quiet lines, `rule` the dashed lines."""
    line = f"linear-gradient({muted}, {muted})"
    down, right = _chevron(muted, True), _chevron(muted, False)
    return f"""
      /* Flow diagrams (lib/flow_diagram.py): one box under another on a
         phone, a row of boxes from {BREAKPOINT} px */
      figure.fd {{ container: fd / inline-size; margin: 4px 0 20px; padding: 0; }}
      .fd p.fd-head {{
        margin: 0 0 14px; text-align: center; font-size: 15px; font-weight: 600;
        line-height: 1.4; color: {ink};
      }}
      .fd ol.fd-flow {{
        list-style: none; margin: 0; padding: 0;
        display: flex; flex-direction: column;
      }}
      .fd ol.fd-flow.fd-zoned {{ padding-top: 24px; }}
      .fd ol.fd-flow > li.fd-stage {{
        position: relative; display: flex; flex-direction: column; min-width: 0;
        margin: 0; padding: 10px 12px; border: 1px solid; border-radius: 12px;
        text-align: center; color: {ink}; line-height: 1.35;
        overflow-wrap: break-word;
      }}
      .fd ol.fd-flow > li.fd-stage + li.fd-stage {{ margin-top: 30px; }}
      .fd ol.fd-flow > li.fd-stage + li.fd-stage::before {{
        content: ""; position: absolute; left: 50%; bottom: 100%;
        width: 10px; height: 31px; margin: 0 0 0 -5px;
        background: {down} center bottom 2px / 10px 8px no-repeat,
                    {line} center top / 1.6px calc(100% - 4px) no-repeat;
      }}
      .fd ol.fd-flow > li.fd-stage + li.fd-cross {{ margin-top: 58px; }}
      .fd ol.fd-flow > li.fd-stage + li.fd-cross::before {{ height: 59px; }}
      .fd ol.fd-flow > li.fd-cross::after {{
        content: ""; position: absolute; left: -1px; right: -1px; top: -36px;
        border-top: 1.2px dashed {rule};
      }}
      .fd .fd-zone {{
        position: absolute; left: -1px; bottom: 100%; margin-bottom: 4px;
        font-size: 13px; line-height: 1.3; color: {muted}; white-space: nowrap;
        text-align: left;
      }}
      .fd .fd-title {{
        font-size: 14px; font-weight: 700; letter-spacing: 0.03em; line-height: 1.3;
      }}
      .fd .fd-text {{ margin-top: 4px; font-size: 15px; color: {ink}; }}
      .fd .fd-foot {{
        margin-top: auto; padding-top: 6px; font-size: 13px; font-style: italic;
      }}
      .fd p.fd-note {{
        margin: 16px 0 0; padding-top: 10px; border-top: 1px dashed {rule};
        text-align: center; font-size: 13px; line-height: 1.45; color: {muted};
      }}
      .fd ul.fd-key {{
        list-style: none; margin: 8px 0 0; padding: 0;
        display: flex; flex-wrap: wrap; justify-content: center; gap: 4px 18px;
        font-size: 13px; line-height: 1.4; color: {ink};
      }}
      .fd ul.fd-key li {{
        display: flex; align-items: center; gap: 6px; margin: 0; padding: 0;
        font-size: 13px;
      }}
      .fd .fd-swatch {{
        flex: none; width: 11px; height: 11px; border: 1px solid; border-radius: 2px;
      }}
      @media (min-width: {BREAKPOINT}px) {{ @container fd (min-width: {ROW_MIN}px) {{
        .fd ol.fd-flow {{ flex-direction: row; align-items: stretch; }}
        .fd ol.fd-flow > li.fd-stage {{ flex: 1 1 0; padding: 12px 6px; }}
        .fd ol.fd-flow > li.fd-stage + li.fd-stage {{ margin: 0 0 0 22px; }}
        .fd ol.fd-flow > li.fd-stage + li.fd-stage::before {{
          left: auto; right: 100%; bottom: auto; top: 50%;
          width: 22px; height: 10px; margin: -5px 0 0;
          background: {right} right 2px center / 8px 10px no-repeat,
                      {line} left 1px center / calc(100% - 5px) 1.6px no-repeat;
        }}
        .fd ol.fd-flow > li.fd-cross::after {{
          left: -12px; right: auto; top: -24px; bottom: -1px;
          border-top: 0; border-left: 1.2px dashed {rule};
        }}
        .fd .fd-title {{ font-size: 13px; letter-spacing: 0.02em; }}
        .fd .fd-text {{ font-size: 14px; }}
      }} }}
"""

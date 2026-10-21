# =============================================================================
# lib/theme.py : one visual identity, shared with the PDF
# =============================================================================
# The exact palette the PDFs already use (step6_explainer), so the web app and
# the report it produces read as a single product. Status is shown by two
# chips, amber DRAFT and green FINAL; every page banner is the navy band.
#
# Typography: Source Serif 4 for headings (institutional authority) and Inter
# for body, UI, and data (screen-first, with tabular figures so numbers align
# in tables). Both are free Google Fonts, loaded by CSS import.
# =============================================================================

# Core palette — identical to the PDF (step6_explainer.py)
DARK_BLUE  = "#1A3A5C"
MID_BLUE   = "#2D6A9F"
LIGHT_BLUE = "#EAF2FB"
GREEN      = "#1D6B0F"
AMBER      = "#854F0B"
AMBER_BG   = "#FAEEDA"
FLAG_RED   = "#A32D2D"
BODY_DARK  = "#1A1A19"
MUTED      = "#898781"
RULE       = "#D3D1C7"
NEAR_WHITE = "#FBFAF7"

# Status chips: amber DRAFT and green FINAL, the series' sign-off colours (as
# Project 6's screen and PDF use them)
DRAFT_CHIP = "#B45F06"
FINAL_CHIP = "#2E6B3F"

# Font families (referenced in CSS and available to the SVG diagram)
SERIF = "'Source Serif 4', Georgia, 'Times New Roman', serif"
SANS  = "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"


def inject_css():
    """Return the app's CSS, including the font imports. Kept in one place so
    every page is consistent. The boldness is spent on the governance UI and
    the type pairing, not on chrome."""
    return f"""
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600;8..60,700&display=swap');

      /* Body, UI, and data: Inter */
      html, body, [class*="css"], .stMarkdown, .stText, p, span, div, label,
      input, button, table, td, th {{
        font-family: {SANS};
        font-feature-settings: "cv05" 1;
      }}

      /* Tabular figures only where numbers line up: tables, metrics, figures */
      table, table *, [data-testid="stMetricValue"], [data-testid="stMetricValue"] *,
      [data-testid="stMetricDelta"], [data-testid="stMetricDelta"] * {{
        font-feature-settings: "tnum" 1, "cv05" 1;
      }}

      /* Headings: Source Serif 4 for institutional authority */
      h1, h2, h3, h4 {{
        font-family: {SERIF};
        color: {DARK_BLUE};
        letter-spacing: -0.01em;
        font-weight: 600;
      }}

      /* The app header band */
      .sc-header {{
        background: {DARK_BLUE};
        color: white;
        padding: 22px 26px;
        border-radius: 10px;
        margin-bottom: 8px;
      }}
      .sc-header h1 {{
        font-family: {SERIF};
        color: white; margin: 0; font-size: 1.7rem; font-weight: 700;
        letter-spacing: -0.02em;
      }}
      .sc-header p  {{
        font-family: {SANS};
        color: #AACCEE; margin: 6px 0 0; font-size: 0.92rem; font-weight: 400;
      }}

      /* Status chip: amber DRAFT, green FINAL */
      .sc-status {{
        display: inline-block;
        padding: 3px 10px;
        border-radius: 4px;
        font-size: 0.74rem;
        font-weight: 700;
        letter-spacing: 0.06em;
        color: white;
      }}
      .sc-status.draft {{ background: {DRAFT_CHIP}; }}
      .sc-status.final {{ background: {FINAL_CHIP}; }}

      /* Page links wrap rather than clip on a phone */
      [data-testid="stPageLink-NavLink"], [data-testid="stPageLink-NavLink"] * {{
        white-space: normal !important; height: auto !important;
      }}

      /* Honest key-disclosure note */
      .sc-keynote {{
        font-size: 0.8rem;
        color: {MUTED};
        border-left: 2px solid {RULE};
        padding-left: 10px;
        margin-top: 6px;
        font-family: {SANS};
      }}
    </style>
    """


def header_html(title, subtitle):
    """The page banner: the series navy band with the page's name and one line."""
    import html
    return (f'<div class="sc-header"><h1>{html.escape(title)}</h1>'
            f'<p>{html.escape(subtitle)}</p></div>')


def status_chip_html(status):
    """The DRAFT or FINAL chip. Anything but "final" reads DRAFT."""
    label = "FINAL" if status == "final" else "DRAFT"
    return f'<span class="sc-status {label.lower()}">{label}</span>'

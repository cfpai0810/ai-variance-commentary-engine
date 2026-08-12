# =============================================================================
# lib/pipeline_flow.py - the pipeline diagram (matches governance_flow's language)
# =============================================================================
# One SVG, same visual grammar as governance_flow.py: purple = the model (used
# only for language, never numbers), green = deterministic engine, blue = data.
# Inter font, theme palette. Shows the AI boundary: the model appears in exactly
# ONE of five stages; everything numeric is deterministic. Pure function so any
# page can render it and it stays consistent.
# =============================================================================


def pipeline_flow_svg():
    """Return the pipeline diagram as an inline SVG string."""
    return """<svg viewBox="0 0 882 250" width="100%" role="img"
     xmlns="http://www.w3.org/2000/svg"
     aria-label="The pipeline: a deterministic loader reads the profit-and-loss
     data and scopes it to the chosen period; a deterministic validator checks
     every line for the five flag conditions and applies the per-line thresholds;
     a deterministic calculator computes the variances and leaves flagged lines
     uncomputed; the model reads the computed figures and writes the commentary;
     and a deterministic output layer writes the PDF, the data hash, and the audit
     record. Only the commentary stage uses the model; everything numeric is
     deterministic.">
  <defs>
    <marker id="pl-arrow" viewBox="0 0 10 10" refX="8" refY="5"
            markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M2 1 L8 5 L2 9" fill="none" stroke="#898781"
            stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
    </marker>
  </defs>

  <text x="441.0" y="30" text-anchor="middle" font-family="'Inter', sans-serif"
        font-size="13" font-weight="600" fill="#1A3A5C">
    The model appears in one stage only. Everything numeric is deterministic.
  </text>


  <g>
    <rect x="14" y="70" width="150" height="108" rx="12"
          fill="#EAF2FB" stroke="#1A3A5C" stroke-width="1.1"/>
    <text x="89.0" y="98" text-anchor="middle" font-family="'Inter', sans-serif"
          font-size="12.5" font-weight="700" fill="#1A3A5C" letter-spacing="0.03em">Load</text>
    <text x="89.0" y="122" text-anchor="middle" font-family="'Inter', sans-serif"
          font-size="11" fill="#1A3A5C">read P&amp;L,</text>
    <text x="89.0" y="138" text-anchor="middle" font-family="'Inter', sans-serif"
          font-size="11" fill="#1A3A5C">scope to month</text>
    <text x="89.0" y="165" text-anchor="middle" font-family="'Inter', sans-serif"
          font-size="9.5" font-style="italic" fill="#1A3A5C">deterministic</text>
  </g><line x1="164" y1="124.0" x2="190" y2="124.0" stroke="#898781" stroke-width="1.6" marker-end="url(#pl-arrow)"/>
  <g>
    <rect x="190" y="70" width="150" height="108" rx="12"
          fill="#E8F3E9" stroke="#1D6B0F" stroke-width="1.1"/>
    <text x="265.0" y="98" text-anchor="middle" font-family="'Inter', sans-serif"
          font-size="12.5" font-weight="700" fill="#1D6B0F" letter-spacing="0.03em">Validate</text>
    <text x="265.0" y="122" text-anchor="middle" font-family="'Inter', sans-serif"
          font-size="11" fill="#1A3A5C">five checks,</text>
    <text x="265.0" y="138" text-anchor="middle" font-family="'Inter', sans-serif"
          font-size="11" fill="#1A3A5C">thresholds</text>
    <text x="265.0" y="165" text-anchor="middle" font-family="'Inter', sans-serif"
          font-size="9.5" font-style="italic" fill="#1D6B0F">deterministic</text>
  </g><line x1="340" y1="124.0" x2="366" y2="124.0" stroke="#898781" stroke-width="1.6" marker-end="url(#pl-arrow)"/>
  <g>
    <rect x="366" y="70" width="150" height="108" rx="12"
          fill="#E8F3E9" stroke="#1D6B0F" stroke-width="1.1"/>
    <text x="441.0" y="98" text-anchor="middle" font-family="'Inter', sans-serif"
          font-size="12.5" font-weight="700" fill="#1D6B0F" letter-spacing="0.03em">Compute</text>
    <text x="441.0" y="122" text-anchor="middle" font-family="'Inter', sans-serif"
          font-size="11" fill="#1A3A5C">variances,</text>
    <text x="441.0" y="138" text-anchor="middle" font-family="'Inter', sans-serif"
          font-size="11" fill="#1A3A5C">skip flagged</text>
    <text x="441.0" y="165" text-anchor="middle" font-family="'Inter', sans-serif"
          font-size="9.5" font-style="italic" fill="#1D6B0F">deterministic</text>
  </g><line x1="516" y1="124.0" x2="542" y2="124.0" stroke="#898781" stroke-width="1.6" marker-end="url(#pl-arrow)"/>
  <g>
    <rect x="542" y="70" width="150" height="108" rx="12"
          fill="#F0ECF8" stroke="#6B4FA8" stroke-width="1.1"/>
    <text x="617.0" y="98" text-anchor="middle" font-family="'Inter', sans-serif"
          font-size="12.5" font-weight="700" fill="#6B4FA8" letter-spacing="0.03em">Commentary</text>
    <text x="617.0" y="122" text-anchor="middle" font-family="'Inter', sans-serif"
          font-size="11" fill="#1A3A5C">figures to</text>
    <text x="617.0" y="138" text-anchor="middle" font-family="'Inter', sans-serif"
          font-size="11" fill="#1A3A5C">words</text>
    <text x="617.0" y="165" text-anchor="middle" font-family="'Inter', sans-serif"
          font-size="9.5" font-style="italic" fill="#6B4FA8">model, language</text>
  </g><line x1="692" y1="124.0" x2="718" y2="124.0" stroke="#898781" stroke-width="1.6" marker-end="url(#pl-arrow)"/>
  <g>
    <rect x="718" y="70" width="150" height="108" rx="12"
          fill="#E8F3E9" stroke="#1D6B0F" stroke-width="1.1"/>
    <text x="793.0" y="98" text-anchor="middle" font-family="'Inter', sans-serif"
          font-size="12.5" font-weight="700" fill="#1D6B0F" letter-spacing="0.03em">Output</text>
    <text x="793.0" y="122" text-anchor="middle" font-family="'Inter', sans-serif"
          font-size="11" fill="#1A3A5C">PDF, hash,</text>
    <text x="793.0" y="138" text-anchor="middle" font-family="'Inter', sans-serif"
          font-size="11" fill="#1A3A5C">audit record</text>
    <text x="793.0" y="165" text-anchor="middle" font-family="'Inter', sans-serif"
          font-size="9.5" font-style="italic" fill="#1D6B0F">deterministic</text>
  </g>

  <line x1="14" y1="196" x2="868" y2="196" stroke="#D3D1C7"
        stroke-width="1" stroke-dasharray="3 4"/>
  <text x="441.0" y="218" text-anchor="middle" font-family="'Inter', sans-serif"
        font-size="10.5" fill="#898781">
    The commentary stage is handed already-final figures; the model has nothing
    to calculate with.
  </text>

  <g font-family="'Inter', sans-serif" font-size="11">
    <rect x="231.0" y="232" width="11" height="11" rx="2" fill="#F0ECF8" stroke="#6B4FA8"/>
    <text x="248.0" y="241" fill="#1A3A5C">Model, for language</text>
    <rect x="451.0" y="232" width="11" height="11" rx="2" fill="#E8F3E9" stroke="#1D6B0F"/>
    <text x="468.0" y="241" fill="#1A3A5C">Deterministic code, for numbers</text>
  </g>
</svg>"""

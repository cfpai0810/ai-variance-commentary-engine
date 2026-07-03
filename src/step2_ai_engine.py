# =============================================================================
# ai_engine.py — Layer 3: AI Prompt Engineering and API Calls
# =============================================================================
# Responsibilities:
#   - Build the system prompt and user prompt for every run
#   - Call the Claude API and return the response with token counts
#   - Handle all API error types with clear human-readable messages
#
# This layer knows about: Claude API, prompts, pandas DataFrames
# This layer does NOT know about: file paths, output files, audit logs
# =============================================================================

import anthropic
import pandas as pd

from config import (
    ANTHROPIC_API_KEY,
    MODEL,
    MAX_TOKENS,
    DEFAULT_PERIOD,
    DEFAULT_ENTITY,
)

# ── Initialise the Claude client once at module level ─────────────────────────
# Creating the client here means it is reused for every call in the session.
# Never recreate the client inside a function — it wastes time and memory.
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# =============================================================================
# FUNCTION 1: Build the system prompt and user prompt
# =============================================================================
def build_prompt(df, flags, period, entity):
    """
    Build the system prompt and user prompt for the Claude API call.

    Finance context: This is where you hand the brief to Claude.
    The system prompt is the standing contract — written once, reused
    every run. The user prompt is the variable layer — changes with
    each period's data.

    Anthropic best practice: data goes inside XML tags, query goes
    at the end. This improves response quality by up to 30% vs
    unstructured prompts.

    Args:
        df:     DataFrame with variance columns from calculate_variances()
        flags:  list of flag strings from validate_and_flag()
        period: reporting period string e.g. 'March 2026'
        entity: entity name string e.g. 'Valencia Operations'

    Returns:
        (system_prompt string, user_prompt string)
    """

    # Guard: use defaults if period or entity are empty
    if not period or not period.strip():
        period = DEFAULT_PERIOD
    if not entity or not entity.strip():
        entity = DEFAULT_ENTITY

    # =========================================================================
    # SYSTEM PROMPT — fixed contract, never changes between runs
    # Five mandatory sections: role, success criteria, constraints,
    # uncertainty handling, output format
    # =========================================================================
    system_prompt = (
        "You are a senior FP&A analyst at a European company, "
        "preparing management accounts commentary for the CFO and Board.\n\n"
        "<success_criteria>\n"
        "- Identify the specific department and account driving each variance\n"
        "- Use direction-aware language: favourable variances are framed as "
        "opportunities or achievements, unfavourable variances include a root cause "
        "and a recommended corrective action\n"
        "- Commentary is concise, professional, and CFO-ready — no filler phrases, "
        "no corporate jargon\n"
        "- Prior year comparisons are included where data is available\n"
        "- The tone is analytical and confident, not hedged or vague\n"
        "</success_criteria>\n\n"
        "<constraints>\n"
        "- NEVER invent, estimate, or extrapolate any number not present in the data\n"
        "- NEVER round figures differently from how they are provided\n"
        "- If a row is flagged, acknowledge the flag explicitly — do not write "
        "commentary as if the data is complete\n"
        "- All amounts are in EUR unless stated otherwise\n"
        "- Do not use phrases like 'it is worth noting' or 'it should be highlighted' "
        "— state the point directly\n"
        "</constraints>\n\n"
        "<uncertainty_handling>\n"
        "- If a data field is missing or flagged, write: "
        "[FLAG: reason] — e.g. [FLAG: Missing actual for Legal and Compliance]\n"
        "- Do not attempt to estimate or fill a missing value\n"
        "- If a variance is very large (>50%), note that it requires urgent CFO review\n"
        "</uncertainty_handling>\n\n"
        "<output_format>\n"
        "Produce output in exactly this structure — no deviation:\n\n"
        "EXECUTIVE SUMMARY\n"
        "[3 sentences maximum. Overall performance vs budget. "
        "Biggest positive driver. Biggest negative driver or risk.]\n\n"
        "LINE ITEM COMMENTARY\n"
        "[One paragraph per department. Format each paragraph as:]\n"
        "[Department — Account]: [2-3 sentences. Variance amount and %. "
        "Root cause or explanation. Prior year comparison if available. "
        "Recommended action if unfavourable.]\n\n"
        "DATA FLAGS\n"
        "[List each flag on its own line. If no flags, write: No flags raised.]\n"
        "</output_format>"
    )

    # =========================================================================
    # USER PROMPT — variable layer, rebuilt every run
    # Structure: context -> data (XML tags) -> flags -> query
    # Anthropic docs: put data before the query for best results
    # =========================================================================

    # Build the formatted data rows for injection into the prompt
    data_rows = []
    for _, row in df.iterrows():
        dept = row["department"]
        acct = row["account"]

        # Format actual — handle missing value
        if pd.isna(row["actual"]):
            actual_str = "MISSING"
        else:
            actual_str = "€{:,.0f}".format(row["actual"])

        # Format budget — always present (validated in data_loader)
        budget_str = "€{:,.0f}".format(row["budget"])

        # Format variance columns — None means row was flagged and skipped
        if pd.notna(row["variance_abs"]) and pd.notna(row["variance_pct"]):
            var_str = "€{:+,.0f} ({:+.1%})".format(
                row["variance_abs"], row["variance_pct"]
            )
        else:
            var_str = "N/A — see flags"

        # Format prior year comparison
        if pd.notna(row["prior_year_pct"]):
            py_str = "{:+.1%} vs prior year".format(row["prior_year_pct"])
        else:
            py_str = "N/A"

        data_rows.append(
            "  {} | {} | Actual: {} | Budget: {} | Variance: {} | Prior Year: {}".format(
                dept, acct, actual_str, budget_str, var_str, py_str
            )
        )

    data_block = "\n".join(data_rows)

    # Build the flags block
    if flags:
        flags_block = "\n".join("  - {}".format(flag) for flag in flags)
    else:
        flags_block = "  No flags raised."

    # Assemble the full user prompt
    user_prompt = (
        "REPORTING CONTEXT\n"
        "Period:  {}\n"
        "Entity:  {}\n"
        "Currency: EUR\n\n"
        "<financial_data>\n"
        "{}\n"
        "</financial_data>\n\n"
        "<data_flags>\n"
        "{}\n"
        "</data_flags>\n\n"
        "Using the financial data and flags above, produce the variance commentary "
        "in the exact output format specified."
    ).format(period, entity, data_block, flags_block)

    # Preview print
    print("\n[OK] Prompts built")
    print("     Period: {} | Entity: {}".format(period, entity))
    print("     Data rows injected: {}".format(len(data_rows)))
    print("     Flags in prompt: {}".format(len(flags)))

    return system_prompt, user_prompt


# =============================================================================
# FUNCTION 2: Call the Claude API
# =============================================================================
def call_claude(system_prompt, user_prompt):
    """
    Send the system and user prompts to Claude and return the response.

    Finance context: This is the equivalent of handing the formatted
    brief to an analyst and receiving the commentary back. We capture
    everything needed for the audit log: tokens and stop reason.

    Error handling covers every failure mode with clear messages:
    - AuthenticationError: API key wrong or missing — check .env
    - RateLimitError: too many requests — wait and retry
    - APIStatusError 5xx: server error — SDK retries 2x automatically
    - APIConnectionError: no internet connection
    - max_tokens stop_reason: response truncated — output may be incomplete

    Args:
        system_prompt: fixed contract prompt from build_prompt()
        user_prompt:   variable data prompt from build_prompt()

    Returns:
        (response_text, input_tokens, output_tokens, stop_reason)
        — always a tuple of (str, int, int, str), never None

    Raises:
        RuntimeError with clear human-readable message on any failure
    """
    print("\n[..] Calling Claude API ({})...".format(MODEL))

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_prompt}
            ]
        )

    except anthropic.AuthenticationError:
        raise RuntimeError(
            "Authentication failed. Check that your ANTHROPIC_API_KEY "
            "is set correctly in your .env file and starts with sk-ant-."
        )

    except anthropic.RateLimitError:
        raise RuntimeError(
            "Rate limit reached. Wait 60 seconds then run the script again. "
            "If this happens repeatedly, check your Anthropic usage dashboard."
        )

    except anthropic.APIStatusError as e:
        raise RuntimeError(
            "Anthropic API error after retries: {} — {}\n"
            "If this persists, report the error to Anthropic support.".format(
                e.status_code, e.message
            )
        )

    except anthropic.APIConnectionError:
        raise RuntimeError(
            "Could not connect to Anthropic API. "
            "Check your internet connection and try again."
        )

    # Guard against empty response content
    if not response.content:
        raise RuntimeError(
            "Claude returned an empty response with no content. "
            "Check your prompt and try again."
        )

    # Extract response values
    response_text = response.content[0].text
    input_tokens  = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    stop_reason   = response.stop_reason

    # Warn if response was truncated — output may be incomplete
    if stop_reason == "max_tokens":
        print(
            "[WARN] Response truncated at {} tokens. "
            "Consider increasing MAX_TOKENS in config.py.".format(MAX_TOKENS)
        )

    # Print summary — always runs regardless of stop_reason
    approx_cost = (input_tokens * 0.000003) + (output_tokens * 0.000015)

    print("[OK] Claude responded")
    print("     Stop reason:   {}".format(stop_reason))
    print("     Input tokens:  {:,}".format(input_tokens))
    print("     Output tokens: {:,}".format(output_tokens))
    print("     Approx cost:   €{:.4f}".format(approx_cost))

    return response_text, input_tokens, output_tokens, stop_reason
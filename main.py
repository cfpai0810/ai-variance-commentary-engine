# =============================================================================
# main.py - Orchestrator
# =============================================================================
#
# Run this file to execute the full pipeline:
#   python main.py
#
# Pipeline sequence:
#   config.py                    Layer 1: all configuration
#   src/step1_data_loader.py     Layer 2: load CSV, validate, calculate
#   src/step2_ai_engine.py       Layer 3: build prompts, call Claude API
#   src/step3_output_writer.py   Layer 4: write text, PDF, and audit log
#
# This file contains NO business logic.
# =============================================================================

from dotenv import load_dotenv
load_dotenv()

from src.step1_data_loader   import load_pnl, validate_and_flag, calculate_variances
from src.step2_ai_engine     import build_prompt, call_claude
from src.step3_output_writer import write_output, write_pdf
from config                  import SAMPLE_DATA, DEFAULT_PERIOD, DEFAULT_ENTITY, AUDIT_LOG


if __name__ == "__main__":

    # Layer 2 - Data
    df              = load_pnl(SAMPLE_DATA)
    df, flags       = validate_and_flag(df)
    df              = calculate_variances(df, flags)

    # Layer 3 - AI Engine
    system_p, user_p = build_prompt(df, flags, DEFAULT_PERIOD, DEFAULT_ENTITY)
    commentary, tok_in, tok_out, stop_reason = call_claude(system_p, user_p)

    # Layer 4 - Output
    txt_path = write_output(
        commentary, SAMPLE_DATA, flags, tok_in, tok_out, stop_reason,
        input_rows=len(df)
    )
    pdf_path = write_pdf(commentary, df, flags, tok_in, tok_out)

    print("\n[DONE] Pipeline complete.")
    print("       Text: {}".format(txt_path))
    print("       PDF:  {}".format(pdf_path))

    # ── Human review check — read back the audit record ───────────────────────
    # The requires_review flag is set when: flags raised, output truncated,
    # or output token count suspiciously low.
    # We read it back from the audit log rather than storing it in memory
    # so the warning reflects the actual persisted record.
    try:
        last_line   = open(AUDIT_LOG, encoding="utf-8").readlines()[-1]
        audit       = __import__("json").loads(last_line)
        if audit.get("requires_review"):
            print("\n" + "!" * 60)
            print("  HUMAN REVIEW REQUIRED")
            print("!" * 60)
            if audit.get("flags_raised"):
                print("  {} data flag(s) raised:".format(len(audit["flags_raised"])))
                for flag in audit["flags_raised"]:
                    print("    -> {}".format(flag))
            if audit.get("stop_reason") == "max_tokens":
                print("  Response was truncated — commentary may be incomplete.")
            if audit.get("output_tokens", 999) < 200:
                print("  Output token count unusually low — commentary may be incomplete.")
            print("  Review the commentary before presenting to the CFO or Board.")
            print("!" * 60)
        else:
            print("\n[OK] No human review required for this run.")
    except Exception:
        pass  # never let the warning block crash the pipeline
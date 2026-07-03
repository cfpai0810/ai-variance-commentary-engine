# =============================================================================
# main.py - Orchestrator
# Pass 2: four-layer architecture - all layers complete
# =============================================================================
#
# Pipeline sequence — follow the steps:
#
#   config.py                — Layer 1: all configuration and constants
#   step1_data_loader.py     — Layer 2: load CSV, validate, calculate variances
#   step2_ai_engine.py       — Layer 3: build prompts, call Claude API
#   step3_output_writer.py   — Layer 4: write output file and audit log
#
# This file contains NO business logic.
# It only imports from the four layers and calls them in order.
# =============================================================================

from dotenv import load_dotenv
load_dotenv()

from step1_data_loader   import load_pnl, validate_and_flag, calculate_variances
from step2_ai_engine     import build_prompt, call_claude
from step3_output_writer import write_output
from config              import SAMPLE_DATA, DEFAULT_PERIOD, DEFAULT_ENTITY


# =============================================================================
# MAIN - orchestrates the four layers in sequence
# =============================================================================
if __name__ == "__main__":

    # Step 1 - Data: load CSV, validate rows, calculate variances
    df              = load_pnl(SAMPLE_DATA)
    df, flags       = validate_and_flag(df)
    df              = calculate_variances(df, flags)

    # Step 2 - AI Engine: build prompts, call Claude API
    system_p, user_p = build_prompt(df, flags, DEFAULT_PERIOD, DEFAULT_ENTITY)
    commentary, tok_in, tok_out, stop_reason = call_claude(system_p, user_p)

    # Step 3 - Output: write commentary file and audit log
    output_path = write_output(
        commentary, SAMPLE_DATA, flags, tok_in, tok_out, stop_reason
    )

    print("\n[DONE] Pipeline complete.")
    print("       Text: {}".format(output_path))
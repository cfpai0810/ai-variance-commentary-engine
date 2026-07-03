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
#   src/step3_output_writer.py   Layer 4: write output and audit log
#
# This file contains NO business logic.
# It only imports from the four layers and calls them in sequence.
# =============================================================================

from dotenv import load_dotenv
load_dotenv()

from src.step1_data_loader   import load_pnl, validate_and_flag, calculate_variances
from src.step2_ai_engine     import build_prompt, call_claude
from src.step3_output_writer import write_output
from config                  import SAMPLE_DATA, DEFAULT_PERIOD, DEFAULT_ENTITY


if __name__ == "__main__":

    # Layer 2 - Data: load CSV, validate every row, calculate variances
    df              = load_pnl(SAMPLE_DATA)
    df, flags       = validate_and_flag(df)
    df              = calculate_variances(df, flags)

    # Layer 3 - AI Engine: build structured prompts, call Claude API
    system_p, user_p = build_prompt(df, flags, DEFAULT_PERIOD, DEFAULT_ENTITY)
    commentary, tok_in, tok_out, stop_reason = call_claude(system_p, user_p)

    # Layer 4 - Output: write commentary file, append audit log
    output_path = write_output(
        commentary, SAMPLE_DATA, flags, tok_in, tok_out, stop_reason
    )

    print("\n[DONE] Pipeline complete.")
    print("       Text: {}".format(output_path))
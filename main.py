# =============================================================================
# main.py - Orchestrator
# Pass 2: four-layer architecture - all layers complete
# =============================================================================
#
# This file contains NO business logic.
# It only imports from the four layers and calls them in order.
#
# Layer 1 - Config:        config.py
# Layer 2 - Data:          data_loader.py
# Layer 3 - AI Engine:     ai_engine.py
# Layer 4 - Output:        output_writer.py
# =============================================================================

from dotenv import load_dotenv
load_dotenv()

from data_loader   import load_pnl, validate_and_flag, calculate_variances
from ai_engine     import build_prompt, call_claude
from output_writer import write_output
from config        import SAMPLE_DATA, DEFAULT_PERIOD, DEFAULT_ENTITY


# =============================================================================
# MAIN - orchestrates the four layers in sequence
# =============================================================================
if __name__ == "__main__":

    # Layer 2 - Data: load, validate, calculate
    df              = load_pnl(SAMPLE_DATA)
    df, flags       = validate_and_flag(df)
    df              = calculate_variances(df, flags)

    # Layer 3 - AI Engine: build prompts, call Claude
    system_p, user_p = build_prompt(df, flags, DEFAULT_PERIOD, DEFAULT_ENTITY)
    commentary, tok_in, tok_out, stop_reason = call_claude(system_p, user_p)

    # Layer 4 - Output: write file and audit log
    output_path = write_output(
        commentary, SAMPLE_DATA, flags, tok_in, tok_out, stop_reason
    )

    print("\n[DONE] Pipeline complete.")
    print("       Text: {}".format(output_path))
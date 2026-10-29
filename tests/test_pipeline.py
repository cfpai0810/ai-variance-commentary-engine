# =============================================================================
# tests/test_pipeline.py : Project 1: AI Variance Commentary Engine
# =============================================================================
# Phase 5: VALIDATE — The 6-Case Test Protocol
#
# Run from the project root with (venv) active:
#   pytest tests/test_pipeline.py -v
#
# The six protocol cases from the methodology are the first six test classes:
#   1. Happy path          — clean data, full pipeline, audit log correct
#   2. Favourable variance — green dot for revenue over, cost under
#   3. Unfavourable variance — red dot for cost over, revenue under
#   4. Missing value       — Admin actual NaN, MISSING_ACTUAL flag, skipped
#   5. Zero actual         — Technology actual=0, ZERO_ACTUAL not LARGE_VARIANCE
#   6. Large variance      — Product +122.5%, LARGE_VARIANCE flag, skipped
#
# No real API calls are made. Where a test reaches the Claude call, a
# stand-in takes its place, so the tests need no key and cost nothing.
# =============================================================================

import json
import hashlib
import tempfile
import pytest
import pandas as pd

from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

# ── Path setup — tests run from the project root ──────────────────────────────
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))        # project root
sys.path.insert(0, str(Path(__file__).parent.parent / "src")) # src/ package

from src.step1_data_loader   import (
    load_pnl, filter_to_period, available_periods,
    validate_and_flag, calculate_variances,
)
from src.step3_output_writer import (
    get_status, clean_markdown, extract_label,
    parse_sections, write_output, write_pdf, _normalise_dashes,
    compute_requires_review, hash_input, build_pdf_bytes,
    GREEN, FLAG_RED, AMBER, MUTED,
)
from config import LARGE_VARIANCE_THRESHOLD, VARIANCE_THRESHOLDS
from src.trend_chart import build_trend_chart, trend_png_bytes
import matplotlib.pyplot as _plt
from streamlit_app.lib.policy import build_policy_from_ui, policy_note
from streamlit_app.lib.example_variance import load_example
from streamlit_app.lib.cost import estimate_cost, format_cost


# =============================================================================
# SHARED FIXTURES
# =============================================================================

@pytest.fixture
def tmp_dirs(tmp_path):
    """
    Provide a temporary output directory and audit log path.
    Patches OUTPUT_DIR and AUDIT_LOG in step3_output_writer so
    generated files go to a temp folder, not the real output/ folder.
    """
    out_dir = tmp_path / "output"
    audit   = out_dir / "audit_log.jsonl"
    out_dir.mkdir()
    with patch("src.step3_output_writer.OUTPUT_DIR", out_dir), \
         patch("src.step3_output_writer.AUDIT_LOG",  audit):
        yield out_dir, audit


@pytest.fixture
def sample_csv(tmp_path):
    """
    Write the standard 7-row sample CSV to a temp file and return the Path.
    Self-contained — does not depend on data/sample_pnl.csv on disk.
    """
    csv = tmp_path / "sample_pnl.csv"
    csv.write_text(
        "date,account,department,actual,budget,prior_year\n"
        "2026-03-31,Revenue,Sales,1250000,1100000,1050000\n"
        "2026-03-31,COGS,Operations,480000,420000,390000\n"
        "2026-03-31,Marketing Spend,Marketing,95000,80000,72000\n"
        "2026-03-31,Headcount Cost,HR,310000,320000,290000\n"
        "2026-03-31,IT Infrastructure,Technology,0,45000,0\n"
        "2026-03-31,Legal & Compliance,Admin,,25000,22000\n"
        "2026-03-31,R&D Expense,Product,890000,400000,180000\n",
        encoding="utf-8"
    )
    return csv


@pytest.fixture
def loaded_pipeline(sample_csv):
    """
    Run Steps 1-3 of the pipeline and return (df, flags).
    Used by multiple test cases to avoid duplicating setup code.

    Uses the config per-line policy (thresholds=None). Under that policy the
    March sample raises FOUR flags: Revenue now trips the 10% line threshold
    (+13.6%) alongside IT-zero, Legal-missing, and R&D +122.5%. Because a
    flagged row is skipped by calculate_variances, Sales/Revenue no longer has
    a computed variance here - see legacy_pipeline for the favourable-math checks.
    """
    df        = load_pnl(sample_csv)
    df, flags = validate_and_flag(df)
    df        = calculate_variances(df, flags)
    return df, flags


@pytest.fixture
def legacy_pipeline(sample_csv):
    """
    Same March sample under the OLD single-global behaviour (every line at 0.50).
    Reproduces pre-per-line flagging: three flags, Revenue NOT flagged, so
    Sales/Revenue keeps a computed variance. Used by the favourable-variance
    math tests and doubles as a backward-compatibility proof of the new
    thresholds parameter.
    """
    df        = load_pnl(sample_csv)
    df, flags = validate_and_flag(df, {"_default": 0.50})
    df        = calculate_variances(df, flags)
    return df, flags


@pytest.fixture
def mock_commentary():
    """
    Realistic commentary string in the format Claude returns.
    Used to test write_output() and write_pdf() without a real API call.
    """
    return (
        "EXECUTIVE SUMMARY\n"
        "Valencia Operations delivered revenue of EUR 1,250,000 in March 2026, "
        "exceeding budget by EUR 150,000 (+13.6%). The principal positive driver "
        "is Sales outperformance. Three flagged line items prevent a complete "
        "profitability assessment.\n\n"
        "LINE ITEM COMMENTARY\n"
        "Sales | Revenue: Revenue of EUR 1,250,000 exceeded budget by EUR 150,000 "
        "(+13.6%). Growth against prior year stands at +19.0%. No corrective "
        "action required.\n\n"
        "Operations | COGS: COGS of EUR 480,000 exceeded budget by EUR 60,000 "
        "(+14.3%). Year-on-year growth outpaces revenue growth. Operations to "
        "provide a unit cost breakdown.\n\n"
        "**Technology | IT Infrastructure:** [FLAG: ZERO_ACTUAL - Actual EUR 0 "
        "against budget EUR 45,000. Requires immediate clarification.]\n\n"
        "**Admin | Legal & Compliance:** [FLAG: MISSING_ACTUAL - No actual "
        "submitted against budget EUR 25,000.]\n\n"
        "**Product | R&D Expense:** [FLAG: LARGE_VARIANCE - Actual EUR 890,000 "
        "is EUR 490,000 above budget (+122.5%). Urgent CFO review required.]\n\n"
        "DATA FLAGS\n"
        "- ZERO_ACTUAL: Technology (budget was 45,000)\n"
        "- MISSING_ACTUAL: Admin\n"
        "- LARGE_VARIANCE: Product (+122.5% above budget)"
    )


# =============================================================================
# TEST CASE 1: Happy path
# =============================================================================

class TestHappyPath:

    def test_loads_seven_rows(self, sample_csv):
        df = load_pnl(sample_csv)
        assert len(df) == 7

    def test_correct_dtypes(self, sample_csv):
        df = load_pnl(sample_csv)
        assert str(df["actual"].dtype)     == "float64"
        assert str(df["budget"].dtype)     == "float64"
        assert str(df["prior_year"].dtype) == "float64"

    def test_all_required_columns_present(self, sample_csv):
        df = load_pnl(sample_csv)
        required = {"date", "account", "department", "actual", "budget", "prior_year"}
        assert required.issubset(set(df.columns))

    def test_raises_exactly_four_flags(self, loaded_pipeline):
        # Config per-line policy: March raises FOUR flags. Revenue (+13.6%) now
        # trips the 10% line threshold, on top of IT-zero, Legal-missing, and
        # R&D +122.5%. Was three under the old single 0.50 global.
        _, flags = loaded_pipeline
        assert len(flags) == 4

    def test_three_variances_calculated(self, loaded_pipeline):
        # Sales/Revenue is now flagged and therefore skipped, so three lines
        # (Operations, Marketing, HR) retain computed variances.
        df, _ = loaded_pipeline
        assert df["variance_abs"].notna().sum() == 3

    def test_four_rows_skipped(self, loaded_pipeline):
        df, _ = loaded_pipeline
        assert df["variance_abs"].isna().sum() == 4

    def test_text_file_created(self, sample_csv, loaded_pipeline, tmp_dirs, mock_commentary):
        out_dir, audit_log = tmp_dirs
        df, flags = loaded_pipeline
        path = write_output(mock_commentary, sample_csv, flags, 895, 1114, "end_turn")
        assert path.exists()
        assert path.stat().st_size > 100

    def test_text_file_contains_period(self, sample_csv, loaded_pipeline, tmp_dirs, mock_commentary):
        out_dir, audit_log = tmp_dirs
        df, flags = loaded_pipeline
        path = write_output(mock_commentary, sample_csv, flags, 895, 1114, "end_turn")
        content = path.read_text(encoding="utf-8")
        assert "March 2026"          in content
        assert "Valencia Operations" in content
        assert "claude-sonnet-4-6"   in content

    def test_audit_log_created(self, sample_csv, loaded_pipeline, tmp_dirs, mock_commentary):
        out_dir, audit_log = tmp_dirs
        df, flags = loaded_pipeline
        write_output(mock_commentary, sample_csv, flags, 895, 1114, "end_turn")
        assert audit_log.exists()

    def test_audit_record_fields(self, sample_csv, loaded_pipeline, tmp_dirs, mock_commentary):
        out_dir, audit_log = tmp_dirs
        df, flags = loaded_pipeline
        write_output(mock_commentary, sample_csv, flags, 895, 1114, "end_turn")
        record = json.loads(audit_log.read_text(encoding="utf-8").strip())
        assert "run_id"          in record
        assert "input_hash"      in record
        assert "output_file"     in record
        assert "flags_raised"    in record
        assert "human_reviewed"  in record
        assert "requires_review" in record
        assert record["input_hash"].startswith("sha256:")
        assert record["human_reviewed"]  is False
        assert record["requires_review"] is True
        assert record["input_tokens"]    == 895
        assert record["output_tokens"]   == 1114

    def test_pdf_created(self, sample_csv, loaded_pipeline, tmp_dirs, mock_commentary):
        out_dir, audit_log = tmp_dirs
        df, flags = loaded_pipeline
        path = write_pdf(mock_commentary, df, flags, 895, 1114)
        assert path.exists()
        assert path.stat().st_size > 3000


# =============================================================================
# TEST CASE 2: Favourable variance
# =============================================================================

class TestFavourableVariance:

    # Sales/Revenue is flagged under the config per-line policy (10% threshold),
    # so its variance is skipped there. These favourable-math checks use the
    # legacy 0.50-global policy, where Revenue is NOT flagged and keeps a
    # computed variance - which also proves the thresholds parameter recovers
    # the old behaviour.
    def test_sales_variance_abs(self, legacy_pipeline):
        df, _ = legacy_pipeline
        sales = df[df["department"] == "Sales"].iloc[0]
        assert sales["variance_abs"] == 150000.0

    def test_sales_variance_pct(self, legacy_pipeline):
        df, _ = legacy_pipeline
        sales = df[df["department"] == "Sales"].iloc[0]
        assert abs(sales["variance_pct"] - 0.136) < 0.001

    def test_sales_prior_year_pct(self, legacy_pipeline):
        df, _ = legacy_pipeline
        sales = df[df["department"] == "Sales"].iloc[0]
        assert abs(sales["prior_year_pct"] - 0.190) < 0.001

    def test_hr_variance_abs(self, loaded_pipeline):
        df, _ = loaded_pipeline
        hr = df[df["department"] == "HR"].iloc[0]
        assert hr["variance_abs"] == -10000.0

    def test_hr_variance_pct(self, loaded_pipeline):
        df, _ = loaded_pipeline
        hr = df[df["department"] == "HR"].iloc[0]
        assert abs(hr["variance_pct"] - (-0.031)) < 0.001

    def test_revenue_over_budget_is_green_dot(self):
        symbol, colour, _ = get_status("Revenue", +150000)
        assert symbol == "\u25cf"
        assert colour == GREEN

    def test_cost_under_budget_is_green_dot(self):
        symbol, colour, _ = get_status("Headcount Cost", -10000)
        assert symbol == "\u25cf"
        assert colour == GREEN

    def test_zero_variance_is_en_dash(self):
        symbol, colour, _ = get_status("Revenue", 0)
        assert symbol == "\u2013"
        assert colour == MUTED


# =============================================================================
# TEST CASE 3: Unfavourable variance
# =============================================================================

class TestUnfavourableVariance:

    def test_operations_variance_abs(self, loaded_pipeline):
        df, _ = loaded_pipeline
        ops = df[df["department"] == "Operations"].iloc[0]
        assert ops["variance_abs"] == 60000.0

    def test_operations_variance_pct(self, loaded_pipeline):
        df, _ = loaded_pipeline
        ops = df[df["department"] == "Operations"].iloc[0]
        assert abs(ops["variance_pct"] - 0.143) < 0.001

    def test_marketing_variance_abs(self, loaded_pipeline):
        df, _ = loaded_pipeline
        mkt = df[df["department"] == "Marketing"].iloc[0]
        assert mkt["variance_abs"] == 15000.0

    def test_cost_over_budget_is_red_dot(self):
        symbol, colour, _ = get_status("COGS", +60000)
        assert symbol == "\u25cf"
        assert colour == FLAG_RED

    def test_marketing_cost_over_budget_is_red_dot(self):
        symbol, colour, _ = get_status("Marketing Spend", +15000)
        assert symbol == "\u25cf"
        assert colour == FLAG_RED

    def test_revenue_under_budget_is_red_dot(self):
        symbol, colour, _ = get_status("Revenue", -50000)
        assert symbol == "\u25cf"
        assert colour == FLAG_RED


# =============================================================================
# TEST CASE 4: Missing value — Admin actual is NaN
# =============================================================================

class TestMissingValue:

    def test_admin_actual_is_nan_after_load(self, sample_csv):
        df = load_pnl(sample_csv)
        admin = df[df["department"] == "Admin"].iloc[0]
        assert pd.isna(admin["actual"])

    def test_admin_actual_is_not_zero(self, sample_csv):
        df = load_pnl(sample_csv)
        admin = df[df["department"] == "Admin"].iloc[0]
        assert admin["actual"] != 0.0

    def test_missing_actual_flag_raised(self, sample_csv):
        df = load_pnl(sample_csv)
        _, flags = validate_and_flag(df)
        admin_flags = [f for f in flags if "MISSING_ACTUAL" in f and "Admin" in f]
        assert len(admin_flags) == 1

    def test_admin_variance_skipped(self, loaded_pipeline):
        df, _ = loaded_pipeline
        admin = df[df["department"] == "Admin"].iloc[0]
        assert pd.isna(admin["variance_abs"])
        assert pd.isna(admin["variance_pct"])

    def test_missing_actual_in_audit_record(
            self, sample_csv, loaded_pipeline, tmp_dirs, mock_commentary):
        out_dir, audit_log = tmp_dirs
        df, flags = loaded_pipeline
        write_output(mock_commentary, sample_csv, flags, 895, 1114, "end_turn")
        record = json.loads(audit_log.read_text(encoding="utf-8").strip())
        assert any("MISSING_ACTUAL" in f for f in record["flags_raised"])

    def test_missing_actual_status_is_amber_triangle(self):
        symbol, colour, _ = get_status("Legal & Compliance", None)
        assert symbol == "\u25b3"
        assert colour == AMBER


# =============================================================================
# TEST CASE 5: Zero actual — Technology actual = 0.0
# =============================================================================

class TestZeroActual:

    def test_technology_actual_is_zero_not_nan(self, sample_csv):
        df = load_pnl(sample_csv)
        tech = df[df["department"] == "Technology"].iloc[0]
        assert tech["actual"] == 0.0
        assert not pd.isna(tech["actual"])

    def test_zero_actual_flag_raised(self, sample_csv):
        df = load_pnl(sample_csv)
        _, flags = validate_and_flag(df)
        zero_flags = [f for f in flags if "ZERO_ACTUAL" in f and "Technology" in f]
        assert len(zero_flags) == 1

    def test_large_variance_not_raised_for_technology(self, sample_csv):
        df = load_pnl(sample_csv)
        _, flags = validate_and_flag(df)
        large_flags = [f for f in flags if "LARGE_VARIANCE" in f and "Technology" in f]
        assert len(large_flags) == 0

    def test_technology_variance_skipped(self, loaded_pipeline):
        df, _ = loaded_pipeline
        tech = df[df["department"] == "Technology"].iloc[0]
        assert pd.isna(tech["variance_abs"])

    def test_zero_actual_status_is_amber_triangle(self):
        symbol, colour, _ = get_status("IT Infrastructure", None)
        assert symbol == "\u25b3"
        assert colour == AMBER

    def test_zero_actual_flag_contains_budget(self, sample_csv):
        df = load_pnl(sample_csv)
        _, flags = validate_and_flag(df)
        tech_flag = next(f for f in flags if "ZERO_ACTUAL" in f and "Technology" in f)
        assert "45,000" in tech_flag


# =============================================================================
# TEST CASE 6: Large variance — Product R&D +122.5%
# =============================================================================

class TestLargeVariance:

    def test_product_actual_and_budget(self, sample_csv):
        df = load_pnl(sample_csv)
        prod = df[df["department"] == "Product"].iloc[0]
        assert prod["actual"] == 890000.0
        assert prod["budget"] == 400000.0

    def test_product_variance_exceeds_threshold(self):
        actual, budget = 890000.0, 400000.0
        variance_pct = (actual - budget) / budget
        assert abs(variance_pct - 1.225) < 0.001
        assert variance_pct > LARGE_VARIANCE_THRESHOLD

    def test_large_variance_flag_raised(self, sample_csv):
        df = load_pnl(sample_csv)
        _, flags = validate_and_flag(df)
        large_flags = [f for f in flags if "LARGE_VARIANCE" in f and "Product" in f]
        assert len(large_flags) == 1

    def test_large_variance_flag_contains_percentage(self, sample_csv):
        df = load_pnl(sample_csv)
        _, flags = validate_and_flag(df)
        prod_flag = next(f for f in flags if "LARGE_VARIANCE" in f and "Product" in f)
        assert "+122.5%" in prod_flag

    def test_product_variance_skipped(self, loaded_pipeline):
        df, _ = loaded_pipeline
        prod = df[df["department"] == "Product"].iloc[0]
        assert pd.isna(prod["variance_abs"])
        assert pd.isna(prod["variance_pct"])

    def test_large_variance_in_audit_record(
            self, sample_csv, loaded_pipeline, tmp_dirs, mock_commentary):
        out_dir, audit_log = tmp_dirs
        df, flags = loaded_pipeline
        write_output(mock_commentary, sample_csv, flags, 895, 1114, "end_turn")
        record = json.loads(audit_log.read_text(encoding="utf-8").strip())
        assert any("LARGE_VARIANCE" in f for f in record["flags_raised"])

    def test_large_variance_requires_review(
            self, sample_csv, loaded_pipeline, tmp_dirs, mock_commentary):
        out_dir, audit_log = tmp_dirs
        df, flags = loaded_pipeline
        write_output(mock_commentary, sample_csv, flags, 895, 1114, "end_turn")
        record = json.loads(audit_log.read_text(encoding="utf-8").strip())
        assert record["requires_review"] is True


# =============================================================================
# PER-LINE VARIANCE THRESHOLDS
# =============================================================================

class TestPerLineThresholds:

    def test_config_policy_raises_revenue_and_rnd_flags(self, sample_csv):
        # thresholds=None -> config policy. March: four flags including the
        # Revenue LARGE_VARIANCE (10% line) and the R&D LARGE_VARIANCE (100% line).
        df = load_pnl(sample_csv)
        _, flags = validate_and_flag(df)
        assert len(flags) == 4
        large = [f for f in flags if "LARGE_VARIANCE" in f]
        assert any("Sales" in f for f in large)      # Revenue line, dept Sales
        assert any("Product" in f for f in large)    # R&D line, dept Product

    def test_legacy_global_policy_recovers_three_flags(self, sample_csv):
        # A flat 0.50 everywhere reproduces the OLD behaviour: three flags,
        # Revenue NOT flagged. Proves the parameter works and old behaviour
        # is recoverable.
        df = load_pnl(sample_csv)
        _, flags = validate_and_flag(df, {"Revenue": 0.50, "_default": 0.50})
        assert len(flags) == 3
        assert not any("LARGE_VARIANCE" in f and "Sales" in f for f in flags)

    def test_custom_policy_flags_small_rnd_swing(self):
        # A +15% R&D swing: flagged at 0.10, silent at 1.00. Same data, the
        # threshold decides.
        df = pd.DataFrame([{
            "date": "2026-03-31", "account": "R&D Expense", "department": "Product",
            "actual": 460000.0, "budget": 400000.0, "prior_year": 400000.0,
        }])
        _, tight = validate_and_flag(df, {"R&D Expense": 0.10, "_default": 0.50})
        _, loose = validate_and_flag(df, {"R&D Expense": 1.00, "_default": 0.50})
        assert any("LARGE_VARIANCE" in f for f in tight)
        assert not any("LARGE_VARIANCE" in f for f in loose)

    def test_enriched_flag_string_still_parses_to_bare_department(self, sample_csv):
        # calculate_variances parses the department via split(': ')[1].split(' (')[0].
        # The new ", threshold X%" suffix must not break that (load-bearing).
        df = load_pnl(sample_csv)
        _, flags = validate_and_flag(df)
        prod_flag = next(f for f in flags if "LARGE_VARIANCE" in f and "Product" in f)
        parsed = prod_flag.split(": ")[1].split(" (")[0].strip()
        assert parsed == "Product"
        # And the pipeline actually skips the parsed department.
        df = calculate_variances(df, flags)
        prod = df[df["department"] == "Product"].iloc[0]
        assert pd.isna(prod["variance_abs"])

    def test_flag_string_names_the_threshold(self, sample_csv):
        df = load_pnl(sample_csv)
        _, flags = validate_and_flag(df)
        prod_flag = next(f for f in flags if "LARGE_VARIANCE" in f and "Product" in f)
        sales_flag = next(f for f in flags if "LARGE_VARIANCE" in f and "Sales" in f)
        assert "threshold 100%" in prod_flag
        assert "threshold 10%" in sales_flag

    def test_audit_record_contains_resolved_policy(
            self, sample_csv, loaded_pipeline, tmp_dirs, mock_commentary):
        out_dir, audit_log = tmp_dirs
        df, flags = loaded_pipeline
        write_output(mock_commentary, sample_csv, flags, 895, 1114, "end_turn",
                     thresholds=None)
        record = json.loads(audit_log.read_text(encoding="utf-8").strip())
        assert "thresholds" in record
        assert record["thresholds"]["Revenue"] == 0.10
        assert record["thresholds"]["R&D Expense"] == 1.00
        assert record["thresholds"]["_default"] == 0.50


# =============================================================================
# PERIOD SCOPING
# =============================================================================

@pytest.fixture
def full_df():
    """The real 12-month sample, loaded. Period-scoping tests need multi-month data."""
    root = Path(__file__).parent.parent
    return load_pnl(root / "data" / "sample_pnl.csv")


class TestPeriodScoping:

    def test_filter_march_returns_seven_rows(self, full_df):
        march = filter_to_period(full_df, "March 2026")
        assert len(march) == 7
        assert march["date"].str.startswith("2026-03").all()

    def test_filter_iso_date_form_matches_label(self, full_df):
        by_iso   = filter_to_period(full_df, "2026-03-31")
        by_label = filter_to_period(full_df, "March 2026")
        assert len(by_iso) == 7
        assert list(by_iso["date"]) == list(by_label["date"])

    def test_absent_but_valid_period_lists_available(self, full_df):
        # Valid label, no matching data -> the 'Available periods' listing.
        with pytest.raises(ValueError) as exc:
            filter_to_period(full_df, "March 2027")
        msg = str(exc.value)
        assert "Available periods" in msg
        assert "January 2026" in msg and "December 2026" in msg

    def test_malformed_period_raises_unrecognised(self, full_df):
        # Bad format fails parsing first, with a distinct 'Unrecognised' message.
        with pytest.raises(ValueError) as exc:
            filter_to_period(full_df, "Foo 2026")
        assert "Unrecognised period" in str(exc.value)

    def test_available_periods_twelve_ordered(self, full_df):
        periods = available_periods(full_df)
        assert len(periods) == 12
        assert periods[0]  == ("2026-01-31", "January 2026")
        assert periods[-1] == ("2026-12-31", "December 2026")

    def test_filter_does_not_mutate_input(self, full_df):
        before = len(full_df)
        filter_to_period(full_df, "March 2026")
        assert len(full_df) == before

    def test_march_end_to_end_four_flags(self, full_df):
        march = filter_to_period(full_df, "March 2026")
        _, flags = validate_and_flag(march)
        assert len(flags) == 4

    def test_july_tells_a_different_story(self, full_df):
        july = filter_to_period(full_df, "July 2026")
        _, flags = validate_and_flag(july)
        rev = [f for f in flags if "LARGE_VARIANCE" in f and "Sales" in f]
        assert len(rev) == 1
        assert "-55.0%" in rev[0] and "threshold 10%" in rev[0]


# =============================================================================
# REVIEW DECISION (shared pure function)
# =============================================================================

class TestReviewDecision:

    def test_flags_trip_review(self):
        req, reasons = compute_requires_review(
            ["LARGE_VARIANCE: Sales (+13.6% above budget, threshold 10%)"],
            "end_turn", 800)
        assert req is True
        assert any("flag" in r.lower() for r in reasons)

    def test_truncation_trips_review(self):
        req, reasons = compute_requires_review([], "max_tokens", 800)
        assert req is True
        assert any("truncated" in r.lower() for r in reasons)

    def test_short_output_trips_review(self):
        req, reasons = compute_requires_review([], "end_turn", 150)
        assert req is True
        assert any("short" in r.lower() for r in reasons)

    def test_clean_case_no_review(self):
        req, reasons = compute_requires_review([], "end_turn", 800)
        assert req is False
        assert reasons == []

    def test_truncated_and_short_does_not_double_count(self):
        # Truncation already explains a short output; the short reason is suppressed.
        req, reasons = compute_requires_review([], "max_tokens", 150)
        assert req is True
        assert any("truncated" in r.lower() for r in reasons)
        assert not any("short" in r.lower() for r in reasons)


# =============================================================================
# THRESHOLD CONTROL - percent/fraction conversion (web boundary)
# =============================================================================

class TestThresholdConversion:

    def test_percent_to_fraction_single_convert(self):
        policy = build_policy_from_ui(
            {"Revenue": 10.0, "COGS": 15.0, "R&D Expense": 100.0}, 50.0)
        assert policy["Revenue"] == pytest.approx(0.10)
        assert policy["COGS"] == pytest.approx(0.15)
        assert policy["R&D Expense"] == pytest.approx(1.00)
        assert policy["_default"] == pytest.approx(0.50)

    def test_no_double_conversion(self):
        # 10 percent must become 0.10, not 0.001 (the divide-by-100-twice bug).
        policy = build_policy_from_ui({"Revenue": 10.0}, 50.0)
        assert policy["Revenue"] == pytest.approx(0.10)
        assert policy["Revenue"] != pytest.approx(0.001)

    def test_default_always_present(self):
        assert build_policy_from_ui({}, 50.0)["_default"] == pytest.approx(0.50)

    def test_non_whole_percent_snapped_to_whole(self):
        # Snap so the policy note and the flag string cannot disagree.
        assert build_policy_from_ui({"X": 12.4}, 50.0)["X"] == pytest.approx(0.12)
        assert build_policy_from_ui({"X": 12.6}, 50.0)["X"] == pytest.approx(0.13)
        assert build_policy_from_ui({"X": 12.5}, 50.0)["X"] == pytest.approx(0.12)
        assert build_policy_from_ui({}, 47.6)["_default"] == pytest.approx(0.48)
        # The stored fraction is a whole percent, so note and flag agree.
        note = policy_note(build_policy_from_ui({"Revenue": 12.5}, 50.0))
        assert "12%" in note and "12.5%" not in note

    def test_ui_policy_relaxing_revenue_drops_flag(self, sample_csv):
        # Revenue at 50% (the old global): March's +13.6% Revenue no longer flags.
        df = load_pnl(sample_csv)
        pct = {a: v * 100 for a, v in VARIANCE_THRESHOLDS.items()}
        pct["Revenue"] = 50.0
        _, flags = validate_and_flag(df, thresholds=build_policy_from_ui(pct, 50.0))
        assert not any("LARGE_VARIANCE" in f and "Sales" in f for f in flags)
        assert len(flags) == 3

    def test_ui_policy_tightening_marketing_adds_flag(self, sample_csv):
        # Marketing at 15%: March's +18.8% clears it (default 30% did not) -> flags.
        df = load_pnl(sample_csv)
        pct = {a: v * 100 for a, v in VARIANCE_THRESHOLDS.items()}
        pct["Marketing Spend"] = 15.0
        _, flags = validate_and_flag(df, thresholds=build_policy_from_ui(pct, 50.0))
        assert any("LARGE_VARIANCE" in f and "Marketing" in f for f in flags)
        assert len(flags) == 5


# =============================================================================
# INPUT HASH (data lineage) and PDF BYTES (shared builder)
# =============================================================================

class TestInputHashAndPdf:

    def test_hash_input_pure_and_prefixed(self, sample_csv):
        df = load_pnl(sample_csv)
        h = hash_input(df)
        assert h.startswith("sha256:")
        assert hash_input(df) == h            # deterministic, no IO

    def test_hash_input_ignores_computed_columns(self, sample_csv):
        # Variance columns added downstream must not change the lineage hash.
        df = load_pnl(sample_csv)
        base = hash_input(df)
        df2, flags = validate_and_flag(df)
        df2 = calculate_variances(df2, flags)
        assert hash_input(df2) == base

    def test_cli_hash_equals_web_hash(self, sample_csv, tmp_dirs, mock_commentary):
        # write_output(df=...) records exactly hash_input(df): CLI == web lineage.
        out_dir, audit_log = tmp_dirs
        df = load_pnl(sample_csv)
        write_output(mock_commentary, sample_csv, [], 895, 1114, "end_turn", df=df)
        record = json.loads(audit_log.read_text(encoding="utf-8").strip())
        assert record["input_hash"] == hash_input(df)

    def test_build_pdf_bytes_returns_valid_pdf(self, loaded_pipeline, mock_commentary):
        df, flags = loaded_pipeline
        pdf = build_pdf_bytes(
            mock_commentary, df, flags, 895, 1114,
            "March 2026", "Valencia Operations", "2026-03-31T00:00:00+00:00",
            policy_note_text="Flagging policy: Revenue 10%, default 50%")
        assert pdf[:5] == b"%PDF-"
        assert len(pdf) > 3000


# =============================================================================
# KEYLESS WORKED EXAMPLE (D2) - real, not fabricated
# =============================================================================

DOCS_DIR = Path(__file__).parent.parent / "docs"


class TestKeylessExample:

    def test_commentary_is_verbatim_from_sample_file(self):
        ex = load_example()
        sample = (DOCS_DIR / "sample_output.txt").read_text(encoding="utf-8")
        assert ex["commentary"].startswith("EXECUTIVE SUMMARY")
        assert "DATA FLAGS" in ex["commentary"]
        assert ex["commentary"] in sample          # verbatim: no fabrication/drift

    def test_flags_match_pipeline_march(self):
        ex = load_example()
        df = load_pnl(DOCS_DIR.parent / "data" / "sample_pnl.csv")
        df = filter_to_period(df, "March 2026")
        _, flags = validate_and_flag(df)            # config policy
        assert ex["flags"] == flags
        assert len(ex["flags"]) == 4
        assert any("LARGE_VARIANCE" in f and "Sales" in f for f in ex["flags"])

    def test_hash_matches_pipeline_and_audit(self):
        ex = load_example()
        assert ex["input_hash"] == hash_input(ex["df"])   # recompute agrees
        audit = json.loads(
            (DOCS_DIR / "audit_log_sample.jsonl").read_text(encoding="utf-8"))
        assert ex["input_hash"] == audit["input_hash"]    # same committed run

    def test_flagged_rows_carry_none_variance(self):
        ex = load_example()
        flagged = {"Sales", "Technology", "Admin", "Product"}
        for _, r in ex["df"].iterrows():
            if r["department"] in flagged:
                assert pd.isna(r["variance_abs"])
            else:
                assert pd.notna(r["variance_abs"])

    def test_example_pdf_builds(self):
        ex = load_example()
        pdf = build_pdf_bytes(
            ex["commentary"], ex["df"], ex["flags"],
            ex["input_tokens"], ex["output_tokens"],
            ex["period"], ex["entity"], ex["generated_at"],
            policy_note_text=policy_note(ex["policy"]))
        assert pdf[:5] == b"%PDF-"


# =============================================================================
# COST ESTIMATE (Phase E) - estimate from tokens + rates, never a bill
# =============================================================================

class TestCostEstimate:

    def test_estimate_cost_march_run(self):
        c = estimate_cost(955, 1073)
        assert c["usd"] == pytest.approx(0.019, abs=0.001)
        assert c["eur"] == pytest.approx(0.0176, abs=0.001)
        assert c["tokens_total"] == 2028

    def test_format_cost_march_reads_about_two_cents(self):
        line = format_cost(955, 1073)
        assert "about EUR 0.02" in line
        assert "2,028 tokens (955 in + 1,073 out)" in line
        assert "billed by Anthropic" in line

    def test_format_cost_subcent_says_less_than(self):
        line = format_cost(1, 1)
        assert "less than EUR 0.01" in line
        assert "EUR 0.00" not in line       # never looks free
        assert "0.0000" not in line         # no false precision

    def test_format_cost_has_no_dashes(self):
        line = format_cost(955, 1073)
        assert "—" not in line and "–" not in line


# =============================================================================
# 12-MONTH TREND CHART (shared builder; respects the same flags as the table)
# =============================================================================

class TestTrendChart:

    def test_returns_figure_with_axes(self, full_df):
        fig = build_trend_chart(full_df, "Revenue")
        assert fig.axes                       # a real matplotlib figure
        _plt.close(fig)

    def test_missing_actual_is_a_gap(self, full_df):
        # Legal is missing in Feb (index 1) and March (index 2): gaps, no points.
        fig = build_trend_chart(full_df, "Legal & Compliance")
        actual = fig.axes[0].lines[1].get_ydata()   # lines[0]=budget, [1]=actual
        assert pd.isna(actual[1]) and pd.isna(actual[2])
        _plt.close(fig)

    def test_zero_actual_gets_amber_marker(self, full_df):
        # IT is zero in March (2) and November (10): at zero, amber flagged.
        fig = build_trend_chart(full_df, "IT Infrastructure")
        ax = fig.axes[0]
        actual = ax.lines[1].get_ydata()
        assert actual[2] == 0 and actual[10] == 0
        flagged = ax.lines[2]                        # the amber flagged-marker series
        assert [int(v) for v in flagged.get_xdata()] == [2, 10]
        _plt.close(fig)

    def test_clean_line_is_continuous(self, full_df):
        # Revenue is clean all year: no gaps, and no flagged-marker series.
        fig = build_trend_chart(full_df, "Revenue")
        ax = fig.axes[0]
        actual = ax.lines[1].get_ydata()
        assert not any(pd.isna(v) for v in actual)
        assert len(ax.lines) == 2                    # budget + actual only
        _plt.close(fig)

    def test_png_bytes_non_empty(self, full_df):
        png = trend_png_bytes(full_df, "Revenue")
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        assert len(png) > 1000

    def test_pdf_embeds_the_trend(self, loaded_pipeline, full_df, mock_commentary):
        df, flags = loaded_pipeline
        common = (mock_commentary, df, flags, 895, 1114,
                  "March 2026", "Valencia Operations", "2026-03-31T00:00:00+00:00")
        note = "Flagging policy: Revenue 10%, default 50%"
        without = build_pdf_bytes(*common, policy_note_text=note)
        withtrend = build_pdf_bytes(*common, policy_note_text=note, df_12mo=full_df)
        assert withtrend[:5] == b"%PDF-"
        assert len(withtrend) > len(without)         # the embedded PNG adds bytes


# =============================================================================
# CURRENCY IS CONFIGURABLE (not hardcoded euros)
# =============================================================================

class TestCurrencyConfig:

    def test_prompt_uses_configured_currency(self, loaded_pipeline):
        df, flags = loaded_pipeline
        import src.step2_ai_engine as engine
        _, user_p = engine.build_prompt(df, flags, "March 2026", "Valencia")
        assert "Currency: {}".format(engine.CURRENCY_CODE) in user_p
        assert engine.CURRENCY_SYMBOL in user_p           # on the non-flagged rows

    def test_currency_is_swappable(self, loaded_pipeline):
        # Swapping the config values swaps the prompt currency: nothing hardcoded.
        df, flags = loaded_pipeline
        import src.step2_ai_engine as engine
        with patch.object(engine, "CURRENCY_SYMBOL", "$"), \
             patch.object(engine, "CURRENCY_CODE", "USD"):
            system_p, user_p = engine.build_prompt(df, flags, "March 2026", "X")
        assert "$" in user_p and "Currency: USD" in user_p
        assert "€" not in user_p and "EUR" not in user_p
        assert "in USD" in system_p and "in EUR" not in system_p

    def test_trend_axis_uses_currency_code(self, full_df):
        fig = build_trend_chart(full_df, "Revenue")
        assert fig.axes[0].get_ylabel() == "EUR"          # default, read from config
        _plt.close(fig)


# =============================================================================
# ADDITIONAL UTILITY TESTS
# =============================================================================

class TestUtilityFunctions:

    def test_normalise_dashes_replaces_em_and_en(self):
        raw = "Revenue — up 10% – strong quarter"
        out = _normalise_dashes(raw)
        assert "—" not in out
        assert "–" not in out
        assert out == "Revenue - up 10% - strong quarter"

    def test_clean_markdown_removes_bold(self):
        assert clean_markdown("**bold**") == "bold"

    def test_clean_markdown_removes_heading(self):
        assert clean_markdown("## Heading") == "Heading"

    def test_clean_markdown_removes_rule(self):
        assert clean_markdown("---") == ""

    def test_clean_markdown_removes_bullet(self):
        assert clean_markdown("* item") == "item"

    def test_clean_markdown_preserves_content(self):
        result = clean_markdown("**Sales | Revenue:** text here")
        assert "Sales" in result
        assert "text here" in result
        assert "**" not in result

    def test_extract_label_standard_line(self):
        label, body = extract_label("Sales | Revenue: exceeded budget.")
        assert label == "Sales | Revenue"
        assert "exceeded budget" in body

    def test_extract_label_flagged_line(self):
        line = clean_markdown("**Technology | IT Infrastructure:** [FLAG: ZERO_ACTUAL]")
        label, body = extract_label(line)
        assert label == "Technology | IT Infrastructure"
        assert "[FLAG:" in body
        assert "[FLAG" not in label

    def test_extract_label_accepts_legacy_em_dash(self):
        # Pre-pipe artifacts used an em dash separator; still parseable.
        label, body = extract_label("Sales — Revenue: exceeded budget.")
        assert label == "Sales — Revenue"
        assert "exceeded budget" in body

    def test_extract_label_strips_matched_brackets(self):
        # The model wraps labels in '[ ]'; a bracketed line yields the SAME clean
        # label as the unbracketed form ('Sales | Revenue', not '[Sales | Revenue]').
        b_label, b_body = extract_label("[Sales | Revenue]: exceeded budget.")
        p_label, _      = extract_label("Sales | Revenue: exceeded budget.")
        assert b_label == "Sales | Revenue"
        assert b_label == p_label
        assert "exceeded budget" in b_body

    def test_extract_label_no_brackets_unchanged(self):
        # A label with no brackets passes through untouched.
        label, _ = extract_label("Marketing | Marketing Spend: over budget.")
        assert label == "Marketing | Marketing Spend"

    def test_extract_label_unmatched_bracket_left_as_is(self):
        # Only a MATCHED outer pair is stripped; a lone '[' is preserved as-is.
        label, _ = extract_label("[Sales | Revenue: exceeded budget.")
        assert label == "[Sales | Revenue"

    def test_extract_label_bracketed_legacy_em_dash(self):
        # Brackets stripped first, then the em dash legacy fallback parses the
        # inner text: a bracketed legacy label still resolves.
        label, body = extract_label("[Sales — Revenue]: exceeded budget.")
        assert label == "Sales — Revenue"
        assert "exceeded budget" in body

    def test_extract_label_no_dash_returns_none(self):
        label, body = extract_label("No dash here, plain text.")
        assert label is None

    def test_parse_sections_extracts_all_three(self):
        commentary = (
            "EXECUTIVE SUMMARY\nGood results.\n\n"
            "LINE ITEM COMMENTARY\nSales: strong.\n\n"
            "DATA FLAGS\n- ZERO_ACTUAL: Tech"
        )
        s = parse_sections(commentary)
        assert "Good results" in s["executive_summary"]
        assert "Sales"        in s["line_items"]
        assert "ZERO_ACTUAL"  in s["data_flags"]

    def test_parse_sections_strips_markdown(self):
        commentary = (
            "EXECUTIVE SUMMARY\nGood results.\n\n"
            "LINE ITEM COMMENTARY\n**Tech — IT:** [FLAG: x]\n\n---\n##\n\n"
            "DATA FLAGS\n- FLAG"
        )
        s = parse_sections(commentary)
        assert "**"  not in s["line_items"]
        assert "---" not in s["line_items"]
        assert "##"  not in s["line_items"]

    def test_parse_sections_fallback_no_headers(self):
        s = parse_sections("Plain text. No section headers.")
        assert "Plain text" in s["executive_summary"]
        assert s["line_items"] == ""
        assert s["data_flags"] == ""


class TestDeploymentPins:
    """The web server stack the live app installs."""

    def test_item1_starlette_pinned_for_streamlit_1_60(self):
        """Streamlit 1.60 cannot serve images with starlette 1.8 or later (item 1)."""
        from importlib.metadata import version
        requirements = Path(__file__).resolve().parent.parent / "requirements.txt"
        assert "starlette==1.7.0" in requirements.read_text(encoding="utf-8-sig").split()
        if version("streamlit").startswith("1.60."):
            major, minor = (int(part) for part in version("starlette").split(".")[:2])
            assert (major, minor) < (1, 8)


# =============================================================================
# STEP 2 FIXES: the key gate and failed model calls (items 2, 4, 17, 55)
# =============================================================================

import anthropic
import httpx
from streamlit.testing.v1 import AppTest
from anthropic.resources.messages.messages import Messages
from streamlit_app.lib.claude_client import NoKeyError
from streamlit_app.lib.errors import (
    MODEL_FAILURE_MESSAGES, KEY_LOOKS_COMPLETE,
    failure_code, friendly_message, model_failure_message,
)

APP_HOME = Path(__file__).resolve().parent.parent / "streamlit_app" / "Home.py"
TEST_KEY = "sk-ant-api03-" + "x" * 90       # a stand-in, never a real key

# Every kind of failed model call, as (HTTP status or None for no connection, code).
FAILURE_CASES = [
    (401, "key_rejected"), (403, "key_forbidden"), (404, "model_not_found"),
    (400, "bad_request"), (429, "rate_limited"), (500, "service_unavailable"),
    (529, "service_unavailable"), (None, "service_unavailable"),
]


def _sdk_error(status):
    """A stand-in SDK error for one HTTP status, built the way the SDK builds it.
    No network: the request and response are local httpx objects."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    if status is None:
        return anthropic.APIConnectionError(request=request)
    error_class = {
        400: anthropic.BadRequestError, 401: anthropic.AuthenticationError,
        403: anthropic.PermissionDeniedError, 404: anthropic.NotFoundError,
        429: anthropic.RateLimitError, 500: anthropic.InternalServerError,
        529: anthropic.OverloadedError,
    }[status]
    return error_class("stand-in", response=httpx.Response(status, request=request),
                       body=None)


def _app_with_key_on_home():
    """The app on Home with the stand-in key typed into the sidebar gate."""
    at = AppTest.from_file(str(APP_HOME), default_timeout=120).run()
    at.sidebar.text_input(key="byo_api_key").input(TEST_KEY).run()
    return at


def _click_generate(at):
    next(b for b in at.button if b.label == "Generate commentary").click().run()
    return at


class TestModelFailures:

    @pytest.mark.parametrize("status, code", FAILURE_CASES)
    def test_item17_each_failure_maps_to_one_plain_message(self, status, code):
        exc = _sdk_error(status)
        message = friendly_message(exc)
        assert failure_code(exc) == code
        assert message == model_failure_message(code)
        assert message.endswith("Code: `{}`".format(code))
        assert type(exc).__name__ not in message and "Error" not in message

    @pytest.mark.parametrize("status, code", FAILURE_CASES)
    def test_item55_engine_wrap_keeps_the_cause(self, status, code):
        # call_claude wraps the SDK error in a RuntimeError; the cause must still
        # reach friendly_message, or a rejected key reads "Something went wrong".
        import src.step2_ai_engine as engine
        stand_in = MagicMock()
        stand_in.messages.create.side_effect = _sdk_error(status)
        with pytest.raises(RuntimeError) as raised:
            engine.call_claude("system", "user", client=stand_in)
        assert failure_code(raised.value) == code
        assert friendly_message(raised.value) == model_failure_message(code)

    def test_item17_no_misleading_wording(self):
        for code in ("bad_request", "model_not_found"):
            assert "usually temporary" not in model_failure_message(code)
        assert "claude-sonnet-4-6" in model_failure_message("model_not_found")
        generic = friendly_message(ValueError("boom"))
        assert generic == "Something went wrong running that request. Please try again."
        no_key = friendly_message(NoKeyError("No API key provided."))
        assert "sidebar" in no_key and "above" not in no_key
        every_message = list(MODEL_FAILURE_MESSAGES.values()) + [generic, no_key]
        for message in every_message:
            assert "example prompts" not in message
            assert chr(0x2014) not in message and chr(0x2013) not in message

    def test_item17_rejected_key_on_the_page_reads_plainly(self):
        at = _app_with_key_on_home()
        at.switch_page("views/variance_commentary.py").run()
        with patch.object(Messages, "create", side_effect=_sdk_error(401)):
            _click_generate(at)
        errors = [e.value for e in at.error]
        assert errors == [model_failure_message("key_rejected")]
        assert not at.exception


class TestKeyGate:

    def test_item2_privacy_wording(self):
        at = AppTest.from_file(str(APP_HOME), default_timeout=120).run()
        box = at.sidebar.text_input(key="byo_api_key")
        assert box.help == ("Held in the server's memory for this session only. "
                            "Never stored, never logged.")
        notes = " ".join(m.value for m in at.sidebar.markdown)
        assert ("Your key is held in the server's memory for your session only, "
                "used to make the call, and never stored or logged.") in notes
        assert "browser" not in notes
        source = (APP_HOME.parent / "lib" / "key_gate.py").read_text(encoding="utf-8")
        assert "never stored server-side" not in source
        assert "browser" not in source

    def test_item2_success_line_does_not_claim_the_key_works(self):
        at = _app_with_key_on_home()
        assert [s.value for s in at.sidebar.success] == [KEY_LOOKS_COMPLETE]

    def test_item4_key_entered_on_home_stays_live_on_the_model_page(self):
        at = _app_with_key_on_home()
        assert isinstance(at.session_state["vc_live_client"], anthropic.Anthropic)

        at.switch_page("views/variance_commentary.py").run()
        assert not at.exception
        assert at.sidebar.text_input(key="byo_api_key").value == TEST_KEY
        assert [s.value for s in at.sidebar.success] == [KEY_LOOKS_COMPLETE]
        assert not any("Paste your Anthropic API key" in i.value for i in at.info)

        # Generate reaches the model call with a client built from that key.
        # The stand-in replaces the SDK's create, so nothing goes on the network.
        seen = {}

        def stand_in_create(resource, **kwargs):
            seen["api_key"] = resource._client.api_key
            raise _sdk_error(500)

        with patch.object(Messages, "create", stand_in_create):
            _click_generate(at)
        assert seen["api_key"] == TEST_KEY


# =============================================================================
# STEP 2 FIXES: flag wording, PDF text and glyphs, sidebar on arrival
# (items 28, 35, 37, 53, 58)
# =============================================================================

import base64
import re
import zlib


def _pdf_operators(pdf):
    """The decoded page operators of a reportlab PDF (ASCII85, then Flate), so a
    test can read which text and which glyph each cell printed."""
    pattern = rb"/Filter \[ /ASCII85Decode /FlateDecode \] /Length (\d+)\s*>>\s*stream\r?\n"
    streams = []
    for found in re.finditer(pattern, pdf):
        raw = pdf[found.end():found.end() + int(found.group(1))].strip()
        if raw.endswith(b"~>"):
            raw = raw[:-2]
        streams.append(zlib.decompress(base64.a85decode(raw)).decode("latin-1"))
    assert streams, "no page content found"
    return "\n".join(streams)


def _one_row(account, department, actual, budget):
    return pd.DataFrame([{
        "date": "2026-07-31", "account": account, "department": department,
        "actual": float(actual), "budget": float(budget), "prior_year": float(budget),
    }])


class TestFlagDirection:

    def test_item37_revenue_below_budget_reads_below_and_adverse(self):
        # July's sample row: revenue 540,000 against a 1,200,000 budget.
        _, flags = validate_and_flag(_one_row("Revenue", "Sales", 540000, 1200000))
        assert flags == [
            "LARGE_VARIANCE: Sales (-55.0% below budget, adverse, threshold 10%)"]

    @pytest.mark.parametrize("account, actual, budget, words", [
        ("Revenue", 1250000, 1100000, "+13.6% above budget, favourable"),
        ("COGS", 480000, 400000, "+20.0% above budget, adverse"),
        ("COGS", 300000, 400000, "-25.0% below budget, favourable"),
    ])
    def test_item37_direction_and_effect_follow_the_line(
            self, account, actual, budget, words):
        _, flags = validate_and_flag(_one_row(account, "Dept", actual, budget))
        assert len(flags) == 1 and words in flags[0]
        assert "over budget" not in flags[0]

    def test_item37_july_prompt_carries_the_corrected_flag(self, full_df):
        import src.step2_ai_engine as engine
        july = filter_to_period(full_df, "July 2026")
        july, flags = validate_and_flag(july)
        july = calculate_variances(july, flags)
        _, user_p = engine.build_prompt(july, flags, "July 2026", "Valencia Operations")
        assert ("LARGE_VARIANCE: Sales (-55.0% below budget, adverse, threshold 10%)"
                in user_p)
        assert "over budget" not in user_p
        # The flag still parses to its department, so the row stays uncomputed.
        assert pd.isna(july[july["department"] == "Sales"].iloc[0]["variance_abs"])


class TestPdfText:

    def test_item28_model_text_with_markup_characters_builds_a_pdf(
            self, loaded_pipeline):
        df, flags = loaded_pipeline
        commentary = (
            "EXECUTIVE SUMMARY\nMargin fell <b & stayed < plan.\n\n"
            "LINE ITEM COMMENTARY\n"
            "Product | R&D Expense: Spend <b rose & stayed < plan.\n"
            "Admin | Legal & Compliance: [FLAG: MISSING_ACTUAL <b & <]\n\n"
            "DATA FLAGS\n- MISSING_ACTUAL: Admin <b & <")
        pdf = build_pdf_bytes(
            commentary, df, flags + ["ODD_FLAG: R&D <b & <"], 895, 1114,
            "March 2026", "Valencia & <b Operations", "2026-03-31T00:00:00+00:00",
            policy_note_text="Flagging policy: R&D 100% <b & <")
        assert pdf[:5] == b"%PDF-"
        # reportlab splits a run at "<" into two Tj strings; join them back.
        ops = _pdf_operators(pdf).replace(") Tj (", "")
        assert "Spend <b rose & stayed < plan." in ops
        assert "R&D Expense" in ops and "R&D;" not in ops

    def test_5b_missing_actual_advises_and_claims_no_block(self, loaded_pipeline):
        # Flags never block the sign-off, so the PDF's action for a missing
        # actual is advice, not a block the app does not have (5b fix round).
        df, _ = loaded_pipeline
        pdf = build_pdf_bytes(
            "EXECUTIVE SUMMARY\nMargin held.", df, ["MISSING_ACTUAL: Admin"], 1, 1,
            "March 2026", "Valencia Operations", "2026-03-31T00:00:00+00:00")
        ops = _pdf_operators(pdf).replace(") Tj (", "")
        assert "Submit the actual figure immediately. Sign-off should wait for it." in ops
        assert "cannot be signed off" not in ops

    def test_item35_pdf_failure_leaves_a_plain_message(self):
        with patch("src.step3_output_writer.build_pdf_bytes",
                   side_effect=RuntimeError("boom")):
            at = AppTest.from_file(str(APP_HOME), default_timeout=120)
            at.switch_page("views/variance_commentary.py").run()
        assert not at.exception
        captions = [c.value for c in at.caption]
        assert ("The PDF is unavailable this session: Something went wrong running "
                "that request. Please try again.") in captions
        assert not any("boom" in c or "RuntimeError" in c for c in captions)
        assert not at.get("download_button")
        # The rest of the worked example still renders.
        assert any("Executive summary" in m.value for m in at.markdown)

    def test_item58_pdf_flag_marker_is_a_triangle(self):
        ex = load_example()
        pdf = build_pdf_bytes(
            ex["commentary"], ex["df"], ex["flags"],
            ex["input_tokens"], ex["output_tokens"],
            ex["period"], ex["entity"], ex["generated_at"])
        dingbats = re.search(rb"/BaseFont /ZapfDingbats /Name /(F\d+)", pdf)
        glyphs = re.findall(
            r"/{} [\d.]+ Tf [\d.]+ TL (?:[-\d. ]+ Td )?\((.)\) Tj".format(dingbats.group(1).decode()),
            _pdf_operators(pdf))
        # ZapfDingbats prints "s" as the solid triangle and "l" as the dot; "n" is
        # its filled square, which is what the outline triangle used to print.
        assert glyphs.count("s") == 4            # the four flagged March rows
        assert glyphs.count("l") == 3            # the three computed rows
        assert "n" not in glyphs


class TestSidebarOnArrival:

    def test_item53_sidebar_state_is_auto(self):
        import streamlit
        with patch.object(streamlit, "set_page_config",
                          wraps=streamlit.set_page_config) as spy:
            AppTest.from_file(str(APP_HOME), default_timeout=120).run()
        assert spy.call_args.kwargs["initial_sidebar_state"] == "auto"


# =============================================================================
# STEP 2 UX: the key gate in an expander, the Home button, tabular figures
# (UX1, UX2, UX4)
# =============================================================================

from streamlit_app.lib.key_gate import GATE_LABEL, LIVE_ON, LIVE_OFF
from streamlit_app.lib.theme import inject_css


def _gate(at):
    gates = [e for e in at.sidebar.expander if e.label == GATE_LABEL]
    assert len(gates) == 1
    return gates[0]


class TestUx:

    def test_ux1_key_gate_sits_in_a_closed_expander(self):
        at = AppTest.from_file(str(APP_HOME), default_timeout=120).run()
        gate = _gate(at)
        assert not gate.proto.expanded
        assert gate.text_input(key="byo_api_key").label == "Anthropic API key"
        assert any("bills your Anthropic account" in c.value for c in gate.caption)
        assert any("held in the server's memory" in m.value for m in gate.markdown)
        # Directly below the expander, one line on live mode; no old heading.
        assert [c.value for c in at.sidebar.caption][-1] == LIVE_OFF
        assert not any("Run it yourself" in m.value for m in at.sidebar.markdown)

    def test_ux1_live_mode_line_follows_the_key_across_pages(self):
        at = _app_with_key_on_home()
        assert [s.value for s in _gate(at).success] == [KEY_LOOKS_COMPLETE]
        assert [c.value for c in at.sidebar.caption][-1] == LIVE_ON
        at.switch_page("views/variance_commentary.py").run()
        assert [c.value for c in at.sidebar.caption][-1] == LIVE_ON

    def test_ux1_short_key_warning_is_inside_the_gate(self):
        at = AppTest.from_file(str(APP_HOME), default_timeout=120).run()
        at.sidebar.text_input(key="byo_api_key").input("sk-ant-short").run()
        assert len(_gate(at).warning) == 1
        assert [c.value for c in at.sidebar.caption][-1] == LIVE_OFF

    def test_ux2_home_button_opens_the_worked_example_page(self):
        at = AppTest.from_file(str(APP_HOME), default_timeout=120).run()
        assert [b.label for b in at.main.button] == ["See the worked example"]
        at.main.button[0].click().run()
        assert not at.exception
        assert [t.label for t in at.tabs] == ["View a worked example", "Run it yourself"]
        assert any("saved example run for March 2026" in i.value for i in at.info)

    def test_ux4_tabular_figures_only_where_numbers_line_up(self):
        css = inject_css()
        global_rule = css[css.index("html, body"):]
        global_rule = global_rule[:global_rule.index("}")]
        assert "tnum" not in global_rule and '"cv05" 1' in global_rule
        # Lists, bold, italics and captions in Inter too, as Project 6's
        # theme sets them (5b fix round)
        assert "th, ul, ol, li, strong, em, caption {" in global_rule
        numeric = css[css.index("Tabular figures only where numbers line up"):]
        selectors, body = numeric.split("{", 1)
        assert "table, table *" in selectors
        assert '"tnum" 1' in body[:body.index("}")]


# =============================================================================
# STEP 3: the input hash is the same on every platform (H1)
# =============================================================================

import os

LF_MARCH_HASH = "sha256:84df784503b6a4773a99b2ef8dc7ce9dddea9059aab15fc1059140ed7704ca4f"


class TestPortableHash:

    def test_h1_hash_input_ignores_the_platform_line_ending(self, monkeypatch):
        # pandas writes os.linesep unless told otherwise, so Windows (CRLF) and
        # Linux, where the live app runs (LF), used to hash the same March rows
        # to two different values.
        df = filter_to_period(
            load_pnl(DOCS_DIR.parent / "data" / "sample_pnl.csv"), "March 2026")
        for linesep in ("\r\n", "\n"):
            monkeypatch.setattr(os, "linesep", linesep)
            assert hash_input(df) == LF_MARCH_HASH
        committed = json.loads(
            (DOCS_DIR / "audit_log_sample.jsonl").read_text(encoding="utf-8"))
        assert committed["input_hash"] == LF_MARCH_HASH


# =============================================================================
# STEP 3: Home's button opens the worked example tab (UX2). Since Step 5a the
# example is simply the first tab, so no flag or default= is needed.
# =============================================================================

def _tab_sets(node):
    """Every set of tabs under an AppTest node, in page order."""
    found = []
    for child in getattr(node, "children", {}).values():
        if getattr(child, "type", None) == "tab_container":
            found.append(child)
        found.extend(_tab_sets(child))
    return found


class TestUx2ExampleTab:

    def test_ux2_button_opens_the_example_tab(self):
        at = AppTest.from_file(str(APP_HOME), default_timeout=120).run()
        next(b for b in at.main.button if b.label == "See the worked example").click().run()
        assert not at.exception
        assert [t.label for t in at.tabs] == ["View a worked example", "Run it yourself"]
        tab_sets = _tab_sets(at.main)
        assert len(tab_sets) == 1
        assert tab_sets[0].proto.tab_container.default_tab_index == 0
        assert "vc_open_example" not in at.session_state     # no flag at all

    def test_ux2_sidebar_link_still_opens_the_first_tab(self):
        # The sidebar link and Home's button land on the same first tab, the
        # example, before and after the button has been used.
        at = AppTest.from_file(str(APP_HOME), default_timeout=120).run()
        at.switch_page("views/variance_commentary.py").run()
        assert not at.exception
        assert [t.label for t in at.tabs] == ["View a worked example", "Run it yourself"]
        assert _tab_sets(at.main)[0].proto.tab_container.default_tab_index == 0
        at.switch_page("Home.py").run()
        next(b for b in at.main.button if b.label == "See the worked example").click().run()
        assert _tab_sets(at.main)[0].proto.tab_container.default_tab_index == 0
        at.switch_page("Home.py").run()
        at.switch_page("views/variance_commentary.py").run()
        assert _tab_sets(at.main)[0].proto.tab_container.default_tab_index == 0


class TestDependencies:
    """The pinned packages (items 21 and 22): test tools only in the dev file,
    no byte order mark, one anthropic version, patched versions."""

    @staticmethod
    def _pins(name):
        text = (Path(__file__).resolve().parent.parent / name).read_text(encoding="utf-8-sig")
        pins = {}
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith(("#", "-r")) and "==" in line:
                package, version = line.split("==", 1)
                pins[package.strip().lower()] = version.strip()
        return text, pins

    @staticmethod
    def _version(text):
        return tuple(int(part) for part in text.split(".")[:3])

    def test_item21_test_tools_only_in_dev_requirements(self):
        _, runtime = self._pins("requirements.txt")
        dev_text, dev = self._pins("requirements-dev.txt")
        assert not {"pytest", "pluggy", "iniconfig", "pygments", "colorama"} & set(runtime)
        assert "-r requirements.txt" in dev_text and "pytest" in dev

    def test_item21_no_byte_order_mark(self):
        root = Path(__file__).resolve().parent.parent
        for name in ("requirements.txt", "requirements-dev.txt"):
            assert not (root / name).read_bytes().startswith(b"\xef\xbb\xbf"), name

    def test_item21_one_anthropic_version(self):
        assert self._pins("requirements.txt")[1]["anthropic"] == "0.116.0"

    def test_item21_no_unused_packages(self):
        pins = self._pins("requirements.txt")[1]
        assert "openpyxl" not in pins and "et_xmlfile" not in pins

    def test_item22_patched_versions(self):
        pins = self._pins("requirements.txt")[1]
        assert self._version(pins["anyio"]) >= (4, 14, 2)
        assert self._version(pins["pillow"]) >= (12, 3, 0)

    def test_item22_certifi_has_the_fixed_root_bundle(self):
        # certifi before 2026.10.18 trusts emSign ECC Root CA G3, whose
        # intermediates had compromised keys (GHSA-6q48-6c7w-9gw2).
        text = (Path(__file__).resolve().parent.parent / "requirements.txt").read_text(
            encoding="utf-8-sig")
        assert "certifi==2026.10.19" in text.split()


# =============================================================================
# STEP 5a: the series look (V1 to V5 and the page icon), the same tests in
# every project
# =============================================================================

import html
import tomllib

import streamlit
from streamlit_app.lib import theme
from streamlit_app.lib.theme import header_html, status_chip_html

APP_DIR = APP_HOME.parent

# Every page's address as published before Step 5a (the README, posts), in the
# navigation order. A title may change; an address may not.
PAGE_URLS = ["", "how_it_works", "variance_commentary", "your_own_data", "how_its_built"]

# Every page as (the file AppTest opens, its title, the name in its banner).
PAGES = [
    ("Home.py", "Home", "Variance Commentary"),
    ("views/how_it_works.py", "How it works", "How it works"),
    ("views/variance_commentary.py", "Variance commentary", "Variance commentary"),
    ("views/your_own_data.py", "Your own data", "Your own data"),
    ("views/how_its_built.py", "How it's built", "How it's built"),
]


def _navigation():
    """One run of Home: the pages it hands to st.navigation and the arguments
    of its st.set_page_config call."""
    with patch.object(streamlit, "navigation", wraps=streamlit.navigation) as nav, \
            patch.object(streamlit, "set_page_config",
                         wraps=streamlit.set_page_config) as page_config:
        at = AppTest.from_file(str(APP_HOME), default_timeout=120).run()
    assert not at.exception
    return nav.call_args.args[0], page_config.call_args.kwargs


class TestStep5aLook:

    def test_v1_primary_colour_is_the_navy(self):
        config = tomllib.loads(
            (APP_DIR.parent / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
        assert config["theme"]["primaryColor"] == theme.DARK_BLUE == "#1A3A5C"
        assert config["client"]["toolbarMode"] == "minimal"

    def test_v2_every_page_has_a_banner(self):
        at = AppTest.from_file(str(APP_HOME), default_timeout=120).run()
        for page_file, _, banner_name in PAGES:
            at.switch_page(page_file).run()
            assert not at.exception, page_file
            banners = [m.value for m in at.main.markdown if 'class="sc-header"' in m.value]
            assert len(banners) == 1, page_file
            assert banners[0].startswith(
                '<div class="sc-header"><h1>{}</h1><p>'.format(html.escape(banner_name)))
        assert header_html("A & B", "<one line>") == (
            '<div class="sc-header"><h1>A &amp; B</h1><p>&lt;one line&gt;</p></div>')

    def test_v2_draft_and_final_chips(self):
        assert status_chip_html("final") == '<span class="sc-status final">FINAL</span>'
        for status in ("draft", "DRAFT", "FINAL", "", None):
            assert status_chip_html(status) == '<span class="sc-status draft">DRAFT</span>'
        css = inject_css()
        assert ".sc-status.draft { background: #B45F06; }" in css
        assert ".sc-status.final { background: #2E6B3F; }" in css
        assert "sc-badge" not in css and not hasattr(theme, "badge_html")

    def test_v3_home_blocks_and_page_links(self):
        at = AppTest.from_file(str(APP_HOME), default_timeout=120).run()
        headings = [m.value for m in at.main.markdown if m.value.startswith("#")]
        assert headings == ["#### What it does", "#### The governance promise", "#### Pages"]
        links = [link.proto for link in at.main.get("page_link")]
        assert [link.page for link in links] == PAGE_URLS[1:]
        assert [link.label.split(": ")[0] for link in links] == [p[1] for p in PAGES[1:]]
        # The key explainer stays, closed, with its cost; the sample company is
        # the one closing caption; no green "loaded" box.
        (explainer,) = at.main.expander
        assert explainer.label == "Using your own API key" and not explainer.proto.expanded
        assert "about 1.9 US cents" in explainer.markdown[0].value
        assert [c.value for c in at.main.caption] == [
            "Sample data only: Valencia Operations is a fictional company, with twelve "
            "months of profit and loss data across seven lines. All figures are "
            "illustrative."]
        assert not at.main.success

    def test_v4_titles_are_sentence_case_and_urls_unchanged(self):
        pages, _ = _navigation()
        assert [page.url_path for page in pages] == PAGE_URLS
        assert [page.title for page in pages] == [p[1] for p in PAGES]
        for page in pages:
            assert page.title[1:] == page.title[1:].lower(), page.title

    def test_v5_example_tab_first_and_no_open_example_flag(self):
        at = AppTest.from_file(str(APP_HOME), default_timeout=120).run()
        at.switch_page("views/variance_commentary.py").run()
        assert not at.exception
        assert [t.label for t in at.tabs] == ["View a worked example", "Run it yourself"]
        (tab_set,) = _tab_sets(at.main)
        assert tab_set.proto.tab_container.default_tab_index == 0
        for source in APP_DIR.rglob("*.py"):
            assert "_open_example" not in source.read_text(encoding="utf-8"), source.name

    def test_v5_page_icon_is_the_tool_page_icon(self):
        pages, page_config = _navigation()
        tool_page = next(page for page in pages if page.url_path == "variance_commentary")
        assert page_config["page_icon"] == tool_page.icon == ":material/bar_chart:"


# =============================================================================
# STEP 5b: the Sign-off section, after Project 6 (the rule in src/signoff.py)
# =============================================================================

from types import SimpleNamespace

from src.signoff import (
    ALREADY_SIGNED, NAME_LIMIT, NAME_REFUSAL, SCOPE_NOTE, STALE_CAPTION,
    WORD_HELP, WORD_LABEL, WORD_REFUSAL, clean_name, pdf_name, sign_off, when_text,
)

_SENTENCE = ("Signing says you have read the result against the figures above. The "
             "figures come from Python. This version does not check the numbers in "
             "the model's wording.")
_DRAFT_CHIP = '<span class="sc-status draft">DRAFT</span>'
_FINAL_CHIP = '<span class="sc-status final">FINAL</span>'
_REVIEW_WARNING = "Human review required before this commentary is used."
_MARCH_FLAGS = [
    "LARGE_VARIANCE: Sales (+13.6% above budget, favourable, threshold 10%)",
    "ZERO_ACTUAL: Technology (budget was 45,000)",
    "MISSING_ACTUAL: Admin",
    "LARGE_VARIANCE: Product (+122.5% above budget, adverse, threshold 100%)",
]


def _pdf_text(pdf):
    """The PDF's text runs in page order, string escapes undone (an octal code
    such as \\351 is a character such as é), joined by single spaces."""
    def unescape(match):
        code = match.group(1)
        return chr(int(code, 8)) if code[0] in "01234567" else code
    runs = re.findall(r"\(((?:[^()\\]|\\.)*)\)\s*Tj", _pdf_operators(pdf), re.S)
    text = " ".join(re.sub(r"\\([0-7]{1,3}|.)", unescape, run, flags=re.S)
                    for run in runs)
    return " ".join(text.split())


@pytest.fixture
def stand_in_model():
    """The model's reply from a stand-in, never the network: the worked
    example's saved commentary and token counts, whatever the period."""
    example = load_example()
    reply = SimpleNamespace(
        content=[SimpleNamespace(text=example["commentary"])],
        usage=SimpleNamespace(input_tokens=example["input_tokens"],
                              output_tokens=example["output_tokens"]),
        stop_reason="end_turn")
    with patch.object(Messages, "create", return_value=reply) as create:
        yield create


@pytest.fixture
def downloads(monkeypatch):
    """Reads the file behind a download button: while the test runs, every
    file the page hands to one is kept by its media id."""
    from streamlit.runtime.memory_media_file_storage import MemoryMediaFileStorage
    files = {}
    load = MemoryMediaFileStorage.load_and_get_id

    def _load(self, data, mimetype, kind, filename=None):
        file_id = load(self, data, mimetype, kind, filename)
        files[file_id] = self.get_file(file_id).content
        return file_id

    monkeypatch.setattr(MemoryMediaFileStorage, "load_and_get_id", _load)

    def read(at, label):
        (button,) = [d for d in at.get("download_button") if d.proto.label == label]
        return files[button.proto.url.rsplit("/", 1)[-1].split(".")[0]]
    return read


def _live_page():
    """The tool page with the stand-in key typed in, before any Generate."""
    at = _app_with_key_on_home()
    at.switch_page("views/variance_commentary.py").run()
    assert not at.exception
    return at


@pytest.fixture
def generated(stand_in_model):
    """The tool page after Generate commentary for March, the stand-in replying."""
    at = _click_generate(_live_page())
    assert not at.exception and at.session_state["vc_result"]
    return at


def _signoff_section(at):
    """The Sign-off section's markdown on "Run it yourself", from its heading to
    the session audit (whose rows start in bold)."""
    values = [m.value for m in at.tabs[1].markdown]
    section = values[values.index("#### Sign-off"):]
    end = next((i for i, v in enumerate(section) if v.startswith("**")), len(section))
    return section[:end]


def _numbered(markdown):
    """The lines of a numbered markdown list, without their numbers."""
    lines = markdown.splitlines()
    assert [line.split(". ", 1)[0] for line in lines] == [
        str(i) for i in range(1, len(lines) + 1)]
    return [line.split(". ", 1)[1] for line in lines]


def _refusals(at):
    return [w.value for w in at.tabs[1].warning if w.value != _REVIEW_WARNING]


def _boxes(at):
    return [(t.key, t.value) for t in at.text_input if t.key in ("vc_reviewer", "vc_sign")]


def _signoff_buttons(at):
    return [b for b in at.button if b.key == "vc_signoff"]


def _labels(node):
    return [d.proto.label for d in node.get("download_button")]


def _session_audit(at):
    """The Session audit expander on "Run it yourself"."""
    (audit,) = [e for e in at.tabs[1].expander if e.label.startswith("Session audit")]
    return audit


def _sign(at, name="José Núñez", word="SIGN"):
    at.text_input(key="vc_reviewer").input(name).run()
    at.text_input(key="vc_sign").input(word).run()
    at.button(key="vc_signoff").click().run()
    assert not at.exception


class TestStep5bSignOff:
    """The Sign-off section: the rule in src/signoff.py, drawn as in Project 6."""

    def test_5b_no_section_before_a_result(self):
        at = _live_page()
        assert "#### Sign-off" not in [m.value for m in at.markdown]
        assert not _boxes(at) and not _signoff_buttons(at)
        # The worked example keeps its own download and has no section to sign.
        assert _labels(at) == ["Download PDF"]
        assert not [m for m in at.tabs[0].markdown if "Sign-off" in m.value]

    def test_5b_from_run_to_final(self, downloads, generated):
        at = generated
        live = at.tabs[1]
        result = at.session_state["vc_result"]
        # After the live result, at the level of its sibling sections (####)
        assert [m.value for m in live.markdown if m.value.startswith("#### ")] == [
            "#### Choose a period", "#### Review status", "#### Variance table",
            "#### 12-month trend", "#### Commentary", "#### Sign-off"]
        section = _signoff_section(at)
        assert section == ["#### Sign-off", _SENTENCE, _DRAFT_CHIP,
                           "Outstanding before you sign:", section[4]]
        assert _numbered(section[4]) == result["flags"] == _MARCH_FLAGS
        assert [(t.label, t.help) for t in live.text_input
                if t.key in ("vc_reviewer", "vc_sign")] == [
            ("Reviewer name", ""), (WORD_LABEL, WORD_HELP)]
        (button,) = _signoff_buttons(at)
        assert button.label == "Sign off" and button.proto.type == "primary"
        assert not button.disabled
        captions = [c.value for c in live.caption]
        assert captions.count(SCOPE_NOTE) == 1 and STALE_CAPTION not in captions
        # The live download is the DRAFT PDF; the example keeps "Download PDF".
        assert _labels(live) == ["Download the DRAFT PDF"]
        assert _labels(at.tabs[0]) == ["Download PDF"]
        draft = _pdf_text(downloads(at, "Download the DRAFT PDF"))
        assert draft.index("DRAFT: not signed off") < draft.index("EXECUTIVE SUMMARY")

        # Refused: no name, a wrong word, the word in lower case. Each stays DRAFT.
        for name, word, refusal in [("   ", "SIGN", NAME_REFUSAL),
                                    ("José Núñez", "SIGNED", WORD_REFUSAL),
                                    ("José Núñez", "sign", WORD_REFUSAL)]:
            _sign(at, name, word)
            assert _refusals(at) == [refusal]
            assert _signoff_section(at)[2] == _DRAFT_CHIP
            assert "vc_signed_off" not in at.session_state
            assert "status" not in at.session_state["vc_audit"][0]

        # Signed: FINAL, the signed line, read only, the FINAL PDF
        _sign(at, "José Núñez", " SIGN ")
        signed = at.session_state["vc_signed_off"]
        when = when_text(signed.signed_at)
        line = "Signed off by José Núñez on {}.".format(when)
        assert _signoff_section(at) == [
            "#### Sign-off", _SENTENCE, "{}&nbsp; {}".format(_FINAL_CHIP, line)]
        assert not _refusals(at)
        assert not _boxes(at) and not _signoff_buttons(at)
        assert [c.value for c in at.tabs[1].caption].count(SCOPE_NOTE) == 1
        assert _labels(at.tabs[1]) == ["Download the FINAL PDF"]
        final = _pdf_text(downloads(at, "Download the FINAL PDF"))
        status = "FINAL: signed off by José Núñez on {}".format(when)
        assert final.index(status) < final.index("EXECUTIVE SUMMARY")
        assert "DRAFT: not signed off" not in final

        # The run's session audit row carries the sign-off and the flags shown,
        # and the Session audit list shows it on that row.
        (row,) = at.session_state["vc_audit"]
        assert (row["generated_at"], row["input_hash"]) == (
            result["generated_at"], result["input_hash"])
        assert {k: row[k] for k in ("status", "signed_off_by", "signed_off_at",
                                    "acknowledged_at_sign_off")} == {
            "status": "final", "signed_off_by": "José Núñez",
            "signed_off_at": signed.signed_at.isoformat(),
            "acknowledged_at_sign_off": _MARCH_FLAGS}
        audit = _session_audit(at)
        assert "{}&nbsp; {} Flags acknowledged at sign-off: 4.".format(
            _FINAL_CHIP, line) in [m.value for m in audit.markdown]

    def test_5b_a_second_signoff_is_refused(self, generated):
        at = generated
        _sign(at)
        first = at.session_state["vc_signed_off"]
        # The page offers no second Sign off.
        assert not _signoff_buttons(at) and not _boxes(at)
        # And the rule refuses one: a click that lands while a sign-off for the
        # result on screen already stands.
        _click_generate(at)
        at.text_input(key="vc_sign").input("SIGN").run()
        at.session_state["vc_signed_off"] = first
        at.button(key="vc_signoff").click().run()
        assert not at.exception
        assert _refusals(at) == [ALREADY_SIGNED]
        assert at.session_state["vc_signed_off"] is first
        assert [row.get("status") for row in at.session_state["vc_audit"]] == [None, "final"]

    def test_5b_a_new_run_is_a_new_draft(self, downloads, generated):
        at = generated
        _sign(at, "A. Reviewer")
        first_run = at.session_state["vc_result"]["generated_at"]
        # Generate again on the same inputs: a new result, a new DRAFT
        _click_generate(at)
        assert not at.exception
        assert at.session_state["vc_result"]["generated_at"] != first_run
        section = _signoff_section(at)
        assert section[2] == _DRAFT_CHIP and _numbered(section[4]) == _MARCH_FLAGS
        # The name stays filled in; SIGN must be typed again.
        assert _boxes(at) == [("vc_reviewer", "A. Reviewer"), ("vc_sign", "")]
        assert "vc_signed_off" not in at.session_state
        assert _labels(at.tabs[1]) == ["Download the DRAFT PDF"]
        assert "DRAFT: not signed off" in _pdf_text(downloads(at, "Download the DRAFT PDF"))
        # The sign-off stays on the run it was made for, and the new run signs
        # on its own row.
        rows = at.session_state["vc_audit"]
        assert [(r["generated_at"], r.get("status")) for r in rows] == [
            (at.session_state["vc_result"]["generated_at"], None), (first_run, "final")]
        at.text_input(key="vc_sign").input("SIGN").run()
        at.button(key="vc_signoff").click().run()
        assert [r.get("status") for r in at.session_state["vc_audit"]] == ["final", "final"]

    def test_5b_sign_typed_for_one_result_does_not_carry_to_the_next(self, generated):
        at = generated
        at.text_input(key="vc_reviewer").input("A. Reviewer").run()
        at.text_input(key="vc_sign").input("SIGN").run()
        _click_generate(at)                     # a new result before the click
        assert _boxes(at) == [("vc_reviewer", "A. Reviewer"), ("vc_sign", "")]
        at.button(key="vc_signoff").click().run()
        assert _refusals(at) == [WORD_REFUSAL]

    def test_5b_inputs_changed_since_the_run_wait_for_a_new_run(self, generated):
        at = generated

        def button_and_caption():
            (button,) = _signoff_buttons(at)
            return button.disabled, STALE_CAPTION in [c.value for c in at.tabs[1].caption]

        # A new period on screen, Generate not pressed: the result is stale.
        at.selectbox(key="vc_period").set_value("April 2026").run()
        assert button_and_caption() == (True, True)
        assert _numbered(_signoff_section(at)[4]) == _MARCH_FLAGS   # still March's
        at.selectbox(key="vc_period").set_value("March 2026").run()
        assert button_and_caption() == (False, False)
        # A review threshold changed on screen, and changed back
        at.number_input(key="vc_thr_Revenue").set_value(20.0).run()
        assert button_and_caption() == (True, True)
        at.number_input(key="vc_thr_Revenue").set_value(10.0).run()
        assert button_and_caption() == (False, False)

        # Signed, then the period changed: the signed result is still the one
        # on screen, so it stays FINAL; the next Generate is a new DRAFT.
        _sign(at, "A. Reviewer")
        at.selectbox(key="vc_period").set_value("April 2026").run()
        assert _signoff_section(at)[2].startswith(_FINAL_CHIP)
        assert STALE_CAPTION not in [c.value for c in at.tabs[1].caption]
        _click_generate(at)
        assert at.session_state["vc_result"]["period"] == "April 2026"
        assert _signoff_section(at)[2:4] == [_DRAFT_CHIP, "Nothing is outstanding."]
        assert button_and_caption() == (False, False)
        assert _boxes(at) == [("vc_reviewer", "A. Reviewer"), ("vc_sign", "")]

    def test_5b_a_new_key_alone_changes_nothing(self, generated):
        # The key is not an input of the result: a new key on its own neither
        # makes it stale nor undoes a sign-off. Only a new Generate does.
        at = generated
        other_key = "sk-ant-api03-" + "y" * 90
        at.sidebar.text_input(key="byo_api_key").input(other_key).run()
        (button,) = _signoff_buttons(at)
        assert not button.disabled and _signoff_section(at)[2] == _DRAFT_CHIP
        _sign(at)
        at.sidebar.text_input(key="byo_api_key").input(TEST_KEY).run()
        assert _signoff_section(at)[2].startswith(_FINAL_CHIP)
        at.sidebar.text_input(key="byo_api_key").input("").run()
        assert _signoff_section(at)[2].startswith(_FINAL_CHIP)
        assert "vc_signed_off" in at.session_state

    def test_5b_nothing_outstanding(self, stand_in_model):
        at = _live_page()
        at.selectbox(key="vc_period").set_value("January 2026").run()
        _click_generate(at)
        assert _signoff_section(at) == [
            "#### Sign-off", _SENTENCE, _DRAFT_CHIP, "Nothing is outstanding."]
        _sign(at)
        assert at.session_state["vc_audit"][0]["acknowledged_at_sign_off"] == []
        audit = _session_audit(at)
        assert any(m.value.endswith("Flags acknowledged at sign-off: 0.")
                   for m in audit.markdown)

    def test_5b_names_print_safely(self, downloads, generated):
        at = generated
        typed = "Zoë 李 <b>R&D</b>\x07" + "x" * 100
        _sign(at, typed)
        signed = at.session_state["vc_signed_off"]
        assert signed.name == clean_name(typed) and len(signed.name) == NAME_LIMIT
        assert signed.name.startswith("Zoë 李 <b>R&D</b>xxx")
        # On screen as typed, escaped; in the PDF as its fonts print it, never as markup
        assert _signoff_section(at)[2] == "{}&nbsp; {}".format(
            _FINAL_CHIP, html.escape(signed.line))
        final = "".join(_pdf_text(downloads(at, "Download the FINAL PDF")).split())
        status = "FINAL: signed off by {} on {}".format(
            pdf_name(signed.name), when_text(signed.signed_at))
        assert status.startswith("FINAL: signed off by Zoë ? <b>R&D</b>xxx")
        assert "".join(status.split()) in final

    def test_5b_worked_example_and_cli_pdfs_have_no_status_line(
            self, downloads, tmp_dirs, mock_commentary, loaded_pipeline):
        # The worked example's PDF is built as before: no keyword, no status line.
        at = AppTest.from_file(str(APP_HOME), default_timeout=120).run()
        at.switch_page("views/variance_commentary.py").run()
        shown = _pdf_text(downloads(at, "Download PDF"))
        ex = load_example()
        args = (ex["commentary"], ex["df"], ex["flags"], ex["input_tokens"],
                ex["output_tokens"], ex["period"], ex["entity"], ex["generated_at"])
        kwargs = dict(policy_note_text=policy_note(ex["policy"]),
                      df_12mo=load_pnl(DOCS_DIR.parent / "data" / "sample_pnl.csv"))
        assert shown == _pdf_text(build_pdf_bytes(*args, **kwargs))
        assert "DRAFT:" not in shown and "FINAL:" not in shown
        # The status line is the only thing the keyword adds, under the cover.
        with_line = _pdf_text(build_pdf_bytes(*args, **kwargs,
                                              status_line="DRAFT: not signed off"))
        assert with_line.replace(" DRAFT: not signed off", "", 1) == shown
        assert with_line.index("DRAFT: not signed off") < with_line.index(
            "EXECUTIVE SUMMARY")
        # The CLI's PDF (write_pdf) carries no status line either.
        df, flags = loaded_pipeline
        cli = _pdf_text(write_pdf(mock_commentary, df, flags, 895, 1114).read_bytes())
        assert "DRAFT:" not in cli and "FINAL:" not in cli

    def test_5b_wording(self):
        at = AppTest.from_file(str(APP_HOME), default_timeout=120).run()
        values = [m.value for m in at.main.markdown]
        what = values[values.index("#### What it does") + 1]
        promise = values[values.index("#### The governance promise") + 1]
        assert what.splitlines()[-1] == (
            "- Produces a PDF of the figures, the flags and the commentary, a DRAFT "
            "until a named reviewer signs it.")
        assert promise.splitlines()[-1] == (
            "- **The reviewer signs.** Nothing is final until a named reviewer reads "
            "it and signs.")
        at.switch_page("views/how_its_built.py").run()
        assert any("This live demo stops at a typed sign-off kept for the session; it "
                   "does not store or lock anything" in m.value for m in at.markdown)
        stale = ["stops at flagging for review", "no sign-off step", "nobody approves",
                 "nothing here is signed or final", "A person reviews",
                 "before the accounts can be signed off"]
        root = APP_DIR.parent
        for path in [root / "README.md", *APP_DIR.rglob("*.py"), *(root / "src").glob("*.py")]:
            text = path.read_text(encoding="utf-8")
            assert not [s for s in stale if s in text], path.name


# =============================================================================
# STEP 6c: the How it's built diagrams, readable on a phone
# =============================================================================
# The three diagrams were SVG in fixed-height frames, so on a phone their text
# shrank to about 4 px and a blank gap followed. They are now HTML lists drawn
# by lib/flow_diagram.py: a row of boxes from 640 px, stacked below that. These
# tests read the page as AppTest renders it and check each diagram's words, its
# accessible name (the old SVG's aria-label) and the order of its stages.

from html.parser import HTMLParser

GOVERNANCE_FLOW = {
    "label": "How a run is governed: you pick a period, Python computes every "
             "variance and checks each line against its threshold, the model reads "
             "the figures and writes the commentary, Python marks any run that needs "
             "a human, and you review what is flagged. Every run is written to the "
             "audit record with a hash of the input data.",
    "head": "You open and close every run. The model works only in between.",
    "stages": [
        ("YOU PICK A PERIOD", "A month to report on", "the person"),
        ("PYTHON COMPUTES", "Every variance, checks thresholds", "no model here"),
        ("THE MODEL WRITES", "Reads the figures, writes commentary", "words, not numbers"),
        ("MARKED FOR REVIEW", "Python flags what needs a human", "no model here"),
        ("YOU REVIEW", "You check the flagged lines", "the person"),
    ],
    "note": "Every run is written to the audit record, with a hash of the input "
            "data, so it can be traced and reproduced.",
    "key": ["You", "The model, for language", "Deterministic code, for numbers"],
}
LIFECYCLE = {
    "label": "The governance lifecycle: you review the flagged output, approve the "
             "report, the approved version is locked and becomes immutable, everyone "
             "reads the locked record, and a change requires a new separately "
             "approved version.",
    "head": "Review is the start of the record, not the end.",
    "stages": [
        ("YOU REVIEW", "Check the flagged output and data", "the person"),
        ("YOU APPROVE", "Sign off the report as final", "the person"),
        ("LOCKED", "The approved report becomes immutable", "the record"),
        ("READ ONLY", "Everyone reads it, no one edits it", "the record"),
        ("RE-ISSUE", "A new version; the original still stands", "the person"),
    ],
    "note": "The live demo stops at a typed sign-off. The stages beyond show the "
            "production model this design is built towards.",
    "key": ["You", "The immutable record"],
}
PIPELINE = {
    "label": "The pipeline: a deterministic loader reads the profit-and-loss data and "
             "scopes it to the chosen period; a deterministic validator checks every "
             "line for the five flag conditions and applies the per-line thresholds; "
             "a deterministic calculator computes the variances and leaves flagged "
             "lines uncomputed; the model reads the computed figures and writes the "
             "commentary; and a deterministic output layer writes the PDF, the data "
             "hash, and the audit record. Only the commentary stage uses the model; "
             "everything numeric is deterministic.",
    "head": "The model appears in one stage only. Everything numeric is deterministic.",
    "stages": [
        ("Load", "read P&L, scope to month", "deterministic"),
        ("Validate", "five checks, thresholds", "deterministic"),
        ("Compute", "variances, skip flagged", "deterministic"),
        ("Commentary", "figures to words", "model, language"),
        ("Output", "PDF, hash, audit record", "deterministic"),
    ],
    "note": "The commentary stage is handed already-final figures; the model has "
            "nothing to calculate with.",
    "key": ["Model, for language", "Deterministic code, for numbers"],
}


class _Diagram(HTMLParser):
    """One flow diagram's HTML read back: the list's accessible name, the
    heading, the note, the colour key, and each stage's parts by class."""

    def __init__(self, markup):
        super().__init__()
        self.label, self.head, self.note, self.key, self.stages = None, None, None, [], []
        self._open = []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = (attrs.get("class") or "").split()
        if tag == "ol" and "fd-flow" in classes:
            self.label = attrs.get("aria-label")
        if tag == "li" and "fd-stage" in classes:
            self.stages.append({"cross": "fd-cross" in classes})
        self._open.append(classes)

    def handle_endtag(self, tag):
        self._open.pop()

    def handle_data(self, data):
        words, classes = data.strip(), self._open[-1] if self._open else []
        if not words:
            return
        if ["fd-key"] in self._open:
            self.key.append(words)
        elif "fd-head" in classes:
            self.head = words
        elif "fd-note" in classes:
            self.note = words
        elif classes and classes[0] in ("fd-zone", "fd-title", "fd-text", "fd-foot"):
            self.stages[-1][classes[0]] = words


@pytest.fixture(scope="class")
def how_its_built():
    """The How it's built page as AppTest renders it, and its flow diagrams read
    back in page order, each with its place among the page's markdown."""
    at = AppTest.from_file(str(APP_HOME), default_timeout=120).run()
    at.switch_page("views/how_its_built.py").run()
    assert not at.exception
    flows = [(i, _Diagram(m.value)) for i, m in enumerate(at.main.markdown)
             if m.value.startswith('<figure class="fd">')]
    return at, flows


def _check_flow(flow, expected):
    """A diagram has the expected words, and its stages in the expected order."""
    assert flow.label == expected["label"]
    assert flow.head == expected["head"]
    assert [(s["fd-title"], s["fd-text"], s["fd-foot"]) for s in flow.stages] == \
        expected["stages"]
    assert flow.note == expected["note"]
    assert flow.key == expected["key"]


class TestStep6cDiagrams:

    def test_6c_diagrams_are_html_lists_not_frames(self, how_its_built):
        at, flows = how_its_built
        assert not at.get("iframe"), "no fixed-height frame left on the page"
        assert len(flows) == 3, "the three diagrams are HTML lists on the page"
        # Each sits where its frame was: just under its lead-in, in page order
        values = [m.value for m in at.main.markdown]
        leads = ["**The work happens in separated layers.**",
                 "#### The governance lifecycle", "**The pipeline.**"]
        assert [i for i, _ in flows] == [values.index(lead) + 1 for lead in leads]
        # The CSS is in inject_css: stacked on a phone, a row from 640 px, and
        # no text in a diagram under 13 px
        from streamlit_app.lib import flow_diagram
        flow_css = flow_diagram.flow_css(theme.DARK_BLUE, theme.MUTED, theme.RULE)
        assert flow_css in inject_css()
        assert "@media (min-width: 640px)" in flow_css and "ol.fd-flow" in flow_css
        sizes = [int(s) for s in re.findall(r"font-size: (\d+)px", flow_css)]
        assert sizes and min(sizes) >= 13
        # The renderer imports nothing from an app, so it copies byte for byte
        source = Path(flow_diagram.__file__).read_text(encoding="utf-8")
        assert "import streamlit_app" not in source and "from streamlit_app" not in source

    def test_6c_governance_flow_stages_in_order(self, how_its_built):
        _, flows = how_its_built
        assert len(flows) == 3, "the three diagrams are HTML lists on the page"
        flow = flows[0][1]
        _check_flow(flow, GOVERNANCE_FLOW)
        assert not any(s["cross"] for s in flow.stages)

    def test_6c_lifecycle_stages_in_order_with_the_demo_boundary(self, how_its_built):
        _, flows = how_its_built
        assert len(flows) == 3, "the three diagrams are HTML lists on the page"
        flow = flows[1][1]
        _check_flow(flow, LIFECYCLE)
        titles = [s["fd-title"] for s in flow.stages]
        assert "YOU APPROVE" in titles and "LOCKED" in titles
        # The live demo ends after YOU REVIEW: the boundary sits just before YOU
        # APPROVE, with a label for the zone on each side
        assert [s["cross"] for s in flow.stages] == [False, True, False, False, False]
        assert [(s.get("fd-zone"), s["fd-title"]) for s in flow.stages[:2]] == [
            ("Live demo", "YOU REVIEW"), ("Production workflow", "YOU APPROVE")]
        assert all("fd-zone" not in s for s in flow.stages[2:])

    def test_6c_pipeline_stages_in_order(self, how_its_built):
        _, flows = how_its_built
        assert len(flows) == 3, "the three diagrams are HTML lists on the page"
        flow = flows[2][1]
        _check_flow(flow, PIPELINE)
        # The model appears in exactly one stage
        assert [s["fd-foot"] for s in flow.stages].count("model, language") == 1
        assert not any(s["cross"] for s in flow.stages)

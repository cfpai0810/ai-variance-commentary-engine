# =============================================================================
# tests/test_pipeline.py : Project 1: AI Variance Commentary Engine
# =============================================================================
# Phase 5: VALIDATE — The 6-Case Test Protocol
#
# Run from the project root with (venv) active:
#   pytest tests/test_pipeline.py -v
#
# All 6 test cases from the methodology:
#   1. Happy path          — clean data, full pipeline, audit log correct
#   2. Favourable variance — green dot for revenue over, cost under
#   3. Unfavourable variance — red dot for cost over, revenue under
#   4. Missing value       — Admin actual NaN, MISSING_ACTUAL flag, skipped
#   5. Zero actual         — Technology actual=0, ZERO_ACTUAL not LARGE_VARIANCE
#   6. Large variance      — Product +122.5%, LARGE_VARIANCE flag, skipped
#
# No real API calls are made. The Claude API call is mocked so the
# tests run in under 5 seconds and cost nothing.
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
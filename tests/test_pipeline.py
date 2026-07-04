# =============================================================================
# tests/test_pipeline.py — Project 1: AI Variance Commentary Engine
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

from src.step1_data_loader   import load_pnl, validate_and_flag, calculate_variances
from src.step3_output_writer import (
    get_status, clean_markdown, extract_label,
    parse_sections, write_output, write_pdf,
    GREEN, FLAG_RED, AMBER, MUTED,
)
from config import LARGE_VARIANCE_THRESHOLD


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
    """
    df        = load_pnl(sample_csv)
    df, flags = validate_and_flag(df)
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
        "Sales — Revenue: Revenue of EUR 1,250,000 exceeded budget by EUR 150,000 "
        "(+13.6%). Growth against prior year stands at +19.0%. No corrective "
        "action required.\n\n"
        "Operations — COGS: COGS of EUR 480,000 exceeded budget by EUR 60,000 "
        "(+14.3%). Year-on-year growth outpaces revenue growth. Operations to "
        "provide a unit cost breakdown.\n\n"
        "**Technology — IT Infrastructure:** [FLAG: ZERO_ACTUAL — Actual EUR 0 "
        "against budget EUR 45,000. Requires immediate clarification.]\n\n"
        "**Admin — Legal & Compliance:** [FLAG: MISSING_ACTUAL — No actual "
        "submitted against budget EUR 25,000.]\n\n"
        "**Product — R&D Expense:** [FLAG: LARGE_VARIANCE — Actual EUR 890,000 "
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

    def test_raises_exactly_three_flags(self, loaded_pipeline):
        _, flags = loaded_pipeline
        assert len(flags) == 3

    def test_four_variances_calculated(self, loaded_pipeline):
        df, _ = loaded_pipeline
        assert df["variance_abs"].notna().sum() == 4

    def test_three_rows_skipped(self, loaded_pipeline):
        df, _ = loaded_pipeline
        assert df["variance_abs"].isna().sum() == 3

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

    def test_sales_variance_abs(self, loaded_pipeline):
        df, _ = loaded_pipeline
        sales = df[df["department"] == "Sales"].iloc[0]
        assert sales["variance_abs"] == 150000.0

    def test_sales_variance_pct(self, loaded_pipeline):
        df, _ = loaded_pipeline
        sales = df[df["department"] == "Sales"].iloc[0]
        assert abs(sales["variance_pct"] - 0.136) < 0.001

    def test_sales_prior_year_pct(self, loaded_pipeline):
        df, _ = loaded_pipeline
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
# ADDITIONAL UTILITY TESTS
# =============================================================================

class TestUtilityFunctions:

    def test_clean_markdown_removes_bold(self):
        assert clean_markdown("**bold**") == "bold"

    def test_clean_markdown_removes_heading(self):
        assert clean_markdown("## Heading") == "Heading"

    def test_clean_markdown_removes_rule(self):
        assert clean_markdown("---") == ""

    def test_clean_markdown_removes_bullet(self):
        assert clean_markdown("* item") == "item"

    def test_clean_markdown_preserves_content(self):
        result = clean_markdown("**Sales — Revenue:** text here")
        assert "Sales" in result
        assert "text here" in result
        assert "**" not in result

    def test_extract_label_standard_line(self):
        label, body = extract_label("Sales — Revenue: exceeded budget.")
        assert label == "Sales — Revenue"
        assert "exceeded budget" in body

    def test_extract_label_flagged_line(self):
        line = clean_markdown("**Technology — IT Infrastructure:** [FLAG: ZERO_ACTUAL]")
        label, body = extract_label(line)
        assert label == "Technology — IT Infrastructure"
        assert "[FLAG:" in body
        assert "[FLAG" not in label

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
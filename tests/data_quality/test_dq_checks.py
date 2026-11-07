"""
PaymentPulse — Data Quality Integration Tests
=============================================
Runs the full DQ check suite against a real (small) pipeline run.
Verifies that DQ results structure is correct and quality score is > 0.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from paymentpulse.controls.controls import run_controls
from paymentpulse.generator.generate import generate
from paymentpulse.ingestion.ingest import ingest
from paymentpulse.quality.checks import run_dq_checks
from paymentpulse.warehouse.warehouse import build_warehouse


@pytest.fixture(scope="module")
def full_pipeline(tmp_path_factory):
    """Run a complete small pipeline once for all DQ integration tests."""
    tmp_path = tmp_path_factory.mktemp("dq_integration")

    cfg = {
        "dataset": {"num_transactions": 500, "num_customers": 30, "num_merchants": 10, "random_seed": 99},
        "dq_injection": {
            "null_customer_id": 0.02,
            "null_amount": 0.02,
            "duplicate_transaction_id": 0.02,
            "invalid_currency": 0.02,
            "invalid_status": 0.02,
            "orphan_customer_id": 0.02,
            "orphan_merchant_id": 0.02,
            "malformed_timestamp": 0.02,
            "future_timestamp": 0.01,
            "negative_amount": 0.01,
        },
        "paths": {
            "raw_dir": str(tmp_path / "raw"),
            "processed_dir": str(tmp_path / "processed"),
            "quarantine_dir": str(tmp_path / "quarantine"),
            "db_path": str(tmp_path / "test.duckdb"),
        },
        "payment_methods": ["credit_card", "debit_card", "bank_transfer",
                            "digital_wallet", "buy_now_pay_later",
                            "direct_debit", "standing_order", "faster_payments"],
        "valid_statuses": ["INITIATED", "SUCCESS", "FAILED", "PENDING", "REVERSED"],
        "valid_currencies": ["GBP", "USD", "EUR", "AUD", "CAD"],
        "channels": ["online", "mobile", "branch"],
        "device_types": ["desktop", "mobile", "tablet", "unknown"],
        "customer_segments": ["retail", "premium", "business", "student", "private_banking"],
        "merchant_categories": ["retail", "food_and_beverage", "travel"],
        "merchant_risk_categories": ["low", "medium", "high"],
        "controls": {"max_transaction_amount": 1000000, "freshness_sla_hours": 24,
                     "volume_anomaly_threshold": 0.30},
        "dq_thresholds": {"warn_failure_rate": 0.01, "fail_failure_rate": 0.05},
        "ingestion": {"schema_version": "1.0", "expected_columns": []},
    }

    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(cfg, f)

    gen = generate(config_path=config_path)
    batch_id = gen["batch_id"]
    db_path = cfg["paths"]["db_path"]

    ingest(
        transactions_path=gen["transactions_path"],
        customers_path=gen["customers_path"],
        merchants_path=gen["merchants_path"],
        batch_id=batch_id,
        config_path=config_path,
        db_path=db_path,
    )
    wh = build_warehouse(batch_id=batch_id, config_path=config_path, db_path=db_path)

    dq = run_dq_checks(config_path=config_path, db_path=db_path, baseline_txn_count=500)
    ctrl = run_controls(batch_id=batch_id, config_path=config_path, db_path=db_path)

    return {
        "batch_id": batch_id,
        "db_path": db_path,
        "config_path": config_path,
        "gen": gen,
        "wh": wh,
        "dq": dq,
        "ctrl": ctrl,
    }


class TestDQReportStructure:

    def test_dq_results_is_list(self, full_pipeline: dict) -> None:
        assert isinstance(full_pipeline["dq"]["results"], list)

    def test_dq_result_has_required_keys(self, full_pipeline: dict) -> None:
        required_keys = {
            "dataset", "check_name", "check_type", "records_checked",
            "records_failed", "failure_rate", "status", "execution_timestamp",
        }
        for r in full_pipeline["dq"]["results"]:
            assert required_keys.issubset(set(r.keys())), f"Missing keys in: {r}"

    def test_dq_status_values_valid(self, full_pipeline: dict) -> None:
        valid_statuses = {"PASS", "WARN", "FAIL"}
        for r in full_pipeline["dq"]["results"]:
            assert r["status"] in valid_statuses, f"Invalid status: {r['status']}"

    def test_quality_score_in_range(self, full_pipeline: dict) -> None:
        score = full_pipeline["dq"]["quality_score"]
        assert 0.0 <= score <= 100.0, f"Score out of range: {score}"

    def test_quality_score_positive(self, full_pipeline: dict) -> None:
        """With DQ problems injected, score should be < 100 but > 0."""
        score = full_pipeline["dq"]["quality_score"]
        assert score > 0.0


class TestWarehouseCounts:

    def test_silver_count_less_than_raw(self, full_pipeline: dict) -> None:
        silver_count = full_pipeline["wh"]["silver"]["silver_count"]
        raw_count = full_pipeline["gen"]["num_transactions"]
        assert silver_count < raw_count, "Silver should be smaller than raw due to quarantine"

    def test_quarantine_count_positive(self, full_pipeline: dict) -> None:
        q_count = full_pipeline["wh"]["silver"]["quarantine_count"]
        assert q_count > 0, "With DQ injection, at least some records should be quarantined"

    def test_gold_fact_matches_silver(self, full_pipeline: dict) -> None:
        silver = full_pipeline["wh"]["silver"]["silver_count"]
        gold = full_pipeline["wh"]["gold"]["fact_transactions"]
        assert gold == silver, "Gold fact count should equal Silver (all silver rows promoted)"


class TestControlsReport:

    def test_controls_results_is_list(self, full_pipeline: dict) -> None:
        assert isinstance(full_pipeline["ctrl"]["results"], list)

    def test_seven_controls_run(self, full_pipeline: dict) -> None:
        assert len(full_pipeline["ctrl"]["results"]) == 7

    def test_control_ids_present(self, full_pipeline: dict) -> None:
        ids = {r["control_id"] for r in full_pipeline["ctrl"]["results"]}
        expected = {"CTL-01", "CTL-02", "CTL-03", "CTL-04", "CTL-05", "CTL-06", "CTL-07"}
        assert ids == expected

    def test_ctl_01_uniqueness_passes(self, full_pipeline: dict) -> None:
        """Silver deduplication should ensure Gold has no duplicates."""
        ctl_01 = next(r for r in full_pipeline["ctrl"]["results"] if r["control_id"] == "CTL-01")
        assert ctl_01["status"] == "PASS", f"CTL-01 failed: {ctl_01['detail']}"

    def test_ctl_07_reconciliation_passes(self, full_pipeline: dict) -> None:
        """Every raw record must end up in Silver or Quarantine — no silent loss."""
        ctl_07 = next(r for r in full_pipeline["ctrl"]["results"] if r["control_id"] == "CTL-07")
        assert ctl_07["status"] == "PASS", f"CTL-07 (reconciliation) failed: {ctl_07['detail']}"

    def test_ctl_06_schema_passes(self, full_pipeline: dict) -> None:
        ctl_06 = next(r for r in full_pipeline["ctrl"]["results"] if r["control_id"] == "CTL-06")
        assert ctl_06["status"] == "PASS", f"CTL-06 (schema) failed: {ctl_06['detail']}"

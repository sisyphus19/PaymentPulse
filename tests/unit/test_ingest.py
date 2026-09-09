"""
PaymentPulse — Unit Tests: Ingestion Layer
==========================================
Tests schema validation and the ingest() function.
Verifies idempotency (re-running doesn't duplicate data).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from paymentpulse.ingestion.ingest import ingest, validate_schema


class TestSchemaValidation:
    """Tests for validate_schema()."""

    def test_valid_transactions_schema(self) -> None:
        df = pd.DataFrame(columns=[
            "transaction_id", "customer_id", "merchant_id", "payment_method",
            "timestamp", "amount", "currency", "country", "channel",
            "device_type", "status", "batch_id",
        ])
        is_valid, missing = validate_schema(df, "transactions")
        assert is_valid
        assert missing == []

    def test_invalid_transactions_schema_missing_cols(self) -> None:
        df = pd.DataFrame(columns=["transaction_id", "amount"])  # missing many cols
        is_valid, missing = validate_schema(df, "transactions")
        assert not is_valid
        assert len(missing) > 0

    def test_valid_customers_schema(self) -> None:
        df = pd.DataFrame(columns=[
            "customer_id", "name", "email", "segment", "country", "customer_since",
        ])
        is_valid, missing = validate_schema(df, "customers")
        assert is_valid

    def test_valid_merchants_schema(self) -> None:
        df = pd.DataFrame(columns=[
            "merchant_id", "name", "category", "country", "risk_category",
        ])
        is_valid, missing = validate_schema(df, "merchants")
        assert is_valid

    def test_unknown_table_returns_valid(self) -> None:
        """Unknown table has no expected schema, so validation passes."""
        df = pd.DataFrame(columns=["col1"])
        is_valid, missing = validate_schema(df, "unknown_table")
        assert is_valid
        assert missing == []


@pytest.fixture()
def pipeline_config_and_data(tmp_path: Path):
    """Set up a minimal config + CSV files for ingestion tests."""
    cfg = {
        "dataset": {"num_transactions": 100, "num_customers": 10, "num_merchants": 5, "random_seed": 42},
        "dq_injection": {k: 0.0 for k in [
            "null_customer_id", "null_amount", "duplicate_transaction_id",
            "invalid_currency", "invalid_status", "orphan_customer_id",
            "orphan_merchant_id", "malformed_timestamp", "future_timestamp", "negative_amount",
        ]},
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
        "valid_currencies": ["GBP", "USD", "EUR"],
        "channels": ["online", "mobile"],
        "device_types": ["desktop", "mobile"],
        "customer_segments": ["retail", "premium"],
        "merchant_categories": ["retail", "travel"],
        "merchant_risk_categories": ["low", "medium", "high"],
        "controls": {"max_transaction_amount": 1000000, "freshness_sla_hours": 24,
                     "volume_anomaly_threshold": 0.30},
        "dq_thresholds": {"warn_failure_rate": 0.01, "fail_failure_rate": 0.05},
        "ingestion": {"schema_version": "1.0", "expected_columns": []},
    }

    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(cfg, f)

    # Generate minimal CSVs
    from paymentpulse.generator.generate import generate
    result = generate(config_path=config_path)

    return {
        "config_path": config_path,
        "db_path": str(tmp_path / "test.duckdb"),
        "transactions_path": result["transactions_path"],
        "customers_path": result["customers_path"],
        "merchants_path": result["merchants_path"],
        "batch_id": result["batch_id"],
    }


class TestIngestion:
    """Tests for ingest()."""

    def test_ingestion_returns_success(self, pipeline_config_and_data: dict) -> None:
        d = pipeline_config_and_data
        result = ingest(
            transactions_path=d["transactions_path"],
            customers_path=d["customers_path"],
            merchants_path=d["merchants_path"],
            batch_id=d["batch_id"],
            config_path=d["config_path"],
            db_path=d["db_path"],
        )
        assert result["transactions"]["status"] == "SUCCESS"
        assert result["customers"]["status"] == "SUCCESS"
        assert result["merchants"]["status"] == "SUCCESS"

    def test_ingestion_record_count(self, pipeline_config_and_data: dict) -> None:
        import duckdb
        d = pipeline_config_and_data
        ingest(
            transactions_path=d["transactions_path"],
            customers_path=d["customers_path"],
            merchants_path=d["merchants_path"],
            batch_id=d["batch_id"],
            config_path=d["config_path"],
            db_path=d["db_path"],
        )
        con = duckdb.connect(d["db_path"], read_only=True)
        count = con.execute(
            "SELECT COUNT(*) FROM bronze.raw_transactions WHERE batch_id = ?",
            [d["batch_id"]],
        ).fetchone()[0]
        con.close()
        assert count == 100  # matches config num_transactions

    def test_ingestion_idempotency(self, pipeline_config_and_data: dict) -> None:
        """Running ingest twice with the same batch_id must not duplicate records."""
        import duckdb
        d = pipeline_config_and_data
        for _ in range(2):
            ingest(
                transactions_path=d["transactions_path"],
                customers_path=d["customers_path"],
                merchants_path=d["merchants_path"],
                batch_id=d["batch_id"],
                config_path=d["config_path"],
                db_path=d["db_path"],
            )
        con = duckdb.connect(d["db_path"], read_only=True)
        count = con.execute(
            "SELECT COUNT(*) FROM bronze.raw_transactions WHERE batch_id = ?",
            [d["batch_id"]],
        ).fetchone()[0]
        con.close()
        assert count == 100, f"Expected 100 rows after re-run, got {count}"

    def test_audit_table_populated(self, pipeline_config_and_data: dict) -> None:
        import duckdb
        d = pipeline_config_and_data
        ingest(
            transactions_path=d["transactions_path"],
            customers_path=d["customers_path"],
            merchants_path=d["merchants_path"],
            batch_id=d["batch_id"],
            config_path=d["config_path"],
            db_path=d["db_path"],
        )
        con = duckdb.connect(d["db_path"], read_only=True)
        audit_count = con.execute(
            "SELECT COUNT(*) FROM bronze.ingestion_audit WHERE batch_id = ?",
            [d["batch_id"]],
        ).fetchone()[0]
        con.close()
        assert audit_count == 3  # one audit row per table (transactions, customers, merchants)

    def test_schema_error_detected(self, tmp_path: Path, pipeline_config_and_data: dict) -> None:
        """A CSV missing required columns should produce a SCHEMA_ERROR status."""
        bad_csv = tmp_path / "bad_transactions.csv"
        # Write a CSV with only 2 columns — missing most required fields
        bad_csv.write_text("transaction_id,amount\ntxn-001,100.0\n")
        d = pipeline_config_and_data
        result = ingest(
            transactions_path=str(bad_csv),
            customers_path=d["customers_path"],
            merchants_path=d["merchants_path"],
            batch_id="bad-batch-123",
            config_path=d["config_path"],
            db_path=d["db_path"],
        )
        assert result["transactions"]["status"] == "SCHEMA_ERROR"

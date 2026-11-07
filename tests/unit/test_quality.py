"""
PaymentPulse — Unit Tests: Data Quality Framework
==================================================
Tests individual DQ check functions and the aggregate quality score.
Verifies PASS/WARN/FAIL thresholds behave correctly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from paymentpulse.quality.checks import (
    DQResult,
    check_amount_positive,
    check_not_null,
    check_uniqueness,
    check_valid_values,
    compute_quality_score,
)


@pytest.fixture()
def in_memory_db():
    """Create an in-memory DuckDB with minimal Silver schema for testing."""
    con = duckdb.connect(":memory:")
    con.execute("CREATE SCHEMA IF NOT EXISTS silver")
    con.execute("""
        CREATE TABLE silver.transactions (
            transaction_id  VARCHAR,
            customer_id     VARCHAR,
            merchant_id     VARCHAR,
            payment_method  VARCHAR,
            ts              TIMESTAMP,
            amount          DOUBLE,
            currency        VARCHAR,
            country         VARCHAR,
            channel         VARCHAR,
            device_type     VARCHAR,
            status          VARCHAR,
            batch_id        VARCHAR
        )
    """)
    return con


def _load_test_data(con: duckdb.DuckDBPyConnection, rows: list[dict]) -> None:
    df = pd.DataFrame(rows)  # noqa: F841 - queried by DuckDB
    con.execute("DELETE FROM silver.transactions")
    con.execute("INSERT INTO silver.transactions SELECT * FROM df")


class TestNotNullCheck:

    def test_all_non_null_passes(self, in_memory_db) -> None:
        _load_test_data(in_memory_db, [
            {"transaction_id": "t1", "customer_id": "c1", "merchant_id": "m1",
             "payment_method": "credit_card", "ts": "2024-01-01 10:00:00",
             "amount": 100.0, "currency": "GBP", "country": "GB",
             "channel": "online", "device_type": "desktop", "status": "SUCCESS",
             "batch_id": "b1"},
        ])
        result = check_not_null(in_memory_db, "silver.transactions", "transaction_id", 0.01, 0.05)
        assert result.status == "PASS"
        assert result.records_failed == 0

    def test_null_values_warn(self, in_memory_db) -> None:
        rows = []
        for i in range(100):
            rows.append({
                "transaction_id": f"t{i}" if i < 97 else None,
                "customer_id": "c1", "merchant_id": "m1",
                "payment_method": "credit_card", "ts": "2024-01-01 10:00:00",
                "amount": 100.0, "currency": "GBP", "country": "GB",
                "channel": "online", "device_type": "desktop",
                "status": "SUCCESS", "batch_id": "b1",
            })
        _load_test_data(in_memory_db, rows)
        # 3% null rate → above warn (1%) but below fail (5%) → WARN
        result = check_not_null(in_memory_db, "silver.transactions", "transaction_id", 0.01, 0.05)
        assert result.status == "WARN"

    def test_high_null_rate_fails(self, in_memory_db) -> None:
        rows = [
            {"transaction_id": None if i % 2 == 0 else f"t{i}",
             "customer_id": "c1", "merchant_id": "m1",
             "payment_method": "credit_card", "ts": "2024-01-01 10:00:00",
             "amount": 100.0, "currency": "GBP", "country": "GB",
             "channel": "online", "device_type": "desktop",
             "status": "SUCCESS", "batch_id": "b1"}
            for i in range(20)
        ]
        _load_test_data(in_memory_db, rows)
        # 50% null → FAIL
        result = check_not_null(in_memory_db, "silver.transactions", "transaction_id", 0.01, 0.05)
        assert result.status == "FAIL"


class TestUniquenessCheck:

    def test_all_unique_passes(self, in_memory_db) -> None:
        rows = [
            {"transaction_id": f"t{i}", "customer_id": "c1", "merchant_id": "m1",
             "payment_method": "credit_card", "ts": "2024-01-01 10:00:00",
             "amount": 100.0, "currency": "GBP", "country": "GB",
             "channel": "online", "device_type": "desktop",
             "status": "SUCCESS", "batch_id": "b1"}
            for i in range(10)
        ]
        _load_test_data(in_memory_db, rows)
        result = check_uniqueness(in_memory_db, "silver.transactions", "transaction_id", 0.0, 0.0)
        assert result.status == "PASS"
        assert result.records_failed == 0

    def test_duplicates_detected(self, in_memory_db) -> None:
        rows = [
            {"transaction_id": "DUPLICATE", "customer_id": "c1", "merchant_id": "m1",
             "payment_method": "credit_card", "ts": "2024-01-01 10:00:00",
             "amount": 100.0, "currency": "GBP", "country": "GB",
             "channel": "online", "device_type": "desktop",
             "status": "SUCCESS", "batch_id": "b1"},
            {"transaction_id": "DUPLICATE", "customer_id": "c2", "merchant_id": "m1",
             "payment_method": "credit_card", "ts": "2024-01-01 11:00:00",
             "amount": 200.0, "currency": "GBP", "country": "GB",
             "channel": "online", "device_type": "desktop",
             "status": "SUCCESS", "batch_id": "b1"},
        ]
        _load_test_data(in_memory_db, rows)
        # Threshold 0/0: any duplicate → FAIL
        result = check_uniqueness(in_memory_db, "silver.transactions", "transaction_id", 0.0, 0.0)
        assert result.status == "FAIL"
        assert result.records_failed > 0


class TestAmountCheck:

    def test_positive_amounts_pass(self, in_memory_db) -> None:
        rows = [
            {"transaction_id": f"t{i}", "customer_id": "c1", "merchant_id": "m1",
             "payment_method": "credit_card", "ts": "2024-01-01 10:00:00",
             "amount": float(i + 1), "currency": "GBP", "country": "GB",
             "channel": "online", "device_type": "desktop",
             "status": "SUCCESS", "batch_id": "b1"}
            for i in range(10)
        ]
        _load_test_data(in_memory_db, rows)
        result = check_amount_positive(in_memory_db, "silver.transactions", 0.01, 0.05)
        assert result.status == "PASS"

    def test_negative_amount_flagged(self, in_memory_db) -> None:
        rows = [
            {"transaction_id": "t1", "customer_id": "c1", "merchant_id": "m1",
             "payment_method": "credit_card", "ts": "2024-01-01 10:00:00",
             "amount": -50.0, "currency": "GBP", "country": "GB",
             "channel": "online", "device_type": "desktop",
             "status": "SUCCESS", "batch_id": "b1"},
        ]
        _load_test_data(in_memory_db, rows)
        result = check_amount_positive(in_memory_db, "silver.transactions", 0.0, 0.0)
        assert result.status == "FAIL"
        assert result.records_failed == 1


class TestValidValuesCheck:

    def test_all_valid_statuses_pass(self, in_memory_db) -> None:
        _load_test_data(in_memory_db, [
            {"transaction_id": "t1", "customer_id": "c1", "merchant_id": "m1",
             "payment_method": "credit_card", "ts": "2024-01-01 10:00:00",
             "amount": 100.0, "currency": "GBP", "country": "GB",
             "channel": "online", "device_type": "desktop",
             "status": "SUCCESS", "batch_id": "b1"},
        ])
        result = check_valid_values(
            in_memory_db, "silver.transactions", "status",
            ["SUCCESS", "FAILED", "PENDING", "REVERSED", "INITIATED"],
            0.01, 0.05,
        )
        assert result.status == "PASS"

    def test_invalid_status_flagged(self, in_memory_db) -> None:
        _load_test_data(in_memory_db, [
            {"transaction_id": "t1", "customer_id": "c1", "merchant_id": "m1",
             "payment_method": "credit_card", "ts": "2024-01-01 10:00:00",
             "amount": 100.0, "currency": "GBP", "country": "GB",
             "channel": "online", "device_type": "desktop",
             "status": "INVALID_STATUS", "batch_id": "b1"},
        ])
        result = check_valid_values(
            in_memory_db, "silver.transactions", "status",
            ["SUCCESS", "FAILED"], 0.0, 0.0,
        )
        assert result.status == "FAIL"
        assert result.records_failed == 1


class TestQualityScore:

    def test_all_pass_score_100(self) -> None:
        results = [
            DQResult("t", "check1", "COMPLETENESS", 100, 0, 0.0, "PASS", "2024-01-01"),
            DQResult("t", "check2", "UNIQUENESS", 100, 0, 0.0, "PASS", "2024-01-01"),
        ]
        assert compute_quality_score(results) == 100.0

    def test_all_fail_score_0(self) -> None:
        results = [
            DQResult("t", "check1", "COMPLETENESS", 100, 50, 0.5, "FAIL", "2024-01-01"),
            DQResult("t", "check2", "UNIQUENESS", 100, 50, 0.5, "FAIL", "2024-01-01"),
        ]
        assert compute_quality_score(results) == 0.0

    def test_mixed_score(self) -> None:
        results = [
            DQResult("t", "check1", "COMPLETENESS", 100, 0, 0.0, "PASS", "2024-01-01"),
            DQResult("t", "check2", "VALIDITY", 100, 5, 0.05, "WARN", "2024-01-01"),
            DQResult("t", "check3", "UNIQUENESS", 100, 50, 0.5, "FAIL", "2024-01-01"),
        ]
        # (1.0 + 0.5 + 0.0) / 3 * 100 = 50.0
        assert compute_quality_score(results) == 50.0

    def test_empty_results_score_0(self) -> None:
        assert compute_quality_score([]) == 0.0

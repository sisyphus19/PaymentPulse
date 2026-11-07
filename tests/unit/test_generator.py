"""
PaymentPulse — Unit Tests: Data Generator
==========================================
Tests the synthetic data generator. Verifies:
  - Correct entity counts
  - Required columns present
  - Injected DQ problems exist (not zero)
  - Output files are created
  - Results are reproducible with same seed

These tests use a small dataset (1000 transactions) to keep execution fast.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml

# Make src importable when running tests from project root
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from paymentpulse.generator.generate import (
    _generate_customers,
    _generate_merchants,
    generate,
)


@pytest.fixture()
def small_config(tmp_path: Path) -> Path:
    """Create a minimal config file with 1000 transactions for fast tests."""
    cfg = {
        "dataset": {"num_transactions": 1000, "num_customers": 50, "num_merchants": 20, "random_seed": 42},
        "dq_injection": {
            "null_customer_id": 0.01,
            "null_amount": 0.01,
            "duplicate_transaction_id": 0.01,
            "invalid_currency": 0.01,
            "invalid_status": 0.01,
            "orphan_customer_id": 0.01,
            "orphan_merchant_id": 0.01,
            "malformed_timestamp": 0.01,
            "future_timestamp": 0.01,
            "negative_amount": 0.01,
        },
        "paths": {
            "raw_dir": str(tmp_path / "raw"),
            "processed_dir": str(tmp_path / "processed"),
            "quarantine_dir": str(tmp_path / "quarantine"),
            "db_path": str(tmp_path / "test.duckdb"),
        },
        "payment_methods": [
            "credit_card", "debit_card", "bank_transfer",
            "digital_wallet", "buy_now_pay_later", "direct_debit",
            "standing_order", "faster_payments",
        ],
        "valid_statuses": ["INITIATED", "SUCCESS", "FAILED", "PENDING", "REVERSED"],
        "valid_currencies": ["GBP", "USD", "EUR", "AUD", "CAD"],
        "channels": ["online", "mobile", "branch", "atm", "pos"],
        "device_types": ["desktop", "mobile", "tablet", "unknown"],
        "customer_segments": ["retail", "premium", "business", "student", "private_banking"],
        "merchant_categories": ["retail", "food_and_beverage", "travel", "healthcare"],
        "merchant_risk_categories": ["low", "medium", "high"],
        "controls": {"max_transaction_amount": 1000000, "freshness_sla_hours": 24,
                     "volume_anomaly_threshold": 0.30},
        "dq_thresholds": {"warn_failure_rate": 0.01, "fail_failure_rate": 0.05},
        "ingestion": {"schema_version": "1.0", "expected_columns": []},
    }
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(cfg, f)
    return config_path


class TestCustomerGeneration:
    """Tests for _generate_customers."""

    def test_correct_count(self, small_config: Path) -> None:
        import random

        from faker import Faker
        with open(small_config) as f:
            cfg = yaml.safe_load(f)
        random.seed(42)
        fake = Faker()
        Faker.seed(42)
        customers = _generate_customers(cfg, fake)
        assert len(customers) == cfg["dataset"]["num_customers"]

    def test_required_columns(self, small_config: Path) -> None:
        import random

        from faker import Faker
        with open(small_config) as f:
            cfg = yaml.safe_load(f)
        random.seed(42)
        fake = Faker()
        Faker.seed(42)
        customers = _generate_customers(cfg, fake)
        df = pd.DataFrame(customers)
        required = {"customer_id", "name", "email", "segment", "country", "customer_since"}
        assert required.issubset(set(df.columns))

    def test_no_null_customer_ids(self, small_config: Path) -> None:
        import random

        from faker import Faker
        with open(small_config) as f:
            cfg = yaml.safe_load(f)
        random.seed(42)
        fake = Faker()
        Faker.seed(42)
        customers = _generate_customers(cfg, fake)
        df = pd.DataFrame(customers)
        assert df["customer_id"].notna().all(), "Customer IDs should never be null"

    def test_unique_customer_ids(self, small_config: Path) -> None:
        import random

        from faker import Faker
        with open(small_config) as f:
            cfg = yaml.safe_load(f)
        random.seed(42)
        fake = Faker()
        customers = _generate_customers(cfg, fake)
        df = pd.DataFrame(customers)
        assert df["customer_id"].nunique() == len(df), "Customer IDs must be unique"


class TestMerchantGeneration:
    """Tests for _generate_merchants."""

    def test_correct_count(self, small_config: Path) -> None:
        import random

        from faker import Faker
        with open(small_config) as f:
            cfg = yaml.safe_load(f)
        random.seed(42)
        fake = Faker()
        merchants = _generate_merchants(cfg, fake)
        assert len(merchants) == cfg["dataset"]["num_merchants"]

    def test_risk_category_values(self, small_config: Path) -> None:
        import random

        from faker import Faker
        with open(small_config) as f:
            cfg = yaml.safe_load(f)
        random.seed(42)
        fake = Faker()
        merchants = _generate_merchants(cfg, fake)
        df = pd.DataFrame(merchants)
        valid = set(cfg["merchant_risk_categories"])
        assert set(df["risk_category"].unique()).issubset(valid)


class TestTransactionGeneration:
    """Tests for generate() end-to-end."""

    def test_output_files_created(self, small_config: Path) -> None:
        result = generate(config_path=small_config)
        assert Path(result["transactions_path"]).exists()
        assert Path(result["customers_path"]).exists()
        assert Path(result["merchants_path"]).exists()

    def test_correct_transaction_count(self, small_config: Path) -> None:
        result = generate(config_path=small_config)
        df = pd.read_csv(result["transactions_path"])
        with open(small_config) as f:
            cfg = yaml.safe_load(f)
        assert len(df) == cfg["dataset"]["num_transactions"]

    def test_required_transaction_columns(self, small_config: Path) -> None:
        result = generate(config_path=small_config)
        df = pd.read_csv(result["transactions_path"])
        required = {
            "transaction_id", "customer_id", "merchant_id", "payment_method",
            "timestamp", "amount", "currency", "country", "channel",
            "device_type", "status", "batch_id",
        }
        assert required.issubset(set(df.columns))

    def test_dq_problems_injected(self, small_config: Path) -> None:
        """At least some DQ problems should be present (injection is stochastic but guaranteed)."""
        result = generate(config_path=small_config)
        df = pd.read_csv(result["transactions_path"])

        # Check nulls exist somewhere (customer_id or amount should have some)
        null_customer = df["customer_id"].isna().sum()
        null_amount = df["amount"].isna().sum()
        assert null_customer + null_amount > 0, "Expected some null values to be injected"

    def test_duplicate_transaction_ids_injected(self, small_config: Path) -> None:
        result = generate(config_path=small_config)
        df = pd.read_csv(result["transactions_path"])
        dup_count = df["transaction_id"].duplicated().sum()
        assert dup_count > 0, "Expected some duplicate transaction IDs to be injected"

    def test_reproducibility_with_seed(self, small_config: Path) -> None:
        """Running generator twice with same seed produces same transaction IDs."""
        result1 = generate(config_path=small_config)
        result2 = generate(config_path=small_config)
        df1 = pd.read_csv(result1["transactions_path"])
        df2 = pd.read_csv(result2["transactions_path"])
        # Row counts and first transaction ID should match
        assert len(df1) == len(df2)
        assert df1.iloc[0]["transaction_id"] == df2.iloc[0]["transaction_id"]

    def test_batch_id_in_result(self, small_config: Path) -> None:
        result = generate(config_path=small_config)
        assert "batch_id" in result
        assert len(result["batch_id"]) == 36  # UUID length

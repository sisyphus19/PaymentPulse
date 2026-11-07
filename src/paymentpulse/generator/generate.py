"""
PaymentPulse — Synthetic Payments Data Generator
=================================================
Generates a realistic synthetic payments dataset for portfolio/demo purposes.

Why this exists: The project has no access to real payment data. Faker
provides locale-aware synthetic PII; the generator also deliberately injects
configurable data-quality problems so that the downstream DQ framework has
real defects to find and quarantine. The injected-problem rates are all
controlled from config/config.yaml so reviewers can adjust them.

Entity counts and dataset size are also configurable — the default 75,000
transactions (500 customers, 100 merchants) gives realistic query results
and runs in ~10 seconds locally.

Outputs three CSV files:
  data/raw/customers_<batch_id>.csv
  data/raw/merchants_<batch_id>.csv
  data/raw/transactions_<batch_id>.csv
"""

from __future__ import annotations

import csv
import random
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from faker import Faker

from paymentpulse.utils.logger import get_logger

log = get_logger(__name__)


def _load_config(config_path: str | Path = "config/config.yaml") -> dict[str, Any]:
    """Load YAML configuration file."""
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _random_uuid() -> str:
    """Generate a UUID4 whose randomness is tied to Python's random.seed."""
    return str(uuid.UUID(int=random.getrandbits(128), version=4))


# ---------------------------------------------------------------------------
# Customer generation
# ---------------------------------------------------------------------------

def _generate_customers(cfg: dict, fake: Faker) -> list[dict]:
    """Generate the customer reference table.

    Each customer has a segment, country of residence, and account open date.
    Customer IDs are UUIDs so they are globally unique and format-consistent.
    """
    segments = cfg["customer_segments"]
    countries = ["GB", "US", "DE", "FR", "AU", "CA", "SG", "IN", "JP", "HK"]
    n = cfg["dataset"]["num_customers"]

    customers = []
    for _ in range(n):
        customers.append({
            "customer_id": _random_uuid(),
            "name": fake.name(),
            "email": fake.email(),
            "segment": random.choice(segments),
            "country": random.choice(countries),
            "customer_since": fake.date_between(start_date="-10y", end_date="-1y").isoformat(),
        })
    return customers


# ---------------------------------------------------------------------------
# Merchant generation
# ---------------------------------------------------------------------------

def _generate_merchants(cfg: dict, fake: Faker) -> list[dict]:
    """Generate the merchant reference table.

    Merchants are assigned a risk category (low/medium/high) to simulate the
    mix seen in real acquiring banks. High-risk merchants get disproportionately
    higher failure rates later in the transaction generator.
    """
    categories = cfg["merchant_categories"]
    risk_cats = cfg["merchant_risk_categories"]
    countries = ["GB", "US", "DE", "FR", "AU", "IE", "NL", "SG"]
    n = cfg["dataset"]["num_merchants"]

    # Risk distribution: 70% low, 20% medium, 10% high
    risk_weights = [0.70, 0.20, 0.10]

    merchants = []
    for _ in range(n):
        merchants.append({
            "merchant_id": _random_uuid(),
            "name": fake.company(),
            "category": random.choice(categories),
            "country": random.choice(countries),
            "risk_category": random.choices(risk_cats, weights=risk_weights, k=1)[0],
        })
    return merchants


# ---------------------------------------------------------------------------
# Transaction generation
# ---------------------------------------------------------------------------

def _generate_transactions(
    cfg: dict,
    customers: list[dict],
    merchants: list[dict],
    batch_id: str,
    fake: Faker,
) -> list[dict]:
    """Generate synthetic payment transactions with realistic patterns.

    Design decisions:
    - Timestamps span the last 90 days so freshness checks are realistic.
    - Amount distributions differ by payment method (bank transfers tend to
      be higher value; digital wallets lower).
    - Status distribution is skewed heavily toward SUCCESS (~78%), reflecting
      real-world payment success rates for a well-run payments platform.
    - High-risk merchants have an elevated failure rate.
    - Customer behaviour varies by segment (premium customers transact higher
      amounts; students transact less frequently).
    """
    n = cfg["dataset"]["num_transactions"]
    dq = cfg["dq_injection"]
    payment_methods = cfg["payment_methods"]
    valid_statuses = cfg["valid_statuses"]
    valid_currencies = cfg["valid_currencies"]
    channels = cfg["channels"]
    device_types = cfg["device_types"]

    customer_ids = [c["customer_id"] for c in customers]
    merchant_ids = [m["merchant_id"] for m in merchants]

    # Pre-build merchant risk lookup so we can bias failure rates
    merchant_risk: dict[str, str] = {m["merchant_id"]: m["risk_category"] for m in merchants}

    # Status weights: SUCCESS, FAILED, PENDING, REVERSED, INITIATED (lingering)
    base_status_weights = [0.78, 0.12, 0.05, 0.04, 0.01]
    # High-risk merchant boosts FAILED
    high_risk_weights = [0.55, 0.32, 0.07, 0.05, 0.01]
    medium_risk_weights = [0.70, 0.20, 0.06, 0.03, 0.01]

    # Amount distributions by payment method (mean, std) in GBP
    amount_params: dict[str, tuple[float, float]] = {
        "credit_card": (120.0, 200.0),
        "debit_card": (65.0, 80.0),
        "bank_transfer": (2500.0, 5000.0),
        "digital_wallet": (40.0, 60.0),
        "buy_now_pay_later": (250.0, 300.0),
        "direct_debit": (150.0, 200.0),
        "standing_order": (500.0, 800.0),
        "faster_payments": (1000.0, 2000.0),
    }

    now = datetime.now(UTC)
    start_window = now - timedelta(days=90)

    transactions = []
    used_txn_ids: set[str] = set()

    # Pre-compute indices for DQ injection
    total = n
    null_cust_indices = set(random.sample(range(total), max(1, int(total * dq["null_customer_id"]))))
    null_amt_indices = set(random.sample(range(total), max(1, int(total * dq["null_amount"]))))
    dup_indices = set(random.sample(range(total), max(1, int(total * dq["duplicate_transaction_id"]))))
    bad_currency_indices = set(random.sample(range(total), max(1, int(total * dq["invalid_currency"]))))
    bad_status_indices = set(random.sample(range(total), max(1, int(total * dq["invalid_status"]))))
    orphan_cust_indices = set(random.sample(range(total), max(1, int(total * dq["orphan_customer_id"]))))
    orphan_merch_indices = set(random.sample(range(total), max(1, int(total * dq["orphan_merchant_id"]))))
    bad_ts_indices = set(random.sample(range(total), max(1, int(total * dq["malformed_timestamp"]))))
    future_ts_indices = set(random.sample(range(total), max(1, int(total * dq["future_timestamp"]))))
    neg_amt_indices = set(random.sample(range(total), max(1, int(total * dq["negative_amount"]))))

    # Pool of IDs to reuse for duplicate injection
    existing_txn_ids: list[str] = []

    for i in range(total):
        method = random.choice(payment_methods)
        merchant_id = random.choice(merchant_ids)
        risk = merchant_risk.get(merchant_id, "low")

        # Status selection based on merchant risk
        if risk == "high":
            status = random.choices(valid_statuses, weights=high_risk_weights, k=1)[0]
        elif risk == "medium":
            status = random.choices(valid_statuses, weights=medium_risk_weights, k=1)[0]
        else:
            status = random.choices(valid_statuses, weights=base_status_weights, k=1)[0]

        # Transaction ID
        if i in dup_indices and existing_txn_ids:
            txn_id = random.choice(existing_txn_ids)  # deliberate duplicate
        else:
            txn_id = _random_uuid()
            used_txn_ids.add(txn_id)
            existing_txn_ids.append(txn_id)

        # Amount
        mean, std = amount_params.get(method, (100.0, 150.0))
        amount: float | None = round(max(0.01, random.gauss(mean, std)), 2)
        if i in null_amt_indices:
            amount = None
        elif i in neg_amt_indices:
            amount = round(-1 * random.uniform(0.01, 500.0), 2)

        # Timestamp
        random_seconds = random.randint(0, int((now - start_window).total_seconds()))
        ts = start_window + timedelta(seconds=random_seconds)
        if i in bad_ts_indices:
            timestamp_str: str | None = fake.pystr(min_chars=8, max_chars=15)  # garbage string
        elif i in future_ts_indices:
            timestamp_str = (now + timedelta(days=random.randint(1, 30))).isoformat()
        else:
            timestamp_str = ts.isoformat()

        # Customer ID
        if i in null_cust_indices:
            customer_id: str | None = None
        elif i in orphan_cust_indices:
            customer_id = "ORPHAN_" + _random_uuid()[:8]
        else:
            customer_id = random.choice(customer_ids)

        # Merchant ID
        if i in orphan_merch_indices:
            merchant_id = "ORPHAN_" + _random_uuid()[:8]

        # Currency
        if i in bad_currency_indices:
            currency: str = fake.pystr(min_chars=2, max_chars=5).upper()  # garbage currency code
        else:
            currency = random.choice(valid_currencies)

        # Status override for bad status injection
        if i in bad_status_indices:
            status = random.choice(["DECLINED", "UNKNOWN", "ERR", "null", "CANCELLED"])

        country = fake.country_code(representation="alpha-2")
        channel = random.choice(channels)
        device_type = random.choice(device_types)

        transactions.append({
            "transaction_id": txn_id,
            "customer_id": customer_id,
            "merchant_id": merchant_id,
            "payment_method": method,
            "timestamp": timestamp_str,
            "amount": amount,
            "currency": currency,
            "country": country,
            "channel": channel,
            "device_type": device_type,
            "status": status,
            "batch_id": batch_id,
        })

    log.info("Generated %d transactions (%d DQ problems injected)", total, _count_injected(dq, total))
    return transactions


def _count_injected(dq: dict, total: int) -> int:
    """Rough total of deliberately injected DQ issues (some rows may overlap)."""
    return sum(max(1, int(total * v)) for v in dq.values())


# ---------------------------------------------------------------------------
# CSV writers
# ---------------------------------------------------------------------------

def _write_csv(records: list[dict], path: Path) -> int:
    """Write list of dicts to CSV, returning record count."""
    if not records:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)
    return len(records)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate(
    config_path: str | Path = "config/config.yaml",
    output_dir: str | Path | None = None,
    batch_id: str | None = None,
) -> dict[str, Any]:
    """Generate and persist the synthetic payments dataset.

    Args:
        config_path: Path to config.yaml.
        output_dir: Override output directory (default: config paths.raw_dir).
        batch_id: Override batch ID (auto-generated UUID if not provided).

    Returns:
        Dictionary with batch_id, output paths, and record counts.
    """
    cfg = _load_config(config_path)

    seed = cfg["dataset"].get("random_seed", 42)
    random.seed(seed)
    fake = Faker(["en_GB", "en_US"])
    Faker.seed(seed)

    if batch_id is None:
        batch_id = str(uuid.uuid4())

    raw_dir = Path(output_dir) if output_dir else Path(cfg["paths"]["raw_dir"])

    log.info("Starting generation | batch_id=%s | seed=%d", batch_id, seed)

    customers = _generate_customers(cfg, fake)
    merchants = _generate_merchants(cfg, fake)
    transactions = _generate_transactions(cfg, customers, merchants, batch_id, fake)

    customers_path = raw_dir / f"customers_{batch_id}.csv"
    merchants_path = raw_dir / f"merchants_{batch_id}.csv"
    transactions_path = raw_dir / f"transactions_{batch_id}.csv"

    n_cust = _write_csv(customers, customers_path)
    n_merch = _write_csv(merchants, merchants_path)
    n_txn = _write_csv(transactions, transactions_path)

    log.info(
        "Generation complete | customers=%d | merchants=%d | transactions=%d",
        n_cust, n_merch, n_txn,
    )

    return {
        "batch_id": batch_id,
        "customers_path": str(customers_path),
        "merchants_path": str(merchants_path),
        "transactions_path": str(transactions_path),
        "num_customers": n_cust,
        "num_merchants": n_merch,
        "num_transactions": n_txn,
    }


if __name__ == "__main__":
    result = generate()
    print(result)

"""
PaymentPulse — DuckDB Warehouse (Bronze → Silver → Gold)
=========================================================
Implements the medallion architecture using DuckDB as the local warehouse.

Why this architecture:
  Bronze  — Raw ingested data; nothing is deleted or transformed. Preserves
            the original record for lineage and audit purposes.
  Silver  — Clean, typed, deduplicated data. Invalid records are quarantined
            rather than deleted; this lets us report on data quality without
            losing the record count needed for reconciliation.
  Gold    — Business-ready dimensional model: one fact table + four dimension
            tables. Analytical queries run against Gold. No duplicates,
            no nulls in key fields, consistent data types.

Why DuckDB (not Postgres): DuckDB is file-based (zero server config), ANSI SQL
compatible, column-oriented (fast aggregations), natively reads Parquet/CSV,
and runs on any OS. It is the right choice for a local portfolio demo where
reproducibility and setup simplicity matter.

In production this layer would be replaced by Databricks PySpark (Bronze→Silver)
and Snowflake (Gold dimensional model). The SQL structure here is intentionally
compatible with Snowflake syntax — see docs/architecture.md.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import yaml

from paymentpulse.utils.logger import get_logger

log = get_logger(__name__)


def _load_config(config_path: str | Path = "config/config.yaml") -> dict[str, Any]:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Silver DDL
# ---------------------------------------------------------------------------

SILVER_DDL = """
CREATE SCHEMA IF NOT EXISTS silver;

CREATE TABLE IF NOT EXISTS silver.customers (
    customer_id     VARCHAR PRIMARY KEY,
    name            VARCHAR,
    email           VARCHAR,
    segment         VARCHAR,
    country         VARCHAR,
    customer_since  DATE,
    batch_id        VARCHAR,
    _loaded_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS silver.merchants (
    merchant_id     VARCHAR PRIMARY KEY,
    name            VARCHAR,
    category        VARCHAR,
    country         VARCHAR,
    risk_category   VARCHAR,
    batch_id        VARCHAR,
    _loaded_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS silver.transactions (
    transaction_id  VARCHAR PRIMARY KEY,
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
    batch_id        VARCHAR,
    _loaded_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS silver.quarantine (
    transaction_id   VARCHAR,
    raw_record       VARCHAR,   -- JSON representation of raw row
    rejection_reason VARCHAR,
    batch_id         VARCHAR,
    _quarantined_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

# ---------------------------------------------------------------------------
# Gold DDL
# ---------------------------------------------------------------------------

GOLD_DDL = """
CREATE SCHEMA IF NOT EXISTS gold;

CREATE TABLE IF NOT EXISTS gold.dim_customer (
    customer_sk     INTEGER PRIMARY KEY,  -- surrogate key
    customer_id     VARCHAR UNIQUE,
    name            VARCHAR,
    email           VARCHAR,
    segment         VARCHAR,
    country         VARCHAR,
    customer_since  DATE
);

CREATE TABLE IF NOT EXISTS gold.dim_merchant (
    merchant_sk     INTEGER PRIMARY KEY,
    merchant_id     VARCHAR UNIQUE,
    name            VARCHAR,
    category        VARCHAR,
    country         VARCHAR,
    risk_category   VARCHAR
);

CREATE TABLE IF NOT EXISTS gold.dim_payment_method (
    payment_method_sk   INTEGER PRIMARY KEY,
    payment_method      VARCHAR UNIQUE,
    method_group        VARCHAR   -- e.g. 'card', 'account', 'digital'
);

CREATE TABLE IF NOT EXISTS gold.dim_date (
    date_sk         INTEGER PRIMARY KEY,  -- YYYYMMDD integer
    full_date       DATE,
    year            INTEGER,
    quarter         INTEGER,
    month           INTEGER,
    month_name      VARCHAR,
    week_of_year    INTEGER,
    day_of_month    INTEGER,
    day_of_week     INTEGER,
    day_name        VARCHAR,
    is_weekend      BOOLEAN
);

CREATE TABLE IF NOT EXISTS gold.fact_transactions (
    transaction_id      VARCHAR PRIMARY KEY,
    customer_sk         INTEGER,
    merchant_sk         INTEGER,
    payment_method_sk   INTEGER,
    date_sk             INTEGER,
    ts                  TIMESTAMP,
    amount              DOUBLE,
    currency            VARCHAR,
    country             VARCHAR,
    channel             VARCHAR,
    device_type         VARCHAR,
    status              VARCHAR,
    is_success          BOOLEAN,
    is_failed           BOOLEAN,
    is_reversed         BOOLEAN,
    batch_id            VARCHAR
);
"""

# ---------------------------------------------------------------------------
# Silver transformation
# ---------------------------------------------------------------------------

VALID_STATUSES = {"INITIATED", "SUCCESS", "FAILED", "PENDING", "REVERSED"}
VALID_CURRENCIES = {
    "GBP", "USD", "EUR", "AUD", "CAD", "JPY", "CHF", "HKD", "SGD", "INR",
}
VALID_PAYMENT_METHODS = {
    "credit_card", "debit_card", "bank_transfer", "digital_wallet",
    "buy_now_pay_later", "direct_debit", "standing_order", "faster_payments",
}


def _build_silver(con: duckdb.DuckDBPyConnection, batch_id: str, cfg: dict) -> dict[str, int]:
    """Transform Bronze → Silver: type, deduplicate, quarantine invalids.

    Returns dict with silver and quarantine counts.
    """
    max_amount = cfg["controls"]["max_transaction_amount"]

    # ── Customers ──────────────────────────────────────────────────────────
    con.execute("DELETE FROM silver.customers WHERE batch_id = ?", [batch_id])
    con.execute("""
        INSERT OR REPLACE INTO silver.customers (
            customer_id, name, email, segment, country, customer_since, batch_id
        )
        SELECT DISTINCT ON (customer_id)
            customer_id,
            name,
            email,
            segment,
            country,
            TRY_CAST(customer_since AS DATE)  AS customer_since,
            batch_id
        FROM bronze.raw_customers
        WHERE batch_id = ?
          AND customer_id IS NOT NULL
          AND customer_id != ''
    """, [batch_id])
    n_customers = con.execute(
        "SELECT COUNT(*) FROM silver.customers WHERE batch_id = ?", [batch_id]
    ).fetchone()[0]

    # ── Merchants ──────────────────────────────────────────────────────────
    con.execute("DELETE FROM silver.merchants WHERE batch_id = ?", [batch_id])
    con.execute("""
        INSERT OR REPLACE INTO silver.merchants (
            merchant_id, name, category, country, risk_category, batch_id
        )
        SELECT DISTINCT ON (merchant_id)
            merchant_id, name, category, country, risk_category, batch_id
        FROM bronze.raw_merchants
        WHERE batch_id = ?
          AND merchant_id IS NOT NULL
          AND merchant_id != ''
    """, [batch_id])

    # ── Transactions: parse + validate ─────────────────────────────────────
    # Pull raw transactions for this batch
    raw_df = con.execute("""
        SELECT *
        FROM bronze.raw_transactions
        WHERE batch_id = ?
    """, [batch_id]).df()

    valid_customer_ids = set(
        con.execute("SELECT customer_id FROM silver.customers").df()["customer_id"].tolist()
    )
    valid_merchant_ids = set(
        con.execute("SELECT merchant_id FROM silver.merchants").df()["merchant_id"].tolist()
    )

    silver_rows = []
    quarantine_rows = []

    # Track seen transaction IDs for deduplication
    seen_txn_ids: set[str] = set()

    for _, row in raw_df.iterrows():
        reasons: list[str] = []

        txn_id = str(row.get("transaction_id", "") or "").strip()
        if not txn_id:
            reasons.append("null/empty transaction_id")

        # Deduplication
        if txn_id in seen_txn_ids:
            reasons.append(f"duplicate transaction_id: {txn_id}")
        else:
            seen_txn_ids.add(txn_id)

        # Amount parsing
        try:
            amount = float(row["amount"])
            if amount <= 0:
                reasons.append(f"non-positive amount: {amount}")
            elif amount > max_amount:
                reasons.append(f"amount exceeds threshold: {amount}")
        except (TypeError, ValueError):
            amount = None
            reasons.append(f"unparseable amount: {row.get('amount')!r}")

        # Timestamp parsing
        try:
            ts = _parse_timestamp(str(row.get("timestamp", "") or ""))
            if ts is None:
                reasons.append(f"unparseable timestamp: {row.get('timestamp')!r}")
            elif ts > datetime.now(UTC):
                reasons.append(f"future timestamp: {ts.isoformat()}")
                ts = None
        except Exception:
            ts = None
            reasons.append(f"timestamp parse error: {row.get('timestamp')!r}")

        # Currency
        currency = str(row.get("currency", "") or "").strip().upper()
        if currency not in VALID_CURRENCIES:
            reasons.append(f"invalid currency: {currency!r}")

        # Status
        status = str(row.get("status", "") or "").strip().upper()
        if status not in VALID_STATUSES:
            reasons.append(f"invalid status: {status!r}")

        # Payment method
        payment_method = str(row.get("payment_method", "") or "").strip().lower()
        if payment_method not in VALID_PAYMENT_METHODS:
            reasons.append(f"invalid payment_method: {payment_method!r}")

        # Customer referential integrity
        cust_id = str(row.get("customer_id", "") or "").strip()
        if not cust_id:
            reasons.append("null customer_id")
        elif cust_id not in valid_customer_ids:
            reasons.append(f"orphan customer_id: {cust_id}")

        # Merchant referential integrity
        merch_id = str(row.get("merchant_id", "") or "").strip()
        if not merch_id:
            reasons.append("null merchant_id")
        elif merch_id not in valid_merchant_ids:
            reasons.append(f"orphan merchant_id: {merch_id}")

        if reasons:
            # Quarantine this record
            import json
            quarantine_rows.append({
                "transaction_id": txn_id or None,
                "raw_record": json.dumps({k: str(v) for k, v in row.items()}),
                "rejection_reason": "; ".join(reasons),
                "batch_id": batch_id,
            })
        else:
            silver_rows.append({
                "transaction_id": txn_id,
                "customer_id": cust_id,
                "merchant_id": merch_id,
                "payment_method": payment_method,
                "ts": ts,
                "amount": amount,
                "currency": currency,
                "country": str(row.get("country", "") or "").strip().upper(),
                "channel": str(row.get("channel", "") or "").strip().lower(),
                "device_type": str(row.get("device_type", "") or "").strip().lower(),
                "status": status,
                "batch_id": batch_id,
            })

    # Write to Silver
    con.execute("DELETE FROM silver.transactions WHERE batch_id = ?", [batch_id])
    if silver_rows:
        import pandas as pd
        silver_df = pd.DataFrame(silver_rows)  # noqa: F841 - queried by DuckDB
        s_cols = ", ".join(silver_df.columns)
        con.execute(f"INSERT INTO silver.transactions ({s_cols}) SELECT * FROM silver_df")  # noqa: S608

    # Write quarantine
    con.execute("DELETE FROM silver.quarantine WHERE batch_id = ?", [batch_id])
    if quarantine_rows:
        import pandas as pd
        qdf = pd.DataFrame(quarantine_rows)  # noqa: F841 - queried by DuckDB
        q_cols = ", ".join(qdf.columns)
        con.execute(f"INSERT INTO silver.quarantine ({q_cols}) SELECT * FROM qdf")  # noqa: S608

    log.info(
        "Silver | batch=%s | silver=%d | quarantine=%d",
        batch_id, len(silver_rows), len(quarantine_rows),
    )
    return {
        "silver_count": len(silver_rows),
        "quarantine_count": len(quarantine_rows),
        "customer_count": n_customers,
    }


def _parse_timestamp(ts_str: str) -> datetime | None:
    """Try multiple timestamp formats; return None if none match."""
    if not ts_str or ts_str.strip() in ("", "None", "nan"):
        return None
    try:
        dt = datetime.fromisoformat(ts_str.strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        pass

    formats = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(ts_str.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Gold transformation
# ---------------------------------------------------------------------------

METHOD_GROUPS = {
    "credit_card": "card",
    "debit_card": "card",
    "bank_transfer": "account",
    "digital_wallet": "digital",
    "buy_now_pay_later": "digital",
    "direct_debit": "account",
    "standing_order": "account",
    "faster_payments": "account",
}


def _build_gold(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Transform Silver → Gold: build dimensional model."""

    # ── dim_date: populate from Silver transaction dates ────────────────────
    con.execute("DELETE FROM gold.dim_date")
    con.execute("""
        INSERT OR IGNORE INTO gold.dim_date
        SELECT DISTINCT
            CAST(strftime(ts::DATE, '%Y%m%d') AS INTEGER)   AS date_sk,
            ts::DATE                                          AS full_date,
            YEAR(ts)                                          AS year,
            QUARTER(ts)                                       AS quarter,
            MONTH(ts)                                         AS month,
            strftime(ts, '%B')                                AS month_name,
            WEEKOFYEAR(ts)                                    AS week_of_year,
            DAY(ts)                                           AS day_of_month,
            DAYOFWEEK(ts)                                     AS day_of_week,
            strftime(ts, '%A')                                AS day_name,
            DAYOFWEEK(ts) IN (0, 6)                           AS is_weekend
        FROM silver.transactions
        WHERE ts IS NOT NULL
    """)

    # ── dim_customer ────────────────────────────────────────────────────────
    con.execute("DELETE FROM gold.dim_customer")
    con.execute("""
        INSERT INTO gold.dim_customer
        SELECT
            ROW_NUMBER() OVER (ORDER BY customer_id) AS customer_sk,
            customer_id, name, email, segment, country, customer_since
        FROM silver.customers
    """)

    # ── dim_merchant ────────────────────────────────────────────────────────
    con.execute("DELETE FROM gold.dim_merchant")
    con.execute("""
        INSERT INTO gold.dim_merchant
        SELECT
            ROW_NUMBER() OVER (ORDER BY merchant_id) AS merchant_sk,
            merchant_id, name, category, country, risk_category
        FROM silver.merchants
    """)

    # ── dim_payment_method ──────────────────────────────────────────────────
    con.execute("DELETE FROM gold.dim_payment_method")
    methods = list(VALID_PAYMENT_METHODS)
    for sk, method in enumerate(sorted(methods), start=1):
        group = METHOD_GROUPS.get(method, "other")
        con.execute(
            "INSERT OR IGNORE INTO gold.dim_payment_method VALUES (?, ?, ?)",
            [sk, method, group],
        )

    # ── fact_transactions ───────────────────────────────────────────────────
    con.execute("DELETE FROM gold.fact_transactions")
    con.execute("""
        INSERT INTO gold.fact_transactions
        SELECT
            t.transaction_id,
            c.customer_sk,
            m.merchant_sk,
            pm.payment_method_sk,
            CAST(strftime(t.ts::DATE, '%Y%m%d') AS INTEGER) AS date_sk,
            t.ts,
            t.amount,
            t.currency,
            t.country,
            t.channel,
            t.device_type,
            t.status,
            t.status = 'SUCCESS'  AS is_success,
            t.status = 'FAILED'   AS is_failed,
            t.status = 'REVERSED' AS is_reversed,
            t.batch_id
        FROM silver.transactions t
        LEFT JOIN gold.dim_customer    c  ON t.customer_id    = c.customer_id
        LEFT JOIN gold.dim_merchant    m  ON t.merchant_id    = m.merchant_id
        LEFT JOIN gold.dim_payment_method pm ON t.payment_method = pm.payment_method
    """)

    n_fact = con.execute("SELECT COUNT(*) FROM gold.fact_transactions").fetchone()[0]
    n_dim_cust = con.execute("SELECT COUNT(*) FROM gold.dim_customer").fetchone()[0]
    n_dim_merch = con.execute("SELECT COUNT(*) FROM gold.dim_merchant").fetchone()[0]
    n_dim_date = con.execute("SELECT COUNT(*) FROM gold.dim_date").fetchone()[0]

    log.info(
        "Gold | fact_transactions=%d | dim_customer=%d | dim_merchant=%d | dim_date=%d",
        n_fact, n_dim_cust, n_dim_merch, n_dim_date,
    )
    return {
        "fact_transactions": n_fact,
        "dim_customer": n_dim_cust,
        "dim_merchant": n_dim_merch,
        "dim_date": n_dim_date,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_warehouse(
    batch_id: str,
    config_path: str | Path = "config/config.yaml",
    db_path: str | None = None,
) -> dict[str, Any]:
    """Run the full Bronze → Silver → Gold pipeline for a given batch.

    Args:
        batch_id:    The batch to process.
        config_path: Path to config.yaml.
        db_path:     DuckDB file path. Falls back to config value.

    Returns:
        Summary dict with row counts at each layer.
    """
    cfg = _load_config(config_path)
    db_path = db_path or cfg["paths"]["db_path"]

    log.info("Warehouse build started | batch=%s", batch_id)

    con = duckdb.connect(db_path)

    # Ensure schemas exist
    con.execute(SILVER_DDL)
    con.execute(GOLD_DDL)

    silver_counts = _build_silver(con, batch_id, cfg)
    gold_counts = _build_gold(con)

    con.close()
    log.info("Warehouse build complete | batch=%s", batch_id)

    return {
        "batch_id": batch_id,
        "silver": silver_counts,
        "gold": gold_counts,
    }

"""
PaymentPulse — Ingestion Layer
===============================
Reads generated CSV files, validates schema, records batch metadata, and
writes raw records into the Bronze layer of the DuckDB warehouse.

Why this exists: Ingestion is a distinct concern from transformation. Separating
it means we can swap the source format (CSV → Parquet → API) without touching
the Bronze→Silver logic. It also gives us an audit trail (ingestion_audit table)
that answers: "what data arrived, when, from where, how many records were good
or bad at the schema level?"

The ingestion layer only does schema-level validation (are the expected columns
present?). Field-level validation (is the amount positive? is the currency valid?)
is the responsibility of the data-quality framework in the next layer.

Idempotency: if the same batch_id is re-ingested, existing records for that
batch are deleted first so re-running never duplicates data.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import yaml

from paymentpulse.utils.logger import get_logger

log = get_logger(__name__)


def _load_config(config_path: str | Path = "config/config.yaml") -> dict[str, Any]:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

EXPECTED_SCHEMAS: dict[str, list[str]] = {
    "transactions": [
        "transaction_id", "customer_id", "merchant_id", "payment_method",
        "timestamp", "amount", "currency", "country", "channel",
        "device_type", "status", "batch_id",
    ],
    "customers": [
        "customer_id", "name", "email", "segment", "country", "customer_since",
    ],
    "merchants": [
        "merchant_id", "name", "category", "country", "risk_category",
    ],
}


def validate_schema(df: pd.DataFrame, table_name: str) -> tuple[bool, list[str]]:
    """Check that the DataFrame contains all expected columns for table_name.

    Args:
        df: Input DataFrame from CSV.
        table_name: One of 'transactions', 'customers', 'merchants'.

    Returns:
        (is_valid, missing_columns) tuple.
    """
    expected = set(EXPECTED_SCHEMAS.get(table_name, []))
    actual = set(df.columns.tolist())
    missing = sorted(expected - actual)
    return len(missing) == 0, missing


# ---------------------------------------------------------------------------
# Bronze DDL
# ---------------------------------------------------------------------------

BRONZE_DDL = """
CREATE SCHEMA IF NOT EXISTS bronze;

CREATE TABLE IF NOT EXISTS bronze.raw_transactions (
    transaction_id  VARCHAR,
    customer_id     VARCHAR,
    merchant_id     VARCHAR,
    payment_method  VARCHAR,
    timestamp       VARCHAR,   -- raw string; typed in Silver
    amount          VARCHAR,   -- raw string; typed in Silver
    currency        VARCHAR,
    country         VARCHAR,
    channel         VARCHAR,
    device_type     VARCHAR,
    status          VARCHAR,
    batch_id        VARCHAR,
    _ingested_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bronze.raw_customers (
    customer_id     VARCHAR,
    name            VARCHAR,
    email           VARCHAR,
    segment         VARCHAR,
    country         VARCHAR,
    customer_since  VARCHAR,
    batch_id        VARCHAR,
    _ingested_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bronze.raw_merchants (
    merchant_id     VARCHAR,
    name            VARCHAR,
    category        VARCHAR,
    country         VARCHAR,
    risk_category   VARCHAR,
    batch_id        VARCHAR,
    _ingested_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bronze.ingestion_audit (
    audit_id            VARCHAR PRIMARY KEY,
    batch_id            VARCHAR NOT NULL,
    source_file         VARCHAR,
    table_name          VARCHAR,
    schema_version      VARCHAR,
    ingestion_timestamp TIMESTAMP,
    record_count        BIGINT,
    success_count       BIGINT,
    failure_count       BIGINT,
    status              VARCHAR,  -- SUCCESS / SCHEMA_ERROR / PARTIAL
    error_detail        VARCHAR
);
"""


# ---------------------------------------------------------------------------
# Core ingest function
# ---------------------------------------------------------------------------

def ingest(
    transactions_path: str | Path,
    customers_path: str | Path,
    merchants_path: str | Path,
    batch_id: str | None = None,
    config_path: str | Path = "config/config.yaml",
    db_path: str | None = None,
) -> dict[str, Any]:
    """Ingest raw CSVs into the Bronze DuckDB layer.

    Args:
        transactions_path: Path to transactions CSV.
        customers_path:    Path to customers CSV.
        merchants_path:    Path to merchants CSV.
        batch_id:          Batch identifier. Auto-generated if None.
        config_path:       Path to config.yaml.
        db_path:           DuckDB file path. Falls back to config value.

    Returns:
        Ingestion summary dict containing batch_id, record counts, and status.
    """
    cfg = _load_config(config_path)
    db_path = db_path or cfg["paths"]["db_path"]
    schema_version = cfg["ingestion"]["schema_version"]

    if batch_id is None:
        batch_id = str(uuid.uuid4())

    log.info("Ingestion started | batch_id=%s | db=%s", batch_id, db_path)

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(db_path)

    # Ensure Bronze schema exists
    con.execute(BRONZE_DDL)

    ingestion_ts = datetime.now(UTC)
    audit_records: list[dict] = []
    summary: dict[str, Any] = {
        "batch_id": batch_id,
        "transactions": {},
        "customers": {},
        "merchants": {},
    }

    file_map = {
        "transactions": (transactions_path, "bronze.raw_transactions"),
        "customers":    (customers_path,    "bronze.raw_customers"),
        "merchants":    (merchants_path,    "bronze.raw_merchants"),
    }

    for table_name, (file_path, bronze_table) in file_map.items():
        audit_id = str(uuid.uuid4())
        file_path = Path(file_path)
        log.info("Reading %s from %s", table_name, file_path)

        try:
            df = pd.read_csv(file_path, dtype=str, keep_default_na=False)
        except Exception as exc:
            log.error("Failed to read %s: %s", file_path, exc)
            audit_records.append({
                "audit_id": audit_id, "batch_id": batch_id,
                "source_file": str(file_path), "table_name": table_name,
                "schema_version": schema_version,
                "ingestion_timestamp": ingestion_ts,
                "record_count": 0, "success_count": 0, "failure_count": 0,
                "status": "READ_ERROR", "error_detail": str(exc),
            })
            summary[table_name] = {"status": "READ_ERROR", "error": str(exc)}
            continue

        # Schema validation
        is_valid, missing_cols = validate_schema(df, table_name)
        if not is_valid:
            msg = f"Missing columns: {missing_cols}"
            log.warning("Schema mismatch for %s | %s", table_name, msg)
            audit_records.append({
                "audit_id": audit_id, "batch_id": batch_id,
                "source_file": str(file_path), "table_name": table_name,
                "schema_version": schema_version,
                "ingestion_timestamp": ingestion_ts,
                "record_count": len(df), "success_count": 0, "failure_count": len(df),
                "status": "SCHEMA_ERROR", "error_detail": msg,
            })
            summary[table_name] = {"status": "SCHEMA_ERROR", "missing_columns": missing_cols}
            continue

        # Add batch_id column if not present (customers/merchants CSVs don't carry it)
        if "batch_id" not in df.columns:
            df["batch_id"] = batch_id

        # Idempotency: delete any existing records for this batch before inserting
        con.execute(f"DELETE FROM {bronze_table} WHERE batch_id = ?", [batch_id])  # noqa: S608

        record_count = len(df)

        cols_str = ", ".join(df.columns)
        # Bulk insert via DuckDB's native pandas integration
        con.execute(f"INSERT INTO {bronze_table} ({cols_str}) SELECT * FROM df")  # noqa: S608

        log.info("Loaded %d records into %s", record_count, bronze_table)

        audit_records.append({
            "audit_id": audit_id, "batch_id": batch_id,
            "source_file": str(file_path), "table_name": table_name,
            "schema_version": schema_version,
            "ingestion_timestamp": ingestion_ts,
            "record_count": record_count, "success_count": record_count, "failure_count": 0,
            "status": "SUCCESS", "error_detail": None,
        })
        summary[table_name] = {"status": "SUCCESS", "record_count": record_count}

    # Write audit records
    if audit_records:
        audit_df = pd.DataFrame(audit_records)  # noqa: F841 - queried by DuckDB
        con.execute("DELETE FROM bronze.ingestion_audit WHERE batch_id = ?", [batch_id])
        con.execute("INSERT INTO bronze.ingestion_audit SELECT * FROM audit_df")
        log.info("Audit records written: %d", len(audit_records))

    con.close()
    log.info("Ingestion complete | batch_id=%s", batch_id)
    summary["batch_id"] = batch_id
    return summary

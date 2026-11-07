"""
PaymentPulse — Data Controls Framework
========================================
Implements seven named data controls inspired by financial-services data
governance practices. Controls are distinct from DQ checks in that they are
binary pass/fail assertions at the business-rule level, not statistical
thresholds. In a real bank, control failures would trigger an incident process.

Why controls matter in banking: regulators (PRA, FCA) and internal audit
functions require evidence that data pipelines have explicit controls over
data integrity, completeness, and accuracy. Controls are the governance layer
on top of data quality.

Controls implemented:
  CTL-01: Transaction Uniqueness       — no duplicate transaction_id in gold
  CTL-02: Referential Integrity        — all gold facts have valid dimension keys
  CTL-03: Amount Validation            — amounts positive and within threshold
  CTL-04: Status Validity              — only approved status values in gold
  CTL-05: Pipeline Freshness           — latest record within SLA
  CTL-06: Schema Validation            — expected columns present in all layers
  CTL-07: Reconciliation               — raw count == silver + quarantine (± delta doc)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import yaml

from paymentpulse.utils.logger import get_logger

log = get_logger(__name__)


def _load_config(config_path: str | Path = "config/config.yaml") -> dict[str, Any]:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass
class ControlResult:
    """Result of a single named control."""

    control_id: str
    control_name: str
    status: str       # PASS / FAIL
    detail: str
    records_checked: int
    records_failed: int
    execution_timestamp: str
    remediation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# CTL-01: Transaction Uniqueness
# ---------------------------------------------------------------------------

def ctl_01_uniqueness(con: duckdb.DuckDBPyConnection) -> ControlResult:
    """No duplicate transaction_id in gold.fact_transactions.

    Gold is the analytical source of truth. Any duplicate here means a
    downstream analyst would double-count transaction values or volumes.
    """
    ts = datetime.now(UTC).isoformat()
    total = con.execute("SELECT COUNT(*) FROM gold.fact_transactions").fetchone()[0]
    dupes = con.execute("""
        SELECT COALESCE(SUM(cnt - 1), 0)
        FROM (
            SELECT transaction_id, COUNT(*) AS cnt
            FROM gold.fact_transactions
            GROUP BY transaction_id
            HAVING COUNT(*) > 1
        ) t
    """).fetchone()[0]
    status = "PASS" if dupes == 0 else "FAIL"
    return ControlResult(
        control_id="CTL-01", control_name="Transaction Uniqueness",
        status=status,
        detail=f"{dupes} duplicate transaction_id(s) found in gold.fact_transactions",
        records_checked=total, records_failed=int(dupes),
        execution_timestamp=ts,
        remediation="Re-run Silver deduplication step; investigate Bronze source for duplicate injection.",
    )


# ---------------------------------------------------------------------------
# CTL-02: Referential Integrity
# ---------------------------------------------------------------------------

def ctl_02_referential_integrity(con: duckdb.DuckDBPyConnection) -> ControlResult:
    """All facts in gold.fact_transactions must resolve to a valid dimension key."""
    ts = datetime.now(UTC).isoformat()
    total = con.execute("SELECT COUNT(*) FROM gold.fact_transactions").fetchone()[0]
    # Count facts with NULL dimension surrogate keys (indicates unresolved foreign key)
    failed = con.execute("""
        SELECT COUNT(*)
        FROM gold.fact_transactions
        WHERE customer_sk IS NULL
           OR merchant_sk IS NULL
           OR payment_method_sk IS NULL
    """).fetchone()[0]
    status = "PASS" if failed == 0 else "FAIL"
    return ControlResult(
        control_id="CTL-02", control_name="Referential Integrity",
        status=status,
        detail=f"{failed} fact rows with NULL dimension key(s)",
        records_checked=total, records_failed=failed,
        execution_timestamp=ts,
        remediation="Check Silver→Gold join logic; ensure dim tables are populated before facts.",
    )


# ---------------------------------------------------------------------------
# CTL-03: Amount Validation
# ---------------------------------------------------------------------------

def ctl_03_amount_validation(
    con: duckdb.DuckDBPyConnection,
    max_amount: float,
) -> ControlResult:
    """Transaction amounts must be positive and within configurable ceiling."""
    ts = datetime.now(UTC).isoformat()
    total = con.execute("SELECT COUNT(*) FROM gold.fact_transactions").fetchone()[0]
    failed = con.execute("""
        SELECT COUNT(*)
        FROM gold.fact_transactions
        WHERE amount IS NULL OR amount <= 0 OR amount > ?
    """, [max_amount]).fetchone()[0]
    status = "PASS" if failed == 0 else "FAIL"
    return ControlResult(
        control_id="CTL-03", control_name="Amount Validation",
        status=status,
        detail=f"{failed} transactions with invalid amount (null, <=0, or >{max_amount})",
        records_checked=total, records_failed=failed,
        execution_timestamp=ts,
        remediation="Quarantine amount-invalid records in Silver; investigate source system.",
    )


# ---------------------------------------------------------------------------
# CTL-04: Status Validity
# ---------------------------------------------------------------------------

def ctl_04_status_validity(
    con: duckdb.DuckDBPyConnection,
    valid_statuses: list[str],
) -> ControlResult:
    """Only approved transaction status values may exist in gold."""
    ts = datetime.now(UTC).isoformat()
    total = con.execute("SELECT COUNT(*) FROM gold.fact_transactions").fetchone()[0]
    placeholders = ", ".join(["?"] * len(valid_statuses))
    failed = con.execute(
        f"SELECT COUNT(*) FROM gold.fact_transactions WHERE status NOT IN ({placeholders})",  # noqa: S608
        valid_statuses,
    ).fetchone()[0]
    status = "PASS" if failed == 0 else "FAIL"
    return ControlResult(
        control_id="CTL-04", control_name="Status Validity",
        status=status,
        detail=f"{failed} transactions with non-approved status value",
        records_checked=total, records_failed=failed,
        execution_timestamp=ts,
        remediation="Review Silver status-validation logic; ensure bad-status records are quarantined.",
    )


# ---------------------------------------------------------------------------
# CTL-05: Pipeline Freshness
# ---------------------------------------------------------------------------

def ctl_05_freshness(
    con: duckdb.DuckDBPyConnection,
    sla_hours: int,
) -> ControlResult:
    """Latest transaction in Silver must be within the configured SLA window."""
    ts_now = datetime.now(UTC)
    ts = ts_now.isoformat()
    cutoff = ts_now - timedelta(hours=sla_hours)

    latest_raw = con.execute("SELECT MAX(ts) FROM silver.transactions").fetchone()[0]

    if latest_raw is None:
        return ControlResult(
            control_id="CTL-05", control_name="Pipeline Freshness",
            status="FAIL",
            detail="No transactions in Silver layer",
            records_checked=0, records_failed=0,
            execution_timestamp=ts,
            remediation="Run ingestion pipeline. Check generator and ingest steps.",
        )

    # DuckDB returns timestamps as datetime objects
    if isinstance(latest_raw, str):
        from paymentpulse.warehouse.warehouse import _parse_timestamp
        latest = _parse_timestamp(latest_raw) or ts_now.replace(year=2000)
    else:
        latest = latest_raw
        if hasattr(latest, "tzinfo") and latest.tzinfo is None:
            latest = latest.replace(tzinfo=UTC)

    passed = latest >= cutoff
    return ControlResult(
        control_id="CTL-05", control_name="Pipeline Freshness",
        status="PASS" if passed else "FAIL",
        detail=(
            f"Latest transaction at {latest.isoformat()} — "
            f"{'within' if passed else 'OUTSIDE'} {sla_hours}h SLA"
        ),
        records_checked=1, records_failed=0 if passed else 1,
        execution_timestamp=ts,
        remediation="Investigate pipeline delays; check ingestion schedule and source availability.",
    )


# ---------------------------------------------------------------------------
# CTL-06: Schema Validation
# ---------------------------------------------------------------------------

EXPECTED_GOLD_COLUMNS = {
    "gold.fact_transactions": [
        "transaction_id", "customer_sk", "merchant_sk", "payment_method_sk",
        "date_sk", "ts", "amount", "currency", "country", "channel",
        "device_type", "status", "is_success", "is_failed", "is_reversed", "batch_id",
    ],
    "gold.dim_customer": [
        "customer_sk", "customer_id", "name", "email", "segment", "country", "customer_since",
    ],
    "gold.dim_merchant": [
        "merchant_sk", "merchant_id", "name", "category", "country", "risk_category",
    ],
}


def ctl_06_schema_validation(con: duckdb.DuckDBPyConnection) -> ControlResult:
    """All expected columns must be present in Gold tables."""
    ts = datetime.now(UTC).isoformat()
    missing_all: list[str] = []

    for table, expected_cols in EXPECTED_GOLD_COLUMNS.items():
        schema_name, table_name = table.split(".")
        actual_cols = con.execute(f"""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = '{schema_name}'
              AND table_name = '{table_name}'
        """).df()["column_name"].tolist()
        missing = [c for c in expected_cols if c not in actual_cols]
        if missing:
            missing_all.append(f"{table}: missing {missing}")

    status = "PASS" if not missing_all else "FAIL"
    return ControlResult(
        control_id="CTL-06", control_name="Schema Validation",
        status=status,
        detail="; ".join(missing_all) if missing_all else "All expected columns present",
        records_checked=len(EXPECTED_GOLD_COLUMNS), records_failed=len(missing_all),
        execution_timestamp=ts,
        remediation="Re-run warehouse build; check DDL for schema drift.",
    )


# ---------------------------------------------------------------------------
# CTL-07: Reconciliation
# ---------------------------------------------------------------------------

def ctl_07_reconciliation(con: duckdb.DuckDBPyConnection, batch_id: str) -> ControlResult:
    """Verify: raw count == silver count + quarantine count.

    This is the pipeline integrity check. Any unaccounted-for records indicate
    a silent data loss in the pipeline, which is a critical defect in a
    financial-services context.
    """
    ts = datetime.now(UTC).isoformat()

    raw_count = con.execute(
        "SELECT COUNT(*) FROM bronze.raw_transactions WHERE batch_id = ?", [batch_id]
    ).fetchone()[0]
    silver_count = con.execute(
        "SELECT COUNT(*) FROM silver.transactions WHERE batch_id = ?", [batch_id]
    ).fetchone()[0]
    quarantine_count = con.execute(
        "SELECT COUNT(*) FROM silver.quarantine WHERE batch_id = ?", [batch_id]
    ).fetchone()[0]

    accounted = silver_count + quarantine_count
    delta = raw_count - accounted
    status = "PASS" if delta == 0 else "FAIL"

    detail = (
        f"Raw={raw_count} | Silver={silver_count} | Quarantine={quarantine_count} | "
        f"Delta={delta} ({'balanced' if delta == 0 else 'UNACCOUNTED RECORDS'})"
    )

    return ControlResult(
        control_id="CTL-07", control_name="Reconciliation",
        status=status,
        detail=detail,
        records_checked=raw_count, records_failed=abs(delta),
        execution_timestamp=ts,
        remediation=(
            "Investigate Silver transformation for record loss. "
            "Check quarantine logic for records dropped without logging."
        ) if delta != 0 else "",
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_controls(
    batch_id: str,
    config_path: str | Path = "config/config.yaml",
    db_path: str | None = None,
) -> dict[str, Any]:
    """Run all 7 controls and return a structured control report.

    Args:
        batch_id:    The batch to evaluate.
        config_path: Path to config.yaml.
        db_path:     DuckDB file path. Falls back to config value.

    Returns:
        {
            "results": list of control result dicts,
            "pass_count": int,
            "fail_count": int,
            "overall_status": "PASS" | "FAIL",
        }
    """
    cfg = _load_config(config_path)
    db_path = db_path or cfg["paths"]["db_path"]
    max_amount = cfg["controls"]["max_transaction_amount"]
    sla_hours = cfg["controls"]["freshness_sla_hours"]
    valid_statuses = [s.upper() for s in cfg["valid_statuses"]]

    log.info("Running data controls | batch=%s | db=%s", batch_id, db_path)
    con = duckdb.connect(db_path, read_only=True)

    results: list[ControlResult] = [
        ctl_01_uniqueness(con),
        ctl_02_referential_integrity(con),
        ctl_03_amount_validation(con, max_amount),
        ctl_04_status_validity(con, valid_statuses),
        ctl_05_freshness(con, sla_hours),
        ctl_06_schema_validation(con),
        ctl_07_reconciliation(con, batch_id),
    ]

    con.close()

    pass_count = sum(1 for r in results if r.status == "PASS")
    fail_count = sum(1 for r in results if r.status == "FAIL")
    overall = "PASS" if fail_count == 0 else "FAIL"

    log.info(
        "Controls complete | overall=%s | PASS=%d | FAIL=%d",
        overall, pass_count, fail_count,
    )
    for r in results:
        level = log.warning if r.status == "FAIL" else log.info
        level("  [%s] %s — %s", r.status, r.control_id, r.detail)

    return {
        "results": [r.to_dict() for r in results],
        "pass_count": pass_count,
        "fail_count": fail_count,
        "overall_status": overall,
    }

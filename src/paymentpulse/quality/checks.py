"""
PaymentPulse — Data Quality Framework
======================================
Runs structured data-quality checks against the Silver layer and produces
PASS / WARN / FAIL results per check, plus an aggregate quality score.

Why this exists: A data-quality framework makes data problems visible and
measurable rather than silent. Each check has a threshold (from config) so
the same check can pass in dev (lenient) and fail in prod (strict). The
structured output (one row per check) makes it easy to trend quality over
time and to build dashboards showing which checks are deteriorating.

The aggregate quality score (0–100) is a weighted average based on the
fraction of records passing each check. This gives a single headline metric
suitable for a data-quality dashboard KPI.

Check structure (per check result row):
  dataset, check_name, check_type, records_checked,
  records_failed, failure_rate, status, execution_timestamp
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
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


@dataclass
class DQResult:
    """A single data-quality check result."""

    dataset: str
    check_name: str
    check_type: str
    records_checked: int
    records_failed: int
    failure_rate: float
    status: str          # PASS / WARN / FAIL
    execution_timestamp: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _evaluate_status(failure_rate: float, warn_threshold: float, fail_threshold: float) -> str:
    """Return PASS / WARN / FAIL based on failure rate vs thresholds."""
    if failure_rate > fail_threshold:
        return "FAIL"
    if failure_rate > warn_threshold:
        return "WARN"
    return "PASS"


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_not_null(
    con: duckdb.DuckDBPyConnection,
    table: str,
    column: str,
    warn: float,
    fail: float,
) -> DQResult:
    """Completeness check: count rows where column IS NULL or empty string."""
    ts = datetime.now(UTC).isoformat()
    total = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
    failed = con.execute(
        f"SELECT COUNT(*) FROM {table} WHERE {column} IS NULL OR TRIM(CAST({column} AS VARCHAR)) = ''"  # noqa: S608
    ).fetchone()[0]
    rate = failed / total if total > 0 else 0.0
    return DQResult(
        dataset=table,
        check_name=f"not_null__{column}",
        check_type="COMPLETENESS",
        records_checked=total,
        records_failed=failed,
        failure_rate=round(rate, 6),
        status=_evaluate_status(rate, warn, fail),
        execution_timestamp=ts,
        detail=f"Column '{column}' has {failed} null/empty values",
    )


def check_uniqueness(
    con: duckdb.DuckDBPyConnection,
    table: str,
    column: str,
    warn: float,
    fail: float,
) -> DQResult:
    """Uniqueness check: count duplicate values of column."""
    ts = datetime.now(UTC).isoformat()
    total = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
    dupes = con.execute(f"""
        SELECT COALESCE(SUM(cnt - 1), 0)
        FROM (
            SELECT {column}, COUNT(*) AS cnt
            FROM {table}
            GROUP BY {column}
            HAVING COUNT(*) > 1
        ) t
    """).fetchone()[0]  # noqa: S608
    rate = dupes / total if total > 0 else 0.0
    return DQResult(
        dataset=table,
        check_name=f"unique__{column}",
        check_type="UNIQUENESS",
        records_checked=total,
        records_failed=int(dupes),
        failure_rate=round(rate, 6),
        status=_evaluate_status(rate, warn, fail),
        execution_timestamp=ts,
        detail=f"Column '{column}' has {dupes} duplicate extra rows",
    )


def check_amount_positive(
    con: duckdb.DuckDBPyConnection,
    table: str,
    warn: float,
    fail: float,
) -> DQResult:
    """Validity check: amount must be > 0."""
    ts = datetime.now(UTC).isoformat()
    total = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
    failed = con.execute(
        f"SELECT COUNT(*) FROM {table} WHERE amount IS NULL OR amount <= 0"  # noqa: S608
    ).fetchone()[0]
    rate = failed / total if total > 0 else 0.0
    return DQResult(
        dataset=table,
        check_name="amount_positive",
        check_type="VALIDITY",
        records_checked=total,
        records_failed=failed,
        failure_rate=round(rate, 6),
        status=_evaluate_status(rate, warn, fail),
        execution_timestamp=ts,
        detail=f"{failed} rows with null or non-positive amount",
    )


def check_valid_values(
    con: duckdb.DuckDBPyConnection,
    table: str,
    column: str,
    allowed: list[str],
    warn: float,
    fail: float,
) -> DQResult:
    """Validity check: column value must be in allowed set."""
    ts = datetime.now(UTC).isoformat()
    total = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
    placeholders = ", ".join(["?"] * len(allowed))
    failed = con.execute(
        f"SELECT COUNT(*) FROM {table} WHERE {column} NOT IN ({placeholders})",  # noqa: S608
        allowed,
    ).fetchone()[0]
    rate = failed / total if total > 0 else 0.0
    return DQResult(
        dataset=table,
        check_name=f"valid_values__{column}",
        check_type="VALIDITY",
        records_checked=total,
        records_failed=failed,
        failure_rate=round(rate, 6),
        status=_evaluate_status(rate, warn, fail),
        execution_timestamp=ts,
        detail=f"{failed} rows where '{column}' is not in allowed set",
    )


def check_referential_integrity(
    con: duckdb.DuckDBPyConnection,
    child_table: str,
    child_column: str,
    parent_table: str,
    parent_column: str,
    warn: float,
    fail: float,
) -> DQResult:
    """Referential integrity check: child column must have a matching parent row."""
    ts = datetime.now(UTC).isoformat()
    total = con.execute(f"SELECT COUNT(*) FROM {child_table}").fetchone()[0]  # noqa: S608
    failed = con.execute(f"""
        SELECT COUNT(*)
        FROM {child_table} c
        LEFT JOIN {parent_table} p ON c.{child_column} = p.{parent_column}
        WHERE p.{parent_column} IS NULL
    """).fetchone()[0]  # noqa: S608
    rate = failed / total if total > 0 else 0.0
    return DQResult(
        dataset=child_table,
        check_name=f"ref_integrity__{child_column}__{parent_table}",
        check_type="REFERENTIAL_INTEGRITY",
        records_checked=total,
        records_failed=failed,
        failure_rate=round(rate, 6),
        status=_evaluate_status(rate, warn, fail),
        execution_timestamp=ts,
        detail=f"{failed} rows in {child_table}.{child_column} with no match in {parent_table}",
    )


def check_freshness(
    con: duckdb.DuckDBPyConnection,
    table: str,
    ts_column: str,
    sla_hours: int,
) -> DQResult:
    """Freshness check: latest record must be within SLA hours of now."""
    ts_now = datetime.now(UTC).isoformat()
    total = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
    latest = con.execute(
        f"SELECT MAX({ts_column}) FROM {table}"  # noqa: S608
    ).fetchone()[0]

    if latest is None:
        return DQResult(
            dataset=table, check_name="pipeline_freshness", check_type="FRESHNESS",
            records_checked=total, records_failed=total, failure_rate=1.0,
            status="FAIL", execution_timestamp=ts_now,
            detail="No records found in table",
        )

    from datetime import timedelta
    cutoff = datetime.now(UTC) - timedelta(hours=sla_hours)
    # latest may be a string or datetime
    if isinstance(latest, str):
        from paymentpulse.warehouse.warehouse import _parse_timestamp
        latest_dt = _parse_timestamp(latest)
    else:
        latest_dt = latest
        if latest_dt.tzinfo is None:
            latest_dt = latest_dt.replace(tzinfo=UTC)

    if latest_dt is None or latest_dt < cutoff:
        return DQResult(
            dataset=table, check_name="pipeline_freshness", check_type="FRESHNESS",
            records_checked=total, records_failed=1, failure_rate=1.0,
            status="FAIL", execution_timestamp=ts_now,
            detail=f"Latest record at {latest_dt} is older than SLA ({sla_hours}h)",
        )

    return DQResult(
        dataset=table, check_name="pipeline_freshness", check_type="FRESHNESS",
        records_checked=total, records_failed=0, failure_rate=0.0,
        status="PASS", execution_timestamp=ts_now,
        detail=f"Latest record at {latest_dt} is within SLA",
    )


def check_volume(
    con: duckdb.DuckDBPyConnection,
    table: str,
    baseline: int,
    threshold: float,
) -> DQResult:
    """Volume anomaly check: current count must be within ±threshold of baseline."""
    ts = datetime.now(UTC).isoformat()
    count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
    lower = baseline * (1 - threshold)
    upper = baseline * (1 + threshold)
    is_anomaly = not (lower <= count <= upper)
    rate = 0.0 if not is_anomaly else 1.0
    status = "FAIL" if is_anomaly else "PASS"
    return DQResult(
        dataset=table, check_name="volume_anomaly", check_type="VOLUME",
        records_checked=count, records_failed=0, failure_rate=rate,
        status=status, execution_timestamp=ts,
        detail=(
            f"Count {count} {'outside' if is_anomaly else 'within'} "
            f"expected range [{int(lower)}, {int(upper)}]"
        ),
    )


# ---------------------------------------------------------------------------
# Aggregate quality score
# ---------------------------------------------------------------------------

def compute_quality_score(results: list[DQResult]) -> float:
    """Compute an overall data quality score (0–100).

    Scoring logic:
      PASS  → 1.0 contribution
      WARN  → 0.5 contribution
      FAIL  → 0.0 contribution

    The final score is the mean across all checks × 100.
    """
    if not results:
        return 0.0
    weights = {"PASS": 1.0, "WARN": 0.5, "FAIL": 0.0}
    total = sum(weights.get(r.status, 0.0) for r in results)
    return round(total / len(results) * 100, 1)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_dq_checks(
    config_path: str | Path = "config/config.yaml",
    db_path: str | None = None,
    baseline_txn_count: int | None = None,
) -> dict[str, Any]:
    """Run all DQ checks against the Silver layer and return a structured report.

    Args:
        config_path:          Path to config.yaml.
        db_path:              DuckDB file path. Falls back to config value.
        baseline_txn_count:   Expected transaction count for volume check.
                              Defaults to config dataset.num_transactions.

    Returns:
        {
            "results": list of check result dicts,
            "quality_score": float (0–100),
            "pass_count": int,
            "warn_count": int,
            "fail_count": int,
        }
    """
    cfg = _load_config(config_path)
    db_path = db_path or cfg["paths"]["db_path"]
    warn = cfg["dq_thresholds"]["warn_failure_rate"]
    fail_thresh = cfg["dq_thresholds"]["fail_failure_rate"]
    sla_hours = cfg["controls"]["freshness_sla_hours"]
    vol_threshold = cfg["controls"]["volume_anomaly_threshold"]
    baseline = baseline_txn_count or cfg["dataset"]["num_transactions"]

    valid_statuses = [s.upper() for s in cfg["valid_statuses"]]
    valid_currencies = [c.upper() for c in cfg["valid_currencies"]]
    valid_methods = cfg["payment_methods"]

    log.info("Running DQ checks | db=%s", db_path)
    con = duckdb.connect(db_path, read_only=True)

    results: list[DQResult] = []

    # ── Completeness ────────────────────────────────────────────────────────
    results.append(check_not_null(con, "silver.transactions", "transaction_id", warn, fail_thresh))
    results.append(check_not_null(con, "silver.transactions", "customer_id", warn, fail_thresh))
    results.append(check_not_null(con, "silver.transactions", "merchant_id", warn, fail_thresh))
    results.append(check_not_null(con, "silver.transactions", "amount", warn, fail_thresh))
    results.append(check_not_null(con, "silver.transactions", "ts", warn, fail_thresh))

    # ── Uniqueness ──────────────────────────────────────────────────────────
    results.append(check_uniqueness(con, "silver.transactions", "transaction_id", 0.0, 0.0))

    # ── Validity ────────────────────────────────────────────────────────────
    results.append(check_amount_positive(con, "silver.transactions", warn, fail_thresh))
    results.append(check_valid_values(con, "silver.transactions", "status", valid_statuses, warn, fail_thresh))
    results.append(check_valid_values(con, "silver.transactions", "currency", valid_currencies, warn, fail_thresh))
    results.append(check_valid_values(con, "silver.transactions", "payment_method", valid_methods, warn, fail_thresh))

    # ── Referential integrity ───────────────────────────────────────────────
    results.append(check_referential_integrity(
        con, "silver.transactions", "customer_id",
        "silver.customers", "customer_id", warn, fail_thresh,
    ))
    results.append(check_referential_integrity(
        con, "silver.transactions", "merchant_id",
        "silver.merchants", "merchant_id", warn, fail_thresh,
    ))

    # ── Freshness ───────────────────────────────────────────────────────────
    results.append(check_freshness(con, "silver.transactions", "ts", sla_hours))

    # ── Volume ──────────────────────────────────────────────────────────────
    # Baseline is the total generated count; Silver will be lower due to quarantine
    # so we adjust: expect Silver ≈ baseline × (1 - total_injection_rate)
    total_injection = sum(cfg["dq_injection"].values())
    adjusted_baseline = int(baseline * (1 - total_injection))
    results.append(check_volume(con, "silver.transactions", adjusted_baseline, vol_threshold))

    con.close()

    score = compute_quality_score(results)
    pass_count = sum(1 for r in results if r.status == "PASS")
    warn_count = sum(1 for r in results if r.status == "WARN")
    fail_count = sum(1 for r in results if r.status == "FAIL")

    log.info(
        "DQ complete | score=%.1f | PASS=%d | WARN=%d | FAIL=%d",
        score, pass_count, warn_count, fail_count,
    )

    for r in results:
        level = log.warning if r.status in ("WARN", "FAIL") else log.info
        level("  [%s] %s — %s", r.status, r.check_name, r.detail)

    return {
        "results": [r.to_dict() for r in results],
        "quality_score": score,
        "pass_count": pass_count,
        "warn_count": warn_count,
        "fail_count": fail_count,
    }

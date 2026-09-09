"""
PaymentPulse — End-to-End Pipeline Orchestrator
================================================
Runs all Tier 1 pipeline stages in sequence:
  1. Generate synthetic data
  2. Ingest raw CSVs into Bronze
  3. Transform Bronze → Silver → Gold
  4. Run data-quality checks
  5. Run data controls
  6. Print a run summary

This script is the single entry point for running the full pipeline locally.
It is deliberately simple — one function per stage, called in order.

Usage:
    python pipelines/run_pipeline.py [--config config/config.yaml]

In a production environment this orchestration would be handled by
Airflow, Databricks Workflows, or a similar scheduler. The stage functions
are designed so they can be called independently.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Make src importable when run as a script ─────────────────────────────────
# In a proper installed package (pip install -e .) this wouldn't be needed.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from paymentpulse.controls.controls import run_controls
from paymentpulse.generator.generate import generate
from paymentpulse.ingestion.ingest import ingest
from paymentpulse.quality.checks import run_dq_checks
from paymentpulse.utils.logger import get_logger
from paymentpulse.warehouse.warehouse import build_warehouse

log = get_logger("pipeline")


def run_pipeline(config_path: str = "config/config.yaml") -> None:
    """Execute the full Tier 1 PaymentPulse pipeline."""
    pipeline_start = time.monotonic()
    run_ts = datetime.now(timezone.utc).isoformat()
    log.info("=" * 70)
    log.info("PaymentPulse Pipeline — Tier 1 | Started at %s", run_ts)
    log.info("=" * 70)

    # ── Stage 1: Generate ─────────────────────────────────────────────────
    log.info("STAGE 1/5: Generating synthetic data")
    t0 = time.monotonic()
    gen_result = generate(config_path=config_path)
    batch_id = gen_result["batch_id"]
    log.info(
        "  [OK] Generated | customers=%d | merchants=%d | transactions=%d | %.2fs",
        gen_result["num_customers"], gen_result["num_merchants"],
        gen_result["num_transactions"], time.monotonic() - t0,
    )

    # ── Stage 2: Ingest → Bronze ──────────────────────────────────────────
    log.info("STAGE 2/5: Ingesting to Bronze")
    t0 = time.monotonic()
    ingest_result = ingest(
        transactions_path=gen_result["transactions_path"],
        customers_path=gen_result["customers_path"],
        merchants_path=gen_result["merchants_path"],
        batch_id=batch_id,
        config_path=config_path,
    )
    for tbl, info in ingest_result.items():
        if tbl == "batch_id":
            continue
        log.info("  [OK] Ingested %s | status=%s", tbl, info.get("status"))
    log.info("  Ingestion completed in %.2fs", time.monotonic() - t0)

    # ── Stage 3: Transform → Silver → Gold ───────────────────────────────
    log.info("STAGE 3/5: Building Silver + Gold warehouse")
    t0 = time.monotonic()
    wh_result = build_warehouse(batch_id=batch_id, config_path=config_path)
    silver = wh_result["silver"]
    gold = wh_result["gold"]
    log.info(
        "  [OK] Silver | transactions=%d | quarantine=%d",
        silver["silver_count"], silver["quarantine_count"],
    )
    log.info(
        "  [OK] Gold | fact_transactions=%d | dim_customer=%d | dim_merchant=%d | dim_date=%d",
        gold["fact_transactions"], gold["dim_customer"],
        gold["dim_merchant"], gold["dim_date"],
    )
    log.info("  Warehouse build completed in %.2fs", time.monotonic() - t0)

    # ── Stage 4: Data Quality ─────────────────────────────────────────────
    log.info("STAGE 4/5: Running DQ checks")
    t0 = time.monotonic()
    dq_result = run_dq_checks(config_path=config_path)
    log.info(
        "  [OK] DQ Score=%.1f | PASS=%d | WARN=%d | FAIL=%d | %.2fs",
        dq_result["quality_score"],
        dq_result["pass_count"], dq_result["warn_count"], dq_result["fail_count"],
        time.monotonic() - t0,
    )

    # ── Stage 5: Controls ─────────────────────────────────────────────────
    log.info("STAGE 5/5: Running data controls")
    t0 = time.monotonic()
    ctrl_result = run_controls(batch_id=batch_id, config_path=config_path)
    log.info(
        "  [OK] Controls: %s | PASS=%d | FAIL=%d | %.2fs",
        ctrl_result["overall_status"],
        ctrl_result["pass_count"], ctrl_result["fail_count"],
        time.monotonic() - t0,
    )

    # ── Summary ───────────────────────────────────────────────────────────
    elapsed = time.monotonic() - pipeline_start
    log.info("=" * 70)
    log.info("PIPELINE COMPLETE | batch_id=%s | total_time=%.2fs", batch_id, elapsed)
    log.info("")
    log.info("Run Summary")
    log.info("  Batch ID         : %s", batch_id)
    log.info("  Raw transactions : %d", gen_result["num_transactions"])
    log.info("  Silver (clean)   : %d", silver["silver_count"])
    log.info("  Quarantine       : %d", silver["quarantine_count"])
    log.info("  Gold fact rows   : %d", gold["fact_transactions"])
    log.info("  DQ Score         : %.1f/100", dq_result["quality_score"])
    log.info("  DQ PASS/WARN/FAIL: %d/%d/%d",
             dq_result["pass_count"], dq_result["warn_count"], dq_result["fail_count"])
    log.info("  Controls overall : %s (%d PASS, %d FAIL)",
             ctrl_result["overall_status"],
             ctrl_result["pass_count"], ctrl_result["fail_count"])
    log.info("  Database         : data/paymentpulse.duckdb")
    log.info("=" * 70)

    # Print DQ failures for visibility
    dq_failures = [r for r in dq_result["results"] if r["status"] in ("WARN", "FAIL")]
    if dq_failures:
        log.warning("DQ checks needing attention:")
        for r in dq_failures:
            log.warning("  [%s] %s — %s", r["status"], r["check_name"], r["detail"])

    ctrl_failures = [r for r in ctrl_result["results"] if r["status"] == "FAIL"]
    if ctrl_failures:
        log.warning("Control failures:")
        for r in ctrl_failures:
            log.warning("  [FAIL] %s — %s", r["control_id"], r["detail"])


def main() -> None:
    parser = argparse.ArgumentParser(description="PaymentPulse Tier 1 Pipeline")
    parser.add_argument(
        "--config", default="config/config.yaml",
        help="Path to config.yaml (default: config/config.yaml)",
    )
    args = parser.parse_args()
    run_pipeline(config_path=args.config)


if __name__ == "__main__":
    main()

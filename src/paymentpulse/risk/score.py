"""
PaymentPulse — Risk Pipeline Entry Point
========================================
Orchestrates feature extraction, anomaly modeling, and explanation generation,
persisting results into `gold.fact_transactions_risk` in DuckDB.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import yaml

from paymentpulse.risk.explain import add_explanations
from paymentpulse.risk.features import extract_features
from paymentpulse.risk.model import AnomalyRiskModel
from paymentpulse.utils.logger import get_logger

log = get_logger(__name__)


def run_risk_scoring(
    config_path: str | Path = "config/config.yaml",
    db_path: str | None = None,
) -> dict[str, Any]:
    """Execute risk scoring and write results to gold.fact_transactions_risk.

    Returns:
        Summary dict containing risk tier distributions.
    """
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    db_path = db_path or cfg["paths"]["db_path"]
    log.info("Running risk scoring pipeline against %s", db_path)

    con = duckdb.connect(db_path)

    # 1. Feature engineering
    features_df = extract_features(con)

    # 2. Model prediction
    model = AnomalyRiskModel()
    scored_df = model.fit_predict(features_df)

    # 3. Explainability
    explained_df = add_explanations(scored_df)

    # 4. Save to Gold table in DuckDB
    con.execute("""
        CREATE TABLE IF NOT EXISTS gold.fact_transactions_risk (
            transaction_id VARCHAR PRIMARY KEY,
            amount DOUBLE,
            risk_score DOUBLE,
            risk_tier VARCHAR,
            risk_reasons VARCHAR,
            amount_ratio DOUBLE,
            merchant_failure_rate DOUBLE,
            country_mismatch INTEGER,
            _scored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    con.execute("DELETE FROM gold.fact_transactions_risk")

    persist_df = explained_df[[
        "transaction_id",
        "amount",
        "risk_score",
        "risk_tier",
        "risk_reasons",
        "amount_ratio",
        "merchant_failure_rate",
        "country_mismatch",
    ]]

    cols_str = ", ".join(persist_df.columns)
    con.execute(f"INSERT INTO gold.fact_transactions_risk ({cols_str}) SELECT * FROM persist_df")

    high_count = int((explained_df["risk_tier"] == "HIGH").sum())
    med_count = int((explained_df["risk_tier"] == "MEDIUM").sum())
    low_count = int((explained_df["risk_tier"] == "LOW").sum())

    log.info(
        "Risk scores written to gold.fact_transactions_risk | HIGH=%d, MEDIUM=%d, LOW=%d",
        high_count, med_count, low_count,
    )

    con.close()
    return {
        "total_scored": len(explained_df),
        "high_risk": high_count,
        "medium_risk": med_count,
        "low_risk": low_count,
    }

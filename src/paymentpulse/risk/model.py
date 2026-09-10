"""
PaymentPulse — Unsupervised Anomaly / Risk Scoring Model
=========================================================
Uses Scikit-Learn Isolation Forest to score transactions for anomalousness.

Why Isolation Forest:
1. No ground-truth fraud labels exist in this dataset. Supervised classifiers
   (like XGBoost or Random Forest trained on fake labels) would give an
   illusion of "fraud detection". Isolation Forest isolates anomalies based
   purely on tree partitioning depth.
2. It generates continuous decision function scores that map cleanly to a
   0–100 calibrated Risk Score.
3. Fast to train and predict across 75,000+ transactions.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from paymentpulse.utils.logger import get_logger

log = get_logger(__name__)

FEATURE_COLS = [
    "amount",
    "hour_of_day",
    "is_weekend",
    "customer_avg_amount",
    "customer_txn_count",
    "merchant_failure_rate",
    "country_mismatch",
    "amount_ratio",
]


class AnomalyRiskModel:
    """Isolation Forest anomaly detection calibrated to a 0–100 risk score."""

    def __init__(self, contamination: float = 0.03, random_state: int = 42) -> None:
        self.contamination = contamination
        self.random_state = random_state
        self.model = IsolationForest(
            contamination=contamination,
            random_state=random_state,
            n_estimators=100,
            n_jobs=-1,
        )
        self.is_fitted = False

    def fit_predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """Fit the model on engineered features and produce calibrated risk scores.

        Args:
            df: DataFrame containing FEATURE_COLS.

        Returns:
            DataFrame with 'anomaly_score', 'risk_score' (0-100), and 'risk_tier' (LOW/MEDIUM/HIGH).
        """
        log.info("Fitting Isolation Forest model on %d records...", len(df))
        X = df[FEATURE_COLS].fillna(0)

        self.model.fit(X)
        self.is_fitted = True

        # raw score: lower means more anomalous
        raw_scores = self.model.score_samples(X)

        # Invert and calibrate raw score to 0–100 range
        # Isolation Forest score_samples is roughly in [-0.8, -0.2]
        min_s = np.percentile(raw_scores, 1)
        max_s = np.percentile(raw_scores, 99)

        clipped = np.clip(raw_scores, min_s, max_s)
        # Normalized inverse: 0 = normal, 100 = most anomalous
        norm_scores = (max_s - clipped) / (max_s - min_s + 1e-6) * 100.0
        risk_scores = np.round(norm_scores, 1)

        result_df = df.copy()
        result_df["risk_score"] = risk_scores

        # Risk-policy tiers based on calibrated score thresholds.
        # Thresholds are configurable and should be tuned against labeled outcomes
        # if production ground truth becomes available.
        result_df["risk_tier"] = pd.cut(
            result_df["risk_score"],
            bins=[-float("inf"), 45.0, 75.0, float("inf")],
            labels=["LOW", "MEDIUM", "HIGH"],
        ).astype(str)

        log.info(
            "Risk scoring complete | Breakdown: LOW=%d, MEDIUM=%d, HIGH=%d",
            (result_df["risk_tier"] == "LOW").sum(),
            (result_df["risk_tier"] == "MEDIUM").sum(),
            (result_df["risk_tier"] == "HIGH").sum(),
        )
        return result_df

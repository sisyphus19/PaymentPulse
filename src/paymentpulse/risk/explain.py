"""
PaymentPulse — Explainability Layer for Anomaly / Risk Scoring
===============================================================
Generates human-readable, auditable reasons for transactions flagged
with Medium or High risk.

Why this exists:
In banking operations and financial crime intelligence, an ML score
without explanation is unusable. Compliance officers and risk analysts
must explain *why* a payment was placed on hold or escalated to a
human investigator.

Provides top-3 human-readable reasons, e.g.:
  1. Transaction amount (£4,200.00) is 6.5x customer historical average.
  2. Cross-border transaction mismatch (GB resident transacting in US).
  3. High merchant failure rate (38.5% historical decline rate).
"""

from __future__ import annotations

import pandas as pd


def explain_transaction(row: pd.Series) -> str:
    """Generate up to 3 prioritized reasons why a transaction was flagged as risky.

    Args:
        row: Series containing transaction features and risk score.

    Returns:
        Semicolon-separated string of top reasons.
    """
    reasons: list[str] = []

    # Reason 1: High amount ratio vs historical average
    amount_ratio = float(row.get("amount_ratio", 1.0))
    amount = float(row.get("amount", 0.0))
    cust_avg = float(row.get("customer_avg_amount", amount))
    if amount_ratio >= 3.0:
        reasons.append(
            f"Transaction amount ({amount:.2f}) is {amount_ratio:.1f}x customer historical average ({cust_avg:.2f})"
        )
    elif amount > 5000:
        reasons.append(f"Unusually high absolute transaction amount ({amount:.2f})")

    # Reason 2: Geographic mismatch
    if int(row.get("country_mismatch", 0)) == 1:
        reasons.append(
            f"Cross-border anomaly: customer country ({row.get('cust_country', 'Unknown')}) differs from transaction country ({row.get('txn_country', 'Unknown')})"
        )

    # Reason 3: Elevated merchant failure history
    merch_fail = float(row.get("merchant_failure_rate", 0.0))
    if merch_fail >= 0.20:
        reasons.append(
            f"Elevated merchant risk profile ({merch_fail * 100:.1f}% historical payment failure rate)"
        )

    # Reason 4: Low frequency / new profile
    cust_txns = int(row.get("customer_txn_count", 1))
    if cust_txns <= 5 and amount > 500:
        reasons.append("Sparse customer history: high value transaction on nascent account")

    # Reason 5: Off-hours or weekend spike
    hour = int(row.get("hour_of_day", 12))
    if hour in (1, 2, 3, 4) and amount > 1000:
        reasons.append(f"Off-peak execution window ({hour:02d}:00 UTC) with substantial value")

    if not reasons:
        if row.get("risk_tier") == "HIGH":
            reasons.append("Multi-dimensional multivariate outlier detected by Isolation Forest")
        else:
            reasons.append("Standard risk profile within baseline expectations")

    return " | ".join(reasons[:3])


def add_explanations(df: pd.DataFrame) -> pd.DataFrame:
    """Apply explainability to a scored transaction DataFrame."""
    explanations = []
    for _, row in df.iterrows():
        if row["risk_tier"] in ("HIGH", "MEDIUM"):
            explanations.append(explain_transaction(row))
        else:
            explanations.append("Within standard baseline behavior")

    df_out = df.copy()
    df_out["risk_reasons"] = explanations
    return df_out

"""
Unit tests for PaymentPulse Risk & Anomaly Detection module.
"""

import pandas as pd
import pytest

from paymentpulse.risk.explain import add_explanations, explain_transaction
from paymentpulse.risk.model import AnomalyRiskModel


@pytest.fixture
def sample_features_df():
    """Create a synthetic DataFrame for testing risk models."""
    return pd.DataFrame([
        {
            "transaction_id": "tx_normal_1",
            "amount": 45.0,
            "hour_of_day": 14,
            "is_weekend": 0,
            "customer_avg_amount": 50.0,
            "customer_txn_count": 25,
            "merchant_failure_rate": 0.02,
            "country_mismatch": 0,
            "amount_ratio": 0.9,
            "cust_country": "GB",
            "txn_country": "GB",
        },
        {
            "transaction_id": "tx_normal_2",
            "amount": 60.0,
            "hour_of_day": 11,
            "is_weekend": 0,
            "customer_avg_amount": 55.0,
            "customer_txn_count": 30,
            "merchant_failure_rate": 0.03,
            "country_mismatch": 0,
            "amount_ratio": 1.09,
            "cust_country": "GB",
            "txn_country": "GB",
        },
        {
            "transaction_id": "tx_anom_high_ratio",
            "amount": 5200.0,
            "hour_of_day": 3,
            "is_weekend": 1,
            "customer_avg_amount": 40.0,
            "customer_txn_count": 2,
            "merchant_failure_rate": 0.45,
            "country_mismatch": 1,
            "amount_ratio": 130.0,
            "cust_country": "GB",
            "txn_country": "US",
        },
        {
            "transaction_id": "tx_normal_3",
            "amount": 75.0,
            "hour_of_day": 16,
            "is_weekend": 0,
            "customer_avg_amount": 70.0,
            "customer_txn_count": 40,
            "merchant_failure_rate": 0.01,
            "country_mismatch": 0,
            "amount_ratio": 1.07,
            "cust_country": "GB",
            "txn_country": "GB",
        },
    ] * 25)  # Repeat to give sufficient sample size for Isolation Forest


def test_anomaly_risk_model(sample_features_df):
    model = AnomalyRiskModel(contamination=0.1, random_state=42)
    scored = model.fit_predict(sample_features_df)

    assert "risk_score" in scored.columns
    assert "risk_tier" in scored.columns
    assert (scored["risk_score"] >= 0).all()
    assert (scored["risk_score"] <= 100).all()
    assert set(scored["risk_tier"].unique()).issubset({"LOW", "MEDIUM", "HIGH"})


def test_explainability(sample_features_df):
    model = AnomalyRiskModel(contamination=0.1, random_state=42)
    scored = model.fit_predict(sample_features_df)
    explained = add_explanations(scored)

    assert "risk_reasons" in explained.columns

    # High anomaly row should have meaningful explanatory reasons
    high_anom_row = explained[explained["transaction_id"] == "tx_anom_high_ratio"].iloc[0]
    reason = explain_transaction(high_anom_row)
    assert len(reason) > 0
    assert "historical average" in reason or "Cross-border" in reason or "merchant risk" in reason

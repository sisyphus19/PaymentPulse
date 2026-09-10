"""
PaymentPulse — Behavioral Feature Engineering for Anomaly / Risk Scoring
========================================================================
Extracts and engineers behavioral transaction features from the Silver layer.

Why this exists:
In banking, raw transaction amount alone is an inadequate signal for risk.
A £5,000 transaction by a corporate client is normal; the same amount by a
student transacting from an unfamiliar country is anomalous.

Engineered features:
  1. amount: The transaction amount.
  2. customer_avg_amount: Historical mean transaction amount for this customer.
  3. amount_ratio: amount / (customer_avg_amount + 1e-5). Ratio of current amount to customer mean.
  4. customer_txn_count: Total historical transaction frequency of this customer.
  5. merchant_failure_rate: Proportion of failures associated with this merchant.
  6. is_weekend: Binary flag indicating weekend transaction.
  7. hour_of_day: Intraday hour (0–23).
  8. country_mismatch: 1 if transaction country != customer residence country, else 0.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from paymentpulse.utils.logger import get_logger

log = get_logger(__name__)


def extract_features(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Extract and engineer transaction-level features from Silver and reference tables.

    Returns:
        DataFrame containing transaction_id, raw features, and engineered ratios.
    """
    log.info("Extracting behavioral features for anomaly detection...")

    query = """
    WITH customer_stats AS (
        SELECT
            customer_id,
            ROUND(AVG(amount), 2) AS customer_avg_amount,
            COUNT(*) AS customer_txn_count
        FROM silver.transactions
        GROUP BY customer_id
    ),
    merchant_stats AS (
        SELECT
            m.merchant_id,
            ROUND(
                COUNT(CASE WHEN t.status = 'FAILED' THEN 1 END) * 1.0 / NULLIF(COUNT(*), 0),
                4
            ) AS merchant_failure_rate
        FROM silver.merchants m
        LEFT JOIN silver.transactions t ON m.merchant_id = t.merchant_id
        GROUP BY m.merchant_id
    )
    SELECT
        t.transaction_id,
        t.customer_id,
        t.merchant_id,
        t.amount,
        t.status,
        t.payment_method,
        t.country AS txn_country,
        c.country AS cust_country,
        EXTRACT(HOUR FROM t.ts) AS hour_of_day,
        CAST(DAYOFWEEK(t.ts) IN (0, 6) AS INTEGER) AS is_weekend,
        COALESCE(cs.customer_avg_amount, t.amount) AS customer_avg_amount,
        COALESCE(cs.customer_txn_count, 1) AS customer_txn_count,
        COALESCE(ms.merchant_failure_rate, 0.0) AS merchant_failure_rate,
        CASE WHEN t.country != c.country THEN 1 ELSE 0 END AS country_mismatch,
        ROUND(t.amount / (COALESCE(cs.customer_avg_amount, t.amount) + 0.01), 2) AS amount_ratio
    FROM silver.transactions t
    LEFT JOIN silver.customers c ON t.customer_id = c.customer_id
    LEFT JOIN customer_stats cs ON t.customer_id = cs.customer_id
    LEFT JOIN merchant_stats ms ON t.merchant_id = ms.merchant_id
    """

    df = con.execute(query).df()
    log.info("Extracted %d feature records across %d engineered attributes", len(df), len(df.columns))
    return df

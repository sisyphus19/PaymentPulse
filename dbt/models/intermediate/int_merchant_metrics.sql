WITH txns AS (
    SELECT * FROM {{ ref('stg_transactions') }}
),
merch AS (
    SELECT * FROM {{ ref('stg_merchants') }}
)

SELECT
    m.merchant_id,
    m.merchant_name,
    m.merchant_category,
    m.merchant_country,
    m.risk_category,
    COUNT(t.transaction_id) AS total_transactions,
    ROUND(SUM(t.amount), 2) AS total_processed_gbp,
    ROUND(AVG(t.amount), 2) AS avg_ticket_size_gbp,
    COUNT(CASE WHEN t.status = 'FAILED' THEN 1 END) AS failed_transactions,
    ROUND(100.0 * COUNT(CASE WHEN t.status = 'FAILED' THEN 1 END) / NULLIF(COUNT(t.transaction_id), 0), 2) AS failure_rate_pct
FROM merch m
LEFT JOIN txns t ON m.merchant_id = t.merchant_id
GROUP BY
    m.merchant_id,
    m.merchant_name,
    m.merchant_category,
    m.merchant_country,
    m.risk_category

WITH txns AS (
    SELECT * FROM {{ ref('stg_transactions') }}
),
cust AS (
    SELECT * FROM {{ ref('stg_customers') }}
)

SELECT
    c.customer_id,
    c.customer_name,
    c.customer_segment,
    c.customer_country,
    COUNT(t.transaction_id) AS total_transactions,
    ROUND(SUM(t.amount), 2) AS total_spend_gbp,
    ROUND(AVG(t.amount), 2) AS avg_transaction_amount,
    COUNT(CASE WHEN t.status = 'SUCCESS' THEN 1 END) AS successful_transactions,
    COUNT(CASE WHEN t.status = 'FAILED' THEN 1 END) AS failed_transactions,
    ROUND(100.0 * COUNT(CASE WHEN t.status = 'FAILED' THEN 1 END) / NULLIF(COUNT(t.transaction_id), 0), 2) AS failure_rate_pct
FROM cust c
LEFT JOIN txns t ON c.customer_id = t.customer_id
GROUP BY
    c.customer_id,
    c.customer_name,
    c.customer_segment,
    c.customer_country

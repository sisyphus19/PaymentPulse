-- PaymentPulse — SQL Analytics Queries
-- =====================================
-- These queries are written against the Gold dimensional model in DuckDB.
-- They are intentionally Snowflake-compatible (no DuckDB-only syntax used).
-- Target: gold.fact_transactions (ft) + dimension tables.
--
-- Each query begins with a comment stating:
--   1. The business question it answers.
--   2. How it would be used in practice.
-- -------------------------------------------------------------------------


-- ── Query 01: Daily Transaction Volume & Value ───────────────────────────────
-- Business question: What is the volume and total GBP value of payments
-- processed each day? The primary KPI for a payments operations team.
-- Used for: daily ops reporting, trend monitoring, SLA tracking.

SELECT
    d.full_date                                     AS transaction_date,
    COUNT(ft.transaction_id)                        AS total_transactions,
    SUM(ft.amount)                                  AS total_value_gbp,
    ROUND(AVG(ft.amount), 2)                        AS avg_transaction_amount,
    COUNT(CASE WHEN ft.is_success THEN 1 END)       AS successful_transactions,
    COUNT(CASE WHEN ft.is_failed THEN 1 END)        AS failed_transactions
FROM gold.fact_transactions ft
JOIN gold.dim_date d ON ft.date_sk = d.date_sk
GROUP BY d.full_date
ORDER BY d.full_date DESC;


-- ── Query 02: Overall Payment Success, Failure & Reversal Rates ─────────────
-- Business question: What fraction of payments succeed? What are the
-- failure and reversal rates? Baseline health metric for any payments platform.
-- Used for: executive dashboard KPI, benchmarking against industry rates.

SELECT
    status,
    COUNT(*)                                             AS transaction_count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)  AS percentage
FROM gold.fact_transactions
GROUP BY status
ORDER BY transaction_count DESC;


-- ── Query 03: Failure Rate by Payment Method ─────────────────────────────────
-- Business question: Which payment methods have the highest failure rates?
-- High failure rates on a specific method may indicate routing issues,
-- bank decline policies, or fraud rule misfires.
-- Used for: payment-method optimisation, routing decisions.

SELECT
    pm.payment_method,
    pm.method_group,
    COUNT(*)                                              AS total_transactions,
    SUM(CASE WHEN ft.is_failed THEN 1 ELSE 0 END)        AS failed_transactions,
    ROUND(
        100.0 * SUM(CASE WHEN ft.is_failed THEN 1 ELSE 0 END) / COUNT(*),
        2
    )                                                     AS failure_rate_pct,
    ROUND(AVG(ft.amount), 2)                              AS avg_amount_gbp
FROM gold.fact_transactions ft
JOIN gold.dim_payment_method pm ON ft.payment_method_sk = pm.payment_method_sk
GROUP BY pm.payment_method, pm.method_group
ORDER BY failure_rate_pct DESC;


-- ── Query 04: Top 10 Merchants by Transaction Value ──────────────────────────
-- Business question: Who are the highest-value merchants on the platform?
-- Used for: merchant relationship management, revenue analysis,
-- concentration risk assessment.

SELECT
    m.name                      AS merchant_name,
    m.category                  AS merchant_category,
    m.risk_category,
    COUNT(ft.transaction_id)    AS total_transactions,
    ROUND(SUM(ft.amount), 2)    AS total_value_gbp,
    ROUND(AVG(ft.amount), 2)    AS avg_transaction_value,
    ROUND(
        100.0 * SUM(CASE WHEN ft.is_failed THEN 1 ELSE 0 END) / COUNT(*),
        2
    )                           AS failure_rate_pct
FROM gold.fact_transactions ft
JOIN gold.dim_merchant m ON ft.merchant_sk = m.merchant_sk
GROUP BY m.merchant_id, m.name, m.category, m.risk_category
ORDER BY total_value_gbp DESC
LIMIT 10;


-- ── Query 05: Top 10 Merchants by Failure Rate ───────────────────────────────
-- Business question: Which merchants have abnormally high payment failure rates?
-- Elevated merchant failure rates may indicate merchant-side technical issues,
-- fraud targeting, or category-level banking restrictions.
-- Used for: merchant risk monitoring, operations escalation.

SELECT
    m.name                      AS merchant_name,
    m.category                  AS merchant_category,
    m.risk_category,
    m.country                   AS merchant_country,
    COUNT(ft.transaction_id)    AS total_transactions,
    SUM(CASE WHEN ft.is_failed THEN 1 ELSE 0 END)   AS failed_transactions,
    ROUND(
        100.0 * SUM(CASE WHEN ft.is_failed THEN 1 ELSE 0 END) / COUNT(*),
        2
    )                           AS failure_rate_pct
FROM gold.fact_transactions ft
JOIN gold.dim_merchant m ON ft.merchant_sk = m.merchant_sk
GROUP BY m.merchant_id, m.name, m.category, m.risk_category, m.country
HAVING COUNT(ft.transaction_id) >= 10   -- exclude merchants with too few transactions
ORDER BY failure_rate_pct DESC
LIMIT 10;


-- ── Query 06: Transaction Volume & Value by Country ──────────────────────────
-- Business question: Where geographically are our payment flows concentrated?
-- Used for: regulatory reporting, geographic expansion decisions, FX exposure.

SELECT
    ft.country                  AS transaction_country,
    COUNT(*)                    AS total_transactions,
    ROUND(SUM(ft.amount), 2)    AS total_value_gbp,
    ROUND(AVG(ft.amount), 2)    AS avg_value_gbp,
    ROUND(
        100.0 * SUM(CASE WHEN ft.is_failed THEN 1 ELSE 0 END) / COUNT(*),
        2
    )                           AS failure_rate_pct
FROM gold.fact_transactions ft
GROUP BY ft.country
ORDER BY total_transactions DESC
LIMIT 20;


-- ── Query 07: Failure Rate by Country ────────────────────────────────────────
-- Business question: Are payment failures concentrated in specific countries?
-- High geographic failure rates can signal network issues, local regulations,
-- or country-specific fraud patterns.
-- Used for: geographic risk monitoring, routing optimisation.

SELECT
    ft.country,
    COUNT(*)                    AS total_transactions,
    SUM(CASE WHEN ft.is_failed THEN 1 ELSE 0 END)   AS failed,
    ROUND(
        100.0 * SUM(CASE WHEN ft.is_failed THEN 1 ELSE 0 END) / COUNT(*),
        2
    )                           AS failure_rate_pct,
    ROUND(SUM(ft.amount), 2)    AS total_value_gbp
FROM gold.fact_transactions ft
GROUP BY ft.country
HAVING COUNT(*) >= 50
ORDER BY failure_rate_pct DESC;


-- ── Query 08: Payment Method Distribution by Country (Top 10 Countries) ──────
-- Business question: How does payment method preference vary by geography?
-- Used for: product localisation, acquiring strategy, cross-border product design.

WITH ranked_countries AS (
    SELECT country, COUNT(*) AS txn_count
    FROM gold.fact_transactions
    GROUP BY country
    ORDER BY txn_count DESC
    LIMIT 10
)
SELECT
    ft.country,
    pm.payment_method,
    COUNT(*)                    AS transaction_count,
    ROUND(
        100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY ft.country),
        2
    )                           AS pct_within_country
FROM gold.fact_transactions ft
JOIN gold.dim_payment_method pm ON ft.payment_method_sk = pm.payment_method_sk
JOIN ranked_countries rc ON ft.country = rc.country
GROUP BY ft.country, pm.payment_method
ORDER BY ft.country, transaction_count DESC;


-- ── Query 09: Average Transaction Amount by Customer Segment ─────────────────
-- Business question: How does spending behaviour differ across customer segments?
-- Premium customers typically transact in higher amounts; understanding
-- segment behaviour drives product pricing and credit decisions.
-- Used for: customer analytics, product P&L, segment-based targeting.

SELECT
    c.segment                   AS customer_segment,
    COUNT(DISTINCT c.customer_id)       AS customer_count,
    COUNT(ft.transaction_id)            AS total_transactions,
    ROUND(AVG(ft.amount), 2)            AS avg_transaction_amount_gbp,
    ROUND(MEDIAN(ft.amount), 2)         AS median_transaction_amount_gbp,
    ROUND(SUM(ft.amount), 2)            AS total_spend_gbp,
    ROUND(
        100.0 * SUM(CASE WHEN ft.is_failed THEN 1 ELSE 0 END) / COUNT(*),
        2
    )                                   AS failure_rate_pct
FROM gold.fact_transactions ft
JOIN gold.dim_customer c ON ft.customer_sk = c.customer_sk
GROUP BY c.segment
ORDER BY avg_transaction_amount_gbp DESC;


-- ── Query 10: Hourly Transaction Volume (Peak Period Analysis) ────────────────
-- Business question: When during the day is transaction volume highest?
-- Peak load identification is critical for capacity planning, SLA management,
-- and scheduling batch jobs to avoid contention with peak processing windows.
-- Used for: capacity planning, incident pattern analysis, batch scheduling.

SELECT
    EXTRACT(HOUR FROM ft.ts)    AS hour_of_day,
    COUNT(*)                    AS total_transactions,
    ROUND(SUM(ft.amount), 2)    AS total_value_gbp,
    SUM(CASE WHEN ft.is_failed THEN 1 ELSE 0 END)   AS failed_transactions,
    ROUND(
        100.0 * SUM(CASE WHEN ft.is_failed THEN 1 ELSE 0 END) / COUNT(*),
        2
    )                           AS failure_rate_pct
FROM gold.fact_transactions ft
WHERE ft.ts IS NOT NULL
GROUP BY EXTRACT(HOUR FROM ft.ts)
ORDER BY hour_of_day;

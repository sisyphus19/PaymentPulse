-- =============================================================================
-- PaymentPulse — Snowflake Target Architecture: Analytical Views & Aggregations
-- Execution Status: Target Architecture (Not executed locally)
--
-- Demonstrates Materialized Views and analytical optimization for Power BI.
-- =============================================================================

USE DATABASE PAYMENTPULSE_PROD;
USE SCHEMA GOLD;

-- 1. Pre-aggregated Daily Payments Summary
-- Materialized in Snowflake for sub-second dashboard rendering
CREATE OR REPLACE VIEW V_PAYMENT_DAILY_KPIS AS
SELECT
    d.FULL_DATE                             AS METRIC_DATE,
    COUNT(ft.TRANSACTION_ID)                AS TOTAL_TRANSACTIONS,
    SUM(ft.AMOUNT)                          AS TOTAL_VOLUME_GBP,
    ROUND(AVG(ft.AMOUNT), 2)                AS AVG_TICKET_SIZE_GBP,
    COUNT(CASE WHEN ft.IS_SUCCESS THEN 1 END) AS SUCCESS_COUNT,
    COUNT(CASE WHEN ft.IS_FAILED THEN 1 END)  AS FAILED_COUNT,
    ROUND(
        100.0 * COUNT(CASE WHEN ft.IS_FAILED THEN 1 END) / NULLIF(COUNT(ft.TRANSACTION_ID), 0),
        2
    )                                       AS FAILURE_RATE_PCT
FROM FACT_TRANSACTIONS ft
JOIN DIM_DATE d ON ft.DATE_SK = d.DATE_SK
GROUP BY d.FULL_DATE;

-- 2. Merchant Performance & Risk Score View
CREATE OR REPLACE VIEW V_MERCHANT_PERFORMANCE AS
SELECT
    m.MERCHANT_NAME,
    m.MERCHANT_CATEGORY,
    m.RISK_CATEGORY,
    m.MERCHANT_COUNTRY,
    COUNT(ft.TRANSACTION_ID)                AS TRANSACTION_COUNT,
    ROUND(SUM(ft.AMOUNT), 2)                AS TOTAL_PROCESSED_GBP,
    ROUND(
        100.0 * COUNT(CASE WHEN ft.IS_FAILED THEN 1 END) / NULLIF(COUNT(ft.TRANSACTION_ID), 0),
        2
    )                                       AS FAILURE_RATE_PCT
FROM FACT_TRANSACTIONS ft
JOIN DIM_MERCHANT m ON ft.MERCHANT_SK = m.MERCHANT_SK
GROUP BY m.MERCHANT_ID, m.MERCHANT_NAME, m.MERCHANT_CATEGORY, m.RISK_CATEGORY, m.MERCHANT_COUNTRY;

-- =============================================================================
-- PaymentPulse — Gold Layer DDL
-- Dimensional Star Schema for analytics queries.
-- Target Engine: DuckDB / Snowflake compatible
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS gold;

CREATE TABLE IF NOT EXISTS gold.dim_customer (
    customer_sk     INTEGER PRIMARY KEY,
    customer_id     VARCHAR UNIQUE,
    name            VARCHAR,
    email           VARCHAR,
    segment         VARCHAR,
    country         VARCHAR,
    customer_since  DATE
);

CREATE TABLE IF NOT EXISTS gold.dim_merchant (
    merchant_sk     INTEGER PRIMARY KEY,
    merchant_id     VARCHAR UNIQUE,
    name            VARCHAR,
    category        VARCHAR,
    country         VARCHAR,
    risk_category   VARCHAR
);

CREATE TABLE IF NOT EXISTS gold.dim_payment_method (
    payment_method_sk   INTEGER PRIMARY KEY,
    payment_method      VARCHAR UNIQUE,
    method_group        VARCHAR
);

CREATE TABLE IF NOT EXISTS gold.dim_date (
    date_sk         INTEGER PRIMARY KEY,
    full_date       DATE,
    year            INTEGER,
    quarter         INTEGER,
    month           INTEGER,
    month_name      VARCHAR,
    week_of_year    INTEGER,
    day_of_month    INTEGER,
    day_of_week     INTEGER,
    day_name        VARCHAR,
    is_weekend      BOOLEAN
);

CREATE TABLE IF NOT EXISTS gold.fact_transactions (
    transaction_id      VARCHAR PRIMARY KEY,
    customer_sk         INTEGER,
    merchant_sk         INTEGER,
    payment_method_sk   INTEGER,
    date_sk             INTEGER,
    ts                  TIMESTAMP,
    amount              DOUBLE,
    currency            VARCHAR,
    country             VARCHAR,
    channel             VARCHAR,
    device_type         VARCHAR,
    status              VARCHAR,
    is_success          BOOLEAN,
    is_failed           BOOLEAN,
    is_reversed         BOOLEAN,
    batch_id            VARCHAR
);

-- =============================================================================
-- PaymentPulse — Silver Layer DDL
-- Cleaned, typed, deduplicated entities and quarantine table.
-- Target Engine: DuckDB / Snowflake compatible
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS silver;

CREATE TABLE IF NOT EXISTS silver.customers (
    customer_id     VARCHAR PRIMARY KEY,
    name            VARCHAR,
    email           VARCHAR,
    segment         VARCHAR,
    country         VARCHAR,
    customer_since  DATE,
    batch_id        VARCHAR,
    _loaded_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS silver.merchants (
    merchant_id     VARCHAR PRIMARY KEY,
    name            VARCHAR,
    category        VARCHAR,
    country         VARCHAR,
    risk_category   VARCHAR,
    batch_id        VARCHAR,
    _loaded_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS silver.transactions (
    transaction_id  VARCHAR PRIMARY KEY,
    customer_id     VARCHAR,
    merchant_id     VARCHAR,
    payment_method  VARCHAR,
    ts              TIMESTAMP,
    amount          DOUBLE,
    currency        VARCHAR,
    country         VARCHAR,
    channel         VARCHAR,
    device_type     VARCHAR,
    status          VARCHAR,
    batch_id        VARCHAR,
    _loaded_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS silver.quarantine (
    transaction_id   VARCHAR,
    raw_record       VARCHAR,   -- JSON representation of raw record
    rejection_reason VARCHAR,   -- Detailed reason for rejection
    batch_id         VARCHAR,
    _quarantined_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- PaymentPulse — Bronze Layer DDL
-- Raw schema storing unparsed strings and ingestion audit metadata.
-- Target Engine: DuckDB / Snowflake compatible
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS bronze;

CREATE TABLE IF NOT EXISTS bronze.raw_transactions (
    transaction_id  VARCHAR,
    customer_id     VARCHAR,
    merchant_id     VARCHAR,
    payment_method  VARCHAR,
    timestamp       VARCHAR,   -- raw string, parsed in Silver
    amount          VARCHAR,   -- raw string, parsed and checked in Silver
    currency        VARCHAR,
    country         VARCHAR,
    channel         VARCHAR,
    device_type     VARCHAR,
    status          VARCHAR,
    batch_id        VARCHAR,
    _ingested_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bronze.raw_customers (
    customer_id     VARCHAR,
    name            VARCHAR,
    email           VARCHAR,
    segment         VARCHAR,
    country         VARCHAR,
    customer_since  VARCHAR,
    batch_id        VARCHAR,
    _ingested_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bronze.raw_merchants (
    merchant_id     VARCHAR,
    name            VARCHAR,
    category        VARCHAR,
    country         VARCHAR,
    risk_category   VARCHAR,
    batch_id        VARCHAR,
    _ingested_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bronze.ingestion_audit (
    audit_id            VARCHAR PRIMARY KEY,
    batch_id            VARCHAR NOT NULL,
    source_file         VARCHAR,
    table_name          VARCHAR,
    schema_version      VARCHAR,
    ingestion_timestamp TIMESTAMP,
    record_count        BIGINT,
    success_count       BIGINT,
    failure_count       BIGINT,
    status              VARCHAR,  -- SUCCESS / SCHEMA_ERROR / READ_ERROR
    error_detail        VARCHAR
);

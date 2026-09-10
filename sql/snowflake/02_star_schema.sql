-- =============================================================================
-- PaymentPulse — Snowflake Target Architecture: Star Schema DDL
-- Execution Status: Target Architecture (Not executed locally)
--
-- Optimization Decisions for Snowflake:
-- 1. CLUSTER BY (ts::DATE): Snowflake automatically manages micro-partitions (~50-500MB).
--    Clustering by date guarantees partition pruning on time-range queries without
--    manual indexing.
-- 2. Constraints: Snowflake does not enforce UNIQUE/FOREIGN KEY constraints at runtime
--    (except NOT NULL), but declaring RELY/NOT ENFORCED assists the Snowflake Cost-Based
--    Optimizer in join elimination.
-- =============================================================================

USE DATABASE PAYMENTPULSE_PROD;
USE SCHEMA GOLD;

-- Dimension: Date
CREATE OR REPLACE TABLE DIM_DATE (
    DATE_SK         INTEGER PRIMARY KEY,
    FULL_DATE       DATE NOT NULL,
    YEAR            INTEGER NOT NULL,
    QUARTER         INTEGER NOT NULL,
    MONTH           INTEGER NOT NULL,
    MONTH_NAME      VARCHAR(20) NOT NULL,
    WEEK_OF_YEAR    INTEGER NOT NULL,
    DAY_OF_MONTH    INTEGER NOT NULL,
    DAY_OF_WEEK     INTEGER NOT NULL,
    DAY_NAME        VARCHAR(20) NOT NULL,
    IS_WEEKEND      BOOLEAN NOT NULL
);

-- Dimension: Customer
CREATE OR REPLACE TABLE DIM_CUSTOMER (
    CUSTOMER_SK     INTEGER AUTOINCREMENT PRIMARY KEY,
    CUSTOMER_ID     VARCHAR(64) NOT NULL UNIQUE,
    NAME            VARCHAR(255),
    EMAIL           VARCHAR(255),
    SEGMENT         VARCHAR(50),
    COUNTRY         VARCHAR(2),
    CUSTOMER_SINCE  DATE
);

-- Dimension: Merchant
CREATE OR REPLACE TABLE DIM_MERCHANT (
    MERCHANT_SK     INTEGER AUTOINCREMENT PRIMARY KEY,
    MERCHANT_ID     VARCHAR(64) NOT NULL UNIQUE,
    NAME            VARCHAR(255),
    CATEGORY        VARCHAR(100),
    COUNTRY         VARCHAR(2),
    RISK_CATEGORY   VARCHAR(20)
);

-- Dimension: Payment Method
CREATE OR REPLACE TABLE DIM_PAYMENT_METHOD (
    PAYMENT_METHOD_SK   INTEGER AUTOINCREMENT PRIMARY KEY,
    PAYMENT_METHOD      VARCHAR(50) NOT NULL UNIQUE,
    METHOD_GROUP        VARCHAR(50)
);

-- Fact: Transactions (Clustered for high performance analytical scanning)
CREATE OR REPLACE TABLE FACT_TRANSACTIONS (
    TRANSACTION_ID      VARCHAR(64) PRIMARY KEY,
    CUSTOMER_SK         INTEGER NOT NULL REFERENCES DIM_CUSTOMER(CUSTOMER_SK),
    MERCHANT_SK         INTEGER NOT NULL REFERENCES DIM_MERCHANT(MERCHANT_SK),
    PAYMENT_METHOD_SK   INTEGER NOT NULL REFERENCES DIM_PAYMENT_METHOD(PAYMENT_METHOD_SK),
    DATE_SK             INTEGER NOT NULL REFERENCES DIM_DATE(DATE_SK),
    TS                  TIMESTAMP_NTZ NOT NULL,
    AMOUNT              NUMBER(18, 2) NOT NULL,
    CURRENCY            VARCHAR(3) NOT NULL,
    COUNTRY             VARCHAR(2),
    CHANNEL             VARCHAR(50),
    DEVICE_TYPE         VARCHAR(50),
    STATUS              VARCHAR(20) NOT NULL,
    IS_SUCCESS          BOOLEAN NOT NULL,
    IS_FAILED           BOOLEAN NOT NULL,
    IS_REVERSED         BOOLEAN NOT NULL,
    BATCH_ID            VARCHAR(64)
)
CLUSTER BY (TO_DATE(TS));

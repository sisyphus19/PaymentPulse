-- =============================================================================
-- PaymentPulse — Snowflake Target Architecture: Warehouse Setup
-- Execution Status: Target Architecture (Not executed locally)
--
-- Barclays Standard: Virtual Warehouses, Dedicated Functional Roles,
-- Resource Monitors, and Controlled Environments.
-- =============================================================================

-- 1. Create Functional Roles (Least Privilege principle)
CREATE ROLE IF NOT EXISTS PAYMENTS_ANALYST_ROLE;
CREATE ROLE IF NOT EXISTS PAYMENTS_ENGINEER_ROLE;

-- 2. Create Virtual Warehouses
-- In Snowflake, compute is decoupled from storage.
-- Small warehouse for daily reporting; auto-suspend prevents idle credit burn.
CREATE WAREHOUSE IF NOT EXISTS PAYMENTS_ANALYTICS_WH
    WITH WAREHOUSE_SIZE = 'X-SMALL'
    AUTO_SUSPEND = 120
    AUTO_RESUME = TRUE
    MIN_CLUSTER_COUNT = 1
    MAX_CLUSTER_COUNT = 3
    SCALING_POLICY = 'STANDARD'
    COMMENT = 'Warehouse for Barclays payments operations dashboards and ad-hoc SQL';

CREATE WAREHOUSE IF NOT EXISTS PAYMENTS_ETL_WH
    WITH WAREHOUSE_SIZE = 'MEDIUM'
    AUTO_SUSPEND = 60
    AUTO_RESUME = TRUE
    COMMENT = 'Dedicated compute for heavy batch ingestion and dbt daily transformations';

-- 3. Database & Schemas
CREATE DATABASE IF NOT EXISTS PAYMENTPULSE_PROD;

USE DATABASE PAYMENTPULSE_PROD;

CREATE SCHEMA IF NOT EXISTS BRONZE COMMENT = 'Raw landing tables directly from S3 Snowpipe';
CREATE SCHEMA IF NOT EXISTS SILVER COMMENT = 'Cleansed, deduplicated, and typed tables';
CREATE SCHEMA IF NOT EXISTS GOLD COMMENT = 'Conformed Dimensional Star Schema for Power BI & analytics';
CREATE SCHEMA IF NOT EXISTS GOVERNANCE COMMENT = 'Data Quality & Reconciliation audit logs';

-- 4. Grant Role Privileges
GRANT USAGE ON WAREHOUSE PAYMENTS_ANALYTICS_WH TO ROLE PAYMENTS_ANALYST_ROLE;
GRANT USAGE ON DATABASE PAYMENTPULSE_PROD TO ROLE PAYMENTS_ANALYST_ROLE;
GRANT USAGE ON SCHEMA PAYMENTPULSE_PROD.GOLD TO ROLE PAYMENTS_ANALYST_ROLE;
GRANT SELECT ON ALL TABLES IN SCHEMA PAYMENTPULSE_PROD.GOLD TO ROLE PAYMENTS_ANALYST_ROLE;
GRANT SELECT ON ALL VIEWS IN SCHEMA PAYMENTPULSE_PROD.GOLD TO ROLE PAYMENTS_ANALYST_ROLE;

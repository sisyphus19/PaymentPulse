# Changelog

All notable changes to the **PaymentPulse** project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2026-09-09

### Added
- **Tier 1 Core Pipeline Complete & Verified**
  - **Synthetic Data Generator (`generate.py`)**: Generates 75,000 transactions, 500 customers, and 100 merchants with realistic Gaussian amounts, merchant risk-weighting, and 10 configurable injected data quality problems.
  - **Ingestion Engine (`ingest.py`)**: Validates schema contracts, logs ingestion metadata to `bronze.ingestion_audit`, and enforces idempotency per `batch_id`.
  - **Warehouse Medallion Pipeline (`warehouse.py`)**:
    - Bronze: Raw unparsed strings with batch metadata.
    - Silver: Clean typed schema with deduplication and automated quarantine (`silver.quarantine`) preserving JSON raw rows and rejection causes.
    - Gold: Dimensional Star Schema featuring `fact_transactions`, `dim_customer`, `dim_merchant`, `dim_payment_method`, and `dim_date`.
  - **Data Quality Framework (`checks.py`)**: 14 automated DQ tests covering completeness, uniqueness, validity, referential integrity, freshness, and volume anomalies; computes an aggregate 0–100 quality score.
  - **Data Controls Governance Framework (`controls.py`)**: 7 financial-grade controls (CTL-01 through CTL-07) with automated verification and reconciliation balance checks.
  - **SQL Analytics Directory (`sql/analytics/analytics.sql`)**: 10 business-focused, Snowflake-compatible SQL queries with inline business question commentary.
  - **End-to-End Orchestrator (`run_pipeline.py`)**: Unified CLI running all 5 stages in sequence with UTC execution logging.
  - **Comprehensive Documentation**:
    - `docs/requirements.md`: Banking stakeholder requirements (FR-01 through FR-06).
    - `docs/domain_model.md`: ERD, payment state machine, and entity definitions.
    - `docs/data_dictionary.md`: Complete column definitions for all layers.
    - `docs/data_controls.md`: Control inventory and remediation runbooks.
    - `docs/architecture.md`: Local vs. production target architecture comparison.
    - `docs/interview_guide.md`: Interview defence and Q&A covering technical and functional decisions.
  - **Automated Test Suite**: Pytest unit tests for generator, ingestion, and DQ checks, plus full pipeline integration tests.

# Changelog

All notable changes to the **PaymentPulse** project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.1] - 2026-11-07

### Fixed
- `mlops/train.py --mlflow` crashed on MLflow >= 3.15 (skops rejected `sklearn.tree._tree.Tree` as an untrusted type); the model is now logged with `serialization_format="cloudpickle"`.
- README documentation index pointed to a non-existent `docs/design_decisions.md`.

### Added
- `tests/unit/test_mlops.py`: 13 tests for the PSI drift monitor (including an injected-drift case) and the model validation gate. Total tests: 65.
- CI now also runs the end-to-end pipeline, risk-model training, the validation gate, and the drift monitor.
- `.gitignore` entries for `mlruns/` and `mlflow.db`.

### Documentation
- README states that AWS (S3, SageMaker, Lambda, Step Functions, CloudWatch), Databricks, Snowflake and dbt are design or scaffolding only, that CI does not build the Docker image, and what the validation gate does and does not check.

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

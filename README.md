# PaymentPulse — End-to-End Payments Analytics, Data Quality & Controls Platform

> **Status:** Core local pipeline complete and tested (v1.0.0).
> **Executed locally** on Windows 11 (Python 3.13, DuckDB, pandas).
> **Cloud components** (AWS S3, Databricks, Snowflake, dbt) are documented as a target design and were not executed.

---

## 1. Problem & Business Objective

Modern payment institutions process tens of millions of financial transactions daily across diverse rails (card networks, Faster Payments, Bacs, digital wallets). Ensuring operational reliability requires answering three core questions continuously:

1. **Pipeline Integrity:** Are any transactions silently dropped or corrupted between ingestion and curation?
2. **Data Governance & Controls:** Do incoming records satisfy basic financial data standards (uniqueness, positive value bounds, referential integrity, freshness)?
3. **Payments Performance:** What are the success/failure distributions by payment rail, merchant risk tier, customer segment, and geography?

**PaymentPulse** is an end-to-end payments engineering and analytics platform. It ingests raw synthetic transaction feeds, applies schema validation, transforms data across a Medallion architecture (Bronze → Silver → Gold), runs financial data controls with automated reconciliation, and provides business analytics for payments operations.

---

## 2. Core Architecture (Local Execution vs. Target Production)

### Local Implementation (Executed & Tested)

```
            SYNTHETIC GENERATOR
           (Python / Faker / Seed)
                     │
                     ▼
            RAW CSV STAGING
    (Customers, Merchants, Transactions)
                     │
                     ▼
              INGESTION ENGINE
       (Schema validation & Audit log)
                     │
                     ▼
   ┌─────────────────────────────────────┐
   │     DUCKDB MEDALLION WAREHOUSE      │
   │                                     │
   │  [Bronze] Raw unparsed strings      │
   │     │                               │
   │     ▼                               │
   │  [Silver] Typed, Deduplicated       │
   │     │       └─► [Quarantine Table]  │
   │     ▼                               │
   │  [Gold]   Dimensional Star Schema   │
   │           (fact_transactions, dims) │
   └──────────────────┬──────────────────┘
                      │
      ┌───────────────┼───────────────┐
      ▼               ▼               ▼
DATA QUALITY    DATA CONTROLS   SQL ANALYTICS
(14 Checks)     (7 Controls)    (10 Queries)
```

### Target Production Architecture (Design Only)

```
AWS S3 (Raw Landing) ──► Databricks (PySpark Bronze/Silver) ──► Snowflake (Gold Star Schema via dbt) ──► Power BI
```

*Cloud infrastructure is documented as the target design and was not executed.*

---

## 3. Technology Stack & Design Decisions

| Technology        | Role                            | Rationale |
| ----------------- | ------------------------------- | --------- |
| **Python 3.13**   | Core language                   | Standard language for data engineering, with structured UTC logging. |
| **DuckDB**        | Local analytical warehouse      | In-process, column-oriented OLAP engine with full ANSI SQL, window functions, and Parquet/CSV scanning, with no server to configure. Queries are written in ANSI SQL and are largely portable to Snowflake. |
| **pandas**        | Ingestion & transformation      | Vectorized batch transformations and schema conformance. PySpark is part of the target cloud design and is deferred locally to avoid JVM overhead. |
| **Faker**         | Data generation                 | Deterministic, seed-controlled generation of realistic financial entities across geographies. |
| **pytest & ruff** | Testing & linting               | Fast, reproducible test and lint tooling, run automatically in CI. |

---

## 4. Medallion Warehouse Model

### Bronze Layer (`bronze`)

- **`raw_transactions`**, **`raw_customers`**, **`raw_merchants`**: Untransformed data stored as raw strings, preserving the source payloads verbatim.
- **`ingestion_audit`**: Audit table logging batch UUIDs, file origins, row counts, and schema conformance statuses.

### Silver Layer (`silver`)

- **`transactions`**: Validated, typed, and deduplicated records.
- **`customers`** & **`merchants`**: Deduplicated dimension sources.
- **`quarantine`**: Rejected records stored with the full JSON payload and an explicit rejection reason (e.g. `null customer_id`, `unparseable amount`).

### Gold Layer (`gold` Star Schema)

- **`fact_transactions`**: Fact table keyed on surrogate dimension keys (`customer_sk`, `merchant_sk`, `payment_method_sk`, `date_sk`) with status flags (`is_success`, `is_failed`, `is_reversed`).
- **`dim_customer`**, **`dim_merchant`**, **`dim_payment_method`**, **`dim_date`**: Conformed dimension tables.

---

## 5. Financial Data Controls & Governance

PaymentPulse implements seven binary data controls (CTL-01 through CTL-07):

| Control ID | Control Name           | Rule & Validation Scope                                            | Status                      |
| ---------- | ---------------------- | ------------------------------------------------------------------ | --------------------------- |
| **CTL-01** | Transaction Uniqueness | Zero duplicate transaction IDs in Gold                             | **PASS** (0 duplicates)     |
| **CTL-02** | Referential Integrity  | Zero orphan facts; all foreign keys resolve to valid dimensions    | **PASS** (0 orphan facts)   |
| **CTL-03** | Amount Validation      | Amounts must be positive and within bounds: 0 < amount ≤ 1,000,000 | **PASS** (0 violations)     |
| **CTL-04** | Status Validity        | Only valid payment lifecycle statuses are allowed                  | **PASS** (0 invalid states) |
| **CTL-05** | Pipeline Freshness     | Data arrives within the 24h operational SLA                        | **PASS** (within SLA)       |
| **CTL-06** | Schema Validation      | All expected columns are present in Gold                           | **PASS** (no drift)         |
| **CTL-07** | Reconciliation         | Raw count = Silver count + Quarantine count                        | **PASS** (delta = 0)        |

**Reconciliation proof (CTL-07):** every ingested record is accounted for in either Silver or the quarantine table, so no record is silently dropped.

```
Raw Ingested   = 75,000
Silver Clean   = 72,053
Quarantine     =  2,947
Unaccounted    = 75,000 - (72,053 + 2,947) = 0
```

---

## 6. Execution Results (Measured Locally)

All figures below come from a successful local pipeline run.

- **Total ingested:** 75,000 transactions
- **Silver promotion rate:** 96.07% (72,053 records)
- **Quarantine rate:** 3.93% (2,947 records)
- **Data quality score:** 100.0 / 100.0 (14/14 checks passed)
- **Data controls:** 7/7 passed
- **Gold fact rows:** 72,053
- **Pipeline execution time:** 7.61 seconds

> **Note on interpreting these results:** the data is synthetic, and the generator deliberately injects 10 configurable data quality problems. The 3.93% quarantine rate and the passing checks show that the pipeline catches and isolates those defects as designed. They are not a claim about real-world data quality.

### Automated Testing

The project includes **52 pytest tests** covering data generation, ingestion, data quality, controls, warehouse processing, and risk scoring. Linting is enforced with ruff, and both run in CI on every push.

---

## 7. SQL Analytics Suite

Located in `sql/analytics/analytics.sql`, the 10 queries answer concrete operational questions against the Gold dimensional model:

1. **Daily Volume & Value:** daily GBP payment totals and transaction velocity.
2. **Success & Failure Rates:** terminal lifecycle distribution across all transactions.
3. **Failure Rate by Payment Method:** failure patterns across card rails, Faster Payments, and wallets.
4. **Top 10 Merchants by Value:** concentration risk and high-value merchant accounts.
5. **Top 10 Merchants by Failure Rate:** merchants with abnormal technical declines.
6. **Country Volume & Exposure:** geographic breakdown of payment flows.
7. **Country Failure Rates:** network or regulatory bottlenecks by region.
8. **Payment Method Preference by Geography:** cross-border rail adoption.
9. **Customer Segment Spend Analysis:** spend depth across retail, business, premium, and student cohorts.
10. **Hourly Peak Distribution:** intraday volume for capacity planning and batch window scheduling.

---

## 8. Risk & Anomaly Analytics

PaymentPulse includes a transaction-level anomaly risk layer built on the curated Silver dataset.

- Engineers behavioral features such as transaction amount, customer-level amount baseline, transaction frequency, merchant failure rate, time of day, weekend activity, and country mismatch.
- Uses an **Isolation Forest** model to flag unusual transaction behavior.
- Calibrates anomaly scores to a **0–100 risk score** with configurable Low / Medium / High policy tiers.
- Generates human-readable risk explanations based on the characteristics driving each score.
- Persists risk outputs for downstream analysis.

The model is unsupervised and the data is synthetic, so the scores illustrate the approach rather than measure real fraud-detection performance.

---

## 9. Local Setup & Reproduction

### Prerequisites

- Python 3.11+ (tested on Python 3.13)
- Git

### Installation & Execution

```bash
# 1. Clone the repository and move into it
git clone https://github.com/sisyphus19/PaymentPulse.git
cd PaymentPulse

# 2. Install the package with development tools (pytest, ruff)
pip install -e ".[dev]"

# 3. Run the complete pipeline (Generate -> Ingest -> Warehouse -> DQ -> Controls -> Risk)
python pipelines/run_pipeline.py

# 4. Run the automated test suite
python -m pytest tests/ -v

# 5. Run the linter (same command as CI)
python -m ruff check .
```

The curated warehouse is written to `data/paymentpulse.duckdb` and can be queried with any DuckDB client or a Python script.

### Optional extras

The core pipeline needs only the default install plus `[dev]`. Optional dependency groups are available for the MLOps and AWS scaffolding in `mlops/` and `aws/`:

```bash
pip install -e ".[mlops]"   # MLflow
pip install -e ".[aws]"     # boto3, SageMaker
```

---

## 10. Skills Demonstrated

| Area                             | Evidence in PaymentPulse                                                                                                              |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| **Data Integration & Pipelines** | Automated end-to-end Python pipeline from raw landing to the Medallion warehouse, with schema validation and an ingestion audit log.  |
| **SQL & Dimensional Modeling**   | ANSI SQL star schema (`fact_transactions`, `dim_customer`, `dim_merchant`, etc.) with 10 business analytics queries.                  |
| **Payments Domain Knowledge**    | Payment lifecycle modeling (INITIATED, SUCCESS, FAILED, PENDING, REVERSED), rail segmentation, and risk metrics.                      |
| **Data Quality & Governance**    | 14-point DQ framework with PASS/WARN/FAIL scoring, and 7 financial data controls including zero-delta reconciliation.                |
| **Testing & SDLC**               | 52 pytest tests, ruff linting, CI on every push, structured UTC logging, and documentation in `docs/`.                                |
| **Cloud / Target Architecture**  | Documented Snowflake/Databricks/dbt target design, with a clear separation between what runs locally and what is design-only.         |

---

## 11. Repository Documentation Index

- `docs/requirements.md`: Stakeholder requirements (FR-01 through FR-06).
- `docs/domain_model.md`: Entity relationship diagram and payment state lifecycle.
- `docs/data_dictionary.md`: Schema dictionary across Bronze, Silver, and Gold.
- `docs/data_controls.md`: Governance controls inventory and reconciliation runbook.
- `docs/architecture.md`: Technical architecture and scalability analysis.
- `docs/design_decisions.md`: Q&A on the main architectural and payments-domain decisions.

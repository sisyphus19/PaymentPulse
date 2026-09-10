# PaymentPulse — End-to-End Payments Analytics, Data Quality & Controls Platform


## 1. Problem & Business Objective

Modern payment institutions process tens of millions of financial transactions daily across diverse rails (card networks, Faster Payments, Bacs, digital wallets). Ensuring operational reliability requires answering three core questions continuously:

1. **Pipeline Integrity:** Are any transactions silently dropped or corrupted between ingestion and curation?
2. **Data Governance & Controls:** Do incoming records strictly satisfy banking regulatory standards (uniqueness, positive value bounds, referential integrity, freshness)?
3. **Payments Performance:** What are our success/failure distributions by payment rail, merchant risk tier, customer segment, and geography?

**PaymentPulse** provides an end-to-end payments engineering and analytics platform that ingests raw synthetic transaction feeds, applies rigorous schema validation, transforms data across a Medallion architecture (Bronze → Silver → Gold), executes financial data controls with automated reconciliation, and provides business analytics for payments operations.

---

## 2. Core Architecture (Local Execution vs. Target Production)

### Local Implementation (Fully Executed & Tested)

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
          ┌──────────────────────┼──────────────────────┐
          ▼                      ▼                      ▼
    DATA QUALITY           DATA CONTROLS         SQL ANALYTICS
    (14 Checks)            (7 Controls)          (10 Queries)
                                 │
                                 ▼
                       RISK / MLOPS LAYER
                  Isolation Forest + Monitoring
```

### Target Production Architecture (Design Specification)

```
AWS S3 ──► Step Functions / Lambda validation ──► SageMaker Processing / Training
                                      │
                                      ├──► MLflow model lineage / registry
                                      ├──► SageMaker Model / Endpoint
                                      └──► CloudWatch monitoring / alarms

Analytics target: curated outputs can feed Snowflake/dbt or other enterprise analytical stores.
```
*Note: AWS resources are documented as a production target design; they were not deployed for this portfolio project.*

---

## 3. Technology Stack & Design Decisions

| Technology | Role | Design Decision & Interview Defence |
|---|---|---|
| **Python 3.13** | Core language | Standard corporate data engineering language with strict typing and modern logging. |
| **DuckDB** | Local Analytical Warehouse | Chosen over Postgres/SQLite because it is an in-process, column-oriented OLAP engine supporting full ANSI SQL, window functions, and Parquet/CSV scanning with zero daemon configuration. Porting to Snowflake requires no query rewrites. |
| **pandas** | Data Ingestion & Transformation | Vectorized batch transformations and schema conformance. (PySpark deferred to Tier 2 to eliminate JVM overhead on local environments). |
| **Faker** | Data Generation | Deterministic, seed-controlled generation of realistic financial entities across global geographies. |
| **pytest & ruff** | Quality & Linting | Automated tests and linting used in local development and CI. |
| **scikit-learn** | Risk model | Isolation Forest anomaly detection with calibrated transaction risk scores. |
| **MLflow** | MLOps | Optional experiment tracking and model artifact logging; enabled with the `mlops` extra. |
| **Docker** | Packaging | Reproducible container image for pipeline execution. |
| **GitHub Actions** | CI/CD | Automated lint + test workflow on pushes and pull requests. |
| **AWS SageMaker / Step Functions / Lambda / CloudWatch** | Production target | Reference implementation and architecture; not deployed in the portfolio environment. |

---

## 4. Medallion Warehouse Model

### Bronze Layer (`bronze`)
- **`raw_transactions`**, **`raw_customers`**, **`raw_merchants`**: Untransformed data stored as raw strings preserving verbatim source payloads.
- **`ingestion_audit`**: Audit table logging batch UUIDs, file origins, row counts, and schema conformance statuses.

### Silver Layer (`silver`)
- **`transactions`**: Validated, typed, and deduplicated records.
- **`customers`** & **`merchants`**: Deduplicated dimension sources.
- **`quarantine`**: Preserves rejected records alongside the full JSON payload and explicit rejection reasons (e.g. `null customer_id`, `unparseable amount`).

### Gold Layer (`gold` Star Schema)
- **`fact_transactions`**: Fact table keyed on surrogate dimension keys (`customer_sk`, `merchant_sk`, `payment_method_sk`, `date_sk`) with terminal boolean flags (`is_success`, `is_failed`, `is_reversed`).
- **`dim_customer`**, **`dim_merchant`**, **`dim_payment_method`**, **`dim_date`**: Conformed dimension tables.

---

## 5. Financial Data Controls & Governance

PaymentPulse implements seven binary financial data controls (CTL-01 through CTL-07):

| Control ID | Control Name | Rule & Validation Scope | Status |
|---|---|---|---|
| **CTL-01** | Transaction Uniqueness | Verifies zero duplicate transaction IDs in Gold | **PASS** (0 duplicates) |
| **CTL-02** | Referential Integrity | Zero orphan facts; all foreign keys resolve to valid dimensions | **PASS** (0 orphan facts) |
| **CTL-03** | Amount Validation | Amounts must be positive and within business bounds ($0 < x \le \$1,000,000$) | **PASS** (0 violations) |
| **CTL-04** | Status Validity | Enforces valid payment lifecycle statuses | **PASS** (0 invalid states) |
| **CTL-05** | Pipeline Freshness | Validates arrival within 24h operational SLA | **PASS** (within SLA) |
| **CTL-06** | Schema Validation | Asserts presence of all expected columns in Gold | **PASS** (no drift) |
| **CTL-07** | **Reconciliation** | **$\text{Raw Count} = \text{Silver Count} + \text{Quarantine Count}$** | **PASS** (Delta = 0) |

> **Audit Proof (CTL-07 Reconciliation):**  
> $\text{Raw Ingested} = 75,000$  
> $\text{Silver Clean} = 72,053$  
> $\text{Quarantine} = 2,947$  
> $\mathbf{\text{Unaccounted Delta}} = 75,000 - (72,053 + 2,947) = \mathbf{0}$. No records are silently dropped.

---

## 6. Real Execution Results (Measured Locally)

*Core figures below reflect an actual successful local pipeline execution on 2026-09-10.*

- **Total Ingested:** 75,000 transactions
- **Silver Promotion Rate:** 96.07% (72,053 records)
- **Quarantine Rate:** 3.93% (2,947 records quarantined due to injected defects)
- **Data Quality Score:** **100.0 / 100.0** (all 14 validation checks passed on curated Silver layer)
- **Data Controls Passed:** 7 of 7 controls passed (100% compliance)
- **Core pipeline execution time:** 7.61 seconds

---

## 7. SQL Analytics Suite

Located in [`sql/analytics/analytics.sql`](sql/analytics/analytics.sql), all 10 queries answer concrete operational questions against the Gold dimensional model:

1. **Daily Volume & Value**: Tracks daily GBP payment totals and transaction velocity.
2. **Success & Failure Rates**: Calculates terminal lifecycle distribution across the enterprise.
3. **Failure Rate by Payment Method**: Isolates failure patterns across card rails, Faster Payments, and wallets.
4. **Top 10 Merchants by Value**: Concentration risk and high-value acquiring accounts.
5. **Top 10 Merchants by Failure Rate**: Identifies problematic or high-risk merchants experiencing abnormal technical declines.
6. **Country Volume & Exposure**: Geographic breakdown of payment flows.
7. **Country Failure Rates**: Isolates network or regulatory bottlenecks by region.
8. **Payment Method Preference by Geography**: Cross-border rail adoption.
9. **Customer Segment Spend Analysis**: Spend depth across retail, business, premium, and student cohorts.
10. **Hourly Peak Distribution**: Analyzes intraday processing volume for capacity planning and batch window scheduling.

---

## 8. MLOps & AWS Production Design

PaymentPulse now includes an operational ML lifecycle around the transaction-risk model:

- **Training:** `mlops/train.py` reuses the production feature engineering and Isolation Forest implementation.
- **Experiment tracking:** optional MLflow logging of parameters, operational metrics, metadata, and model artifacts.
- **Deployment gate:** `mlops/validate.py` checks model metadata, feature schema, training volume, and risk-distribution guardrails.
- **Monitoring:** `mlops/monitor.py` calculates PSI-based feature drift signals.
- **Packaging:** Docker image for reproducible execution.
- **CI/CD:** GitHub Actions runs linting and the automated test suite.
- **AWS target:** SageMaker Pipelines, S3, Lambda, Step Functions and CloudWatch are represented in `aws/` and `docs/mlops_aws_architecture.md`.

The AWS components are **reference architecture/code, not deployed infrastructure**. This distinction is intentional so the project demonstrates MLOps design without overstating cloud experience.

See [`mlops/README.md`](mlops/README.md) and [`docs/mlops_aws_architecture.md`](docs/mlops_aws_architecture.md) for the lifecycle and deployment design.

## 9. Local Setup & Reproduction

### Prerequisites
- Python 3.11+ (Tested on Python 3.13)
- Git

### Installation & Execution

```bash
# 1. Navigate to project root
cd paymentpulse

# 2. Install dependencies (editable mode)
pip install -e .

# 3. Run the complete pipeline (Generate -> Ingest -> Warehouse -> DQ -> Controls -> Risk scoring)
python pipelines/run_pipeline.py

# 4. Run the automated test suite
python -m pytest tests/ -v

# 5. Run the linter
python -m ruff check src/ tests/
```

The curated warehouse database will be available at `data/paymentpulse.duckdb`. The pipeline also writes transaction risk results to `gold.fact_transactions_risk`.

For MLOps training/validation, see `mlops/README.md`.

---

## 10. Alignment with Barclays / MLOps & Data Quality Roles

| Barclays JD Requirement | Evidence in PaymentPulse (Tier 1) |
|---|---|
| **Data Integration & Pipelines** | Automated end-to-end Python pipeline from raw landing to Medallion warehouse with schema validation. |
| **SQL & Dimensional Modeling** | ANSI-standard Star Schema (`fact_transactions`, `dim_customer`, `dim_merchant`, etc.) with 10 business analytics queries. |
| **Payments Domain Expertise** | Complete payment lifecycle modeling (INITIATED, SUCCESS, FAILED, PENDING, REVERSED), payment rail segmentation, and risk metrics. |
| **Data Quality & Governance** | 14-point DQ framework with PASS/WARN/FAIL scoring and 7 financial-grade data controls with zero-delta reconciliation. |
| **Testing & SDLC** | 52 passing pytest tests, clean ruff linting, structured UTC logging, and comprehensive documentation (`docs/`). |
| **Cloud / MLOps Target Architecture** | AWS S3, SageMaker Pipelines/Training, Step Functions, Lambda and CloudWatch design artifacts; local execution remains cloud-independent. |
| **ML Lifecycle** | Isolation Forest risk model, MLflow tracking, deployment validation gate, Docker packaging, CI workflow, and PSI-based drift monitoring. |

---

## 11. Repository Documentation Index

- [`docs/requirements.md`](docs/requirements.md): Stakeholder specifications (FR-01 through FR-06).
- [`docs/domain_model.md`](docs/domain_model.md): Entity relationship diagram and payment state lifecycle.
- [`docs/data_dictionary.md`](docs/data_dictionary.md): Comprehensive schema dictionary across Bronze, Silver, and Gold.
- [`docs/data_controls.md`](docs/data_controls.md): Detailed governance controls inventory and reconciliation runbook.
- [`docs/architecture.md`](docs/architecture.md): Technical architectural specification and scalability analysis.
- [`docs/interview_guide.md`](docs/interview_guide.md): Technical Q&A defending every architectural and payments domain decision.

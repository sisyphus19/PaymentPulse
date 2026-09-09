# PaymentPulse — Architecture Document

**Execution environment:** Local — Python 3.13, DuckDB, pandas  
**Version:** 1.0 (Tier 1)

---

## Tier 1 Architecture (What Is Actually Built and Executed)

```
┌─────────────────────────────────────────────────────────────────┐
│                    LOCAL EXECUTION (Tier 1)                     │
│                                                                 │
│  config/config.yaml                                             │
│         │                                                       │
│         ▼                                                       │
│  [1] DATA GENERATOR (Faker / Python)                            │
│      generate.py → customers.csv, merchants.csv, txns.csv       │
│         │                                                       │
│         ▼                                                       │
│  [2] INGESTION LAYER (pandas / Python)                          │
│      ingest.py → schema validation → bronze.raw_transactions    │
│                             └──────→ bronze.ingestion_audit     │
│         │                                                       │
│         ▼                                                       │
│  [3] WAREHOUSE — DuckDB (data/paymentpulse.duckdb)              │
│      ┌──────────────────────────────────────────────────────┐   │
│      │  BRONZE (raw strings, audit)                         │   │
│      │    bronze.raw_transactions                           │   │
│      │    bronze.ingestion_audit                            │   │
│      │              │                                       │   │
│      │              ▼                                       │   │
│      │  SILVER (typed, deduplicated, validated)             │   │
│      │    silver.transactions ◄── valid records             │   │
│      │    silver.quarantine   ◄── invalid records           │   │
│      │    silver.customers                                  │   │
│      │    silver.merchants                                  │   │
│      │              │                                       │   │
│      │              ▼                                       │   │
│      │  GOLD (dimensional model)                            │   │
│      │    gold.fact_transactions                            │   │
│      │    gold.dim_customer                                 │   │
│      │    gold.dim_merchant                                 │   │
│      │    gold.dim_payment_method                           │   │
│      │    gold.dim_date                                     │   │
│      └──────────────────────────────────────────────────────┘   │
│         │                         │                             │
│         ▼                         ▼                             │
│  [4] DATA QUALITY           [5] DATA CONTROLS                   │
│      checks.py                controls.py                       │
│      14 checks                 7 controls (CTL-01..CTL-07)      │
│      PASS/WARN/FAIL            PASS/FAIL + remediation          │
│      Quality Score 0-100       Reconciliation (CTL-07)          │
│         │                                                       │
│         ▼                                                       │
│  [6] SQL ANALYTICS (sql/analytics/analytics.sql)                │
│      10 queries against Gold dimensional model                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Target Production Architecture (Documented — Not Executed)

The following is the production architecture this project would use in a real
banking environment. SQL and configuration templates exist in the repository
but are clearly labeled as **not executed**.

```
┌─────────────────────────────────────────────────────────────────┐
│                    TARGET PRODUCTION                             │
│                                                                 │
│  Source Systems (banking APIs / file feeds)                     │
│         │                                                       │
│         ▼                                                       │
│  AWS S3 (landing zone / raw data lake)                          │
│         │                                                       │
│         ▼                                                       │
│  Databricks (PySpark)                                           │
│    Bronze → Silver → Gold (Delta tables)                        │
│         │                                                       │
│         ▼                                                       │
│  dbt (analytics transformation layer)                           │
│    staging → intermediate → marts                               │
│         │                                                       │
│         ▼                                                       │
│  Snowflake (cloud warehouse)                                    │
│    FACT_TRANSACTIONS, DIM_* tables                              │
│    Snowflake-compatible SQL provided in sql/warehouse/          │
│         │                                                       │
│    ┌────┴────────────────┐                                      │
│    ▼                     ▼                                      │
│  SQL Analytics        Power BI Dashboard                        │
│  (Snowflake views)    (3 pages: Overview / Merchants / Risk)    │
│                                                                 │
│  CI/CD: GitLab CI pipeline (lint → test → dbt-test → deploy)   │
│  Infrastructure: Docker containers, GitLab Runner               │
└─────────────────────────────────────────────────────────────────┘
```

---

## Technology Choices & Rationale

### DuckDB (local warehouse)

DuckDB was chosen over PostgreSQL for the local warehouse because:
- **Zero server configuration**: file-based, no daemon required
- **Column-oriented storage**: fast aggregations over large fact tables
- **ANSI SQL compatible**: queries written here run on Snowflake with minimal changes
- **Native Parquet/CSV support**: reads files without an ETL step
- **Python integration**: registers pandas DataFrames as virtual tables natively

Interview defence: "DuckDB lets me demonstrate the Bronze/Silver/Gold medallion
architecture with real SQL and real data, locally, without spinning up a database
server. The SQL I've written is Snowflake-compatible — the column names, data types,
and query patterns all translate directly."

### pandas (transformation in Tier 1)

pandas is used for the Silver transformation (row-level validation and quarantine)
because:
- It is more reliable than PySpark on Windows without a JVM configured
- The brief explicitly defers PySpark to Tier 2
- At 75,000 rows, pandas is performant (< 30 seconds)
- The same logic can be ported to PySpark DataFrames with minimal changes
  (same `.filter()`, `.withColumn()`, `.dropDuplicates()` patterns)

### Faker (synthetic data)

Faker provides locale-aware synthetic PII (GB and US locales). All data is
demonstrably synthetic. No real customer or financial data is used or implied.

### pytest + ruff

Industry-standard Python testing and linting toolchain. ruff replaces
flake8 + black + isort with a single, faster tool. pytest provides clear,
readable test output.

---

## Data Flow Detail

### Bronze Layer

Raw CSV records written as-is (all fields as strings). Nothing is transformed
or deleted. Bronze is append-only per batch. Re-running with the same batch_id
deletes and replaces that batch's records (idempotency).

**Tables:** `bronze.raw_transactions`, `bronze.raw_customers`,
`bronze.raw_merchants`, `bronze.ingestion_audit`

### Silver Layer

Field-level validation and type conversion. Records failing any check are
moved to `silver.quarantine` with a documented rejection reason. Valid records
are written to `silver.transactions`.

**Quarantine reasons (examples):**
- `null/empty transaction_id`
- `duplicate transaction_id: <id>`
- `non-positive amount: -50.0`
- `invalid currency: 'ZZZZ'`
- `orphan customer_id: ORPHAN_abc12345`
- `unparseable timestamp: 'garbage'`

### Gold Layer

Star schema built from Silver. Surrogate keys assigned via `ROW_NUMBER()`.
Derived boolean columns (`is_success`, `is_failed`, `is_reversed`) simplify
common analytical query patterns.

---

## Medallion Architecture — Interview Defence

> Why Bronze/Silver/Gold?

The medallion architecture solves the fundamental problem of raw-data preservation
vs analytical usability. Bronze preserves the exact record that arrived from the
source — critical for regulatory audit and incident investigation. Silver applies
business rules consistently (one place to change a validation rule). Gold exposes
a clean, denormalised surface for analysts who should not need to understand
pipeline internals.

In a real bank, the alternative — applying transformations directly on raw data —
creates irreversible data loss and makes it impossible to reprocess a batch with
updated rules when a business definition changes.

---

## Scalability Considerations (Documented)

At scale (millions of transactions), the following changes would apply:

| Concern | Local (Tier 1) | Production |
|---|---|---|
| Storage | DuckDB file | AWS S3 + Delta Lake |
| Compute | pandas | Databricks PySpark |
| Partitioning | None (75K rows) | By date (YYYY/MM/DD) in S3 |
| Incremental processing | batch_id isolation | Merge/UPSERT on transaction_id |
| Query engine | DuckDB | Snowflake |
| Orchestration | manual `run_pipeline.py` | Airflow / Databricks Workflows |
| Monitoring | log output | Datadog / CloudWatch |

---

## Local Setup (Executed Locally)

```bash
# 1. Clone / navigate to project
cd paymentpulse

# 2. Install dependencies
pip install -e .

# 3. Run the full pipeline
python pipelines/run_pipeline.py

# 4. Run tests
pytest tests/ -v

# 5. Run linter
ruff check src/ tests/
```

Output: `data/paymentpulse.duckdb` — open with any DuckDB client.

---

## What Is NOT Executed (Target Architecture Only)

| Component | Status | Location |
|---|---|---|
| AWS S3 | Not executed — no credentials | `docs/architecture.md` (this doc) |
| Databricks / PySpark | Not executed — no cluster | Tier 2 scope |
| dbt | Not executed — not installed | Tier 2 scope |
| Snowflake | Not executed — no credentials | `sql/warehouse/` (syntax-compatible SQL) |
| Power BI dashboard | Not executed — no Power BI | Tier 2 scope |
| GitLab CI/CD | Not executed | `.gitlab-ci.yml` Tier 2 scope |
| Docker | Not executed (installed but not used in T1) | Tier 2 scope |

# PaymentPulse — Requirements Document

**Document type:** Business & Technical Requirements  
**Version:** 1.0  
**Status:** Final (Tier 1)  
**Execution environment:** Local — Python 3.13, DuckDB, pandas  
**Author:** PaymentPulse Portfolio Project  

---

## Business Objective

Design and build an end-to-end payments analytics and data quality platform
that ingests synthetic transaction data, validates it against data-quality
and control rules, transforms it into a clean dimensional model, and exposes
analytical insights through SQL queries.

The platform is intended to simulate the data engineering and analytics
capabilities required by a banking payments team, and to demonstrate these
capabilities in a portfolio context.

---

## Stakeholders

| Role | Interest |
|---|---|
| Payments Operations Team | Daily transaction volume, success/failure rates, operational KPIs |
| Risk & Compliance | Data controls, referential integrity, anomaly patterns |
| Data Engineering | Pipeline reliability, data quality, reconciliation |
| Business Analytics | Merchant performance, customer segments, geographic analysis |
| Audit / Governance | Data lineage, control evidence, quarantine records |

---

## Functional Requirements

### FR-01 — Data Generation

> The system shall generate a configurable synthetic payments dataset
> comprising transactions, customers, and merchants with realistic
> distributions of amounts, statuses, currencies, and payment methods.

**Acceptance criteria:**
- Dataset contains 50,000–100,000 transactions (default: 75,000)
- Multiple customers (default: 500), merchants (default: 100)
- All payment methods represented: credit card, debit card, bank transfer,
  digital wallet, buy now pay later, direct debit, standing order, faster payments
- Injected data-quality problems configurable by type and percentage
- Output in CSV format; reproducible with fixed random seed

---

### FR-02 — Data Ingestion

> The system shall ingest raw CSV files, validate schema,
> record batch metadata, and write records to the Bronze layer.

**Acceptance criteria:**
- Schema validation detects missing columns and records SCHEMA_ERROR status
- Batch ID, source file, record counts, and ingestion timestamp are recorded
  in `bronze.ingestion_audit`
- Re-running ingestion with the same batch ID does not duplicate records
  (idempotent)
- Ingestion supports customers, merchants, and transactions tables

---

### FR-03 — Data Transformation (Bronze → Silver → Gold)

> The system shall transform raw Bronze records into typed, deduplicated
> Silver records, quarantining invalid records with documented rejection
> reasons. Silver records shall be promoted to a Gold dimensional model.

**Acceptance criteria (Silver):**
- Timestamps parsed to `TIMESTAMP` type; unparseable timestamps → quarantine
- Amounts parsed to `DOUBLE`; non-positive amounts → quarantine
- Duplicate `transaction_id` values deduplicated; second occurrence → quarantine
- Records with orphan `customer_id` or `merchant_id` → quarantine
- Records with invalid `currency`, `status`, or `payment_method` → quarantine
- `silver.quarantine` table records rejection reason for every quarantined row

**Acceptance criteria (Gold):**
- `gold.fact_transactions` contains one row per Silver transaction
- `gold.dim_customer`, `gold.dim_merchant`, `gold.dim_payment_method`, `gold.dim_date` populated
- Surrogate keys resolve correctly in fact table JOINs

---

### FR-04 — Data Quality Framework

> The system shall run structured data-quality checks against the Silver layer
> and produce PASS / WARN / FAIL results per check and an aggregate quality score.

**Acceptance criteria:**
- Minimum 12 checks covering: completeness, uniqueness, validity,
  referential integrity, freshness, volume
- Each check records: dataset, check name, type, records checked,
  records failed, failure rate, status, timestamp
- Thresholds (WARN/FAIL boundaries) are configurable from `config.yaml`
- Aggregate quality score in range 0–100 is computed and logged

---

### FR-05 — Data Controls

> The system shall run seven named data controls and produce a structured
> control report with PASS / FAIL status and remediation guidance.

**Acceptance criteria:**
- CTL-01 Transaction Uniqueness: zero duplicate `transaction_id` in Gold
- CTL-02 Referential Integrity: zero Gold fact rows with NULL dimension keys
- CTL-03 Amount Validation: all amounts positive and within configurable ceiling
- CTL-04 Status Validity: only approved status values in Gold
- CTL-05 Pipeline Freshness: latest record within SLA (default: 24 hours)
- CTL-06 Schema Validation: all expected Gold columns present
- CTL-07 Reconciliation: `raw count == silver count + quarantine count`

---

### FR-06 — SQL Analytics

> The system shall provide at least ten analytical SQL queries answering
> defined business questions against the Gold dimensional model.

**Acceptance criteria:**
- Queries cover: daily volume/value, success/failure rates, failure by payment method,
  top merchants by value and failure rate, geographic breakdown, customer segment analysis,
  hourly peak analysis
- Each query includes a comment stating the business question it answers
- All queries are Snowflake-compatible (no DuckDB-specific syntax)
- Queries return non-empty results on the generated dataset

---

## Non-Functional Requirements

### NFR-01 — Reproducibility
All pipeline runs with the same random seed must produce identical datasets.

### NFR-02 — Execution time
Full pipeline (generate → ingest → transform → DQ → controls) must complete
in under 5 minutes on a standard laptop with 75,000 transactions.

### NFR-03 — Idempotency
Re-running any pipeline stage with the same batch ID must not corrupt or
duplicate existing data.

### NFR-04 — No cloud dependency
The entire Tier 1 pipeline must run locally without any cloud credentials,
paid services, or internet access (after dependencies are installed).

### NFR-05 — No fabricated metrics
All numbers reported in logs, documentation, and results must reflect actual
pipeline execution. No benchmark numbers are claimed unless actually measured.

### NFR-06 — Security
No credentials, API keys, or real personal data may be committed to the
repository. The `.env.example` template must clearly label which variables
are required for cloud execution (target architecture only).

---

## Data Requirements

| Dataset | Minimum Rows | Format | Source |
|---|---|---|---|
| Transactions | 75,000 | CSV | Generated (Faker) |
| Customers | 500 | CSV | Generated (Faker) |
| Merchants | 100 | CSV | Generated (Faker) |

### Injected Data Quality Problems (configurable)

| Problem Type | Default Rate |
|---|---|
| Null `customer_id` | 0.5% |
| Null `amount` | 0.3% |
| Duplicate `transaction_id` | 0.8% |
| Invalid currency code | 0.4% |
| Invalid status value | 0.3% |
| Orphan `customer_id` | 0.5% |
| Orphan `merchant_id` | 0.4% |
| Malformed timestamp | 0.3% |
| Future timestamp | 0.2% |
| Negative amount | 0.3% |

---

## Data Quality Requirements

| Check | Type | WARN threshold | FAIL threshold |
|---|---|---|---|
| Required field not null | Completeness | > 1% | > 5% |
| Transaction ID unique | Uniqueness | > 0% | > 0% |
| Amount > 0 | Validity | > 1% | > 5% |
| Valid currency | Validity | > 1% | > 5% |
| Valid status | Validity | > 1% | > 5% |
| Valid payment method | Validity | > 1% | > 5% |
| RI: customer exists | Referential Integrity | > 1% | > 5% |
| RI: merchant exists | Referential Integrity | > 1% | > 5% |
| Latest record < 24h | Freshness | N/A | Older than SLA |
| Volume within ±30% | Volume | N/A | Outside range |

---

## Reporting Requirements

The following analytical outputs must be produced:

1. DQ report (PASS/WARN/FAIL per check + score)
2. Control report (PASS/FAIL per control + remediation)
3. Reconciliation report (raw vs silver vs quarantine counts)
4. 10 analytical SQL queries with business question commentary
5. Run summary log (batch ID, record counts, DQ score, control status, timing)

---

## Risk / Control Requirements

| Control | Rationale |
|---|---|
| CTL-01 Transaction Uniqueness | Duplicate transactions lead to double-counting of revenue and payment exposure |
| CTL-02 Referential Integrity | Orphan records produce misleading analytics (merchant/customer can't be attributed) |
| CTL-03 Amount Validation | Negative or zero amounts indicate upstream system errors or potential manipulation |
| CTL-04 Status Validity | Unexpected status values indicate schema drift or upstream processing errors |
| CTL-05 Pipeline Freshness | Stale data leads to operational decisions based on outdated information |
| CTL-06 Schema Validation | Schema drift (added/removed columns) must be detected before it corrupts downstream models |
| CTL-07 Reconciliation | Financial regulators require that every input record is accounted for — either processed or explicitly rejected |

---

## Acceptance Criteria (End-to-End)

| Criterion | Verification |
|---|---|
| Pipeline runs end-to-end | `python pipelines/run_pipeline.py` completes without error |
| Quarantine table populated | `SELECT COUNT(*) FROM silver.quarantine` > 0 |
| DQ score < 100 (problems detected) | DQ report shows at least some WARN/FAIL |
| CTL-07 PASS (reconciliation balanced) | raw = silver + quarantine |
| All 10 SQL queries return results | Each query produces > 0 rows |
| Tests pass | `pytest tests/ -v` all green |
| No secrets committed | `.env` not in repo; `.env.example` has no real values |

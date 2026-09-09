# PaymentPulse — Interview Guide (Tier 1)

**Purpose:** Helps you defend every design decision in a technical interview.  
**Scope:** Tier 1 only (local pipeline). Tier 2/3 questions will be added when built.

> [!IMPORTANT]
> Every answer here refers to the actual implementation.
> No generic textbook answers — these are specific to the code you built.

---

## Architecture Questions

### Why Bronze/Silver/Gold?

**Short answer:** To separate concerns between data preservation, data cleaning,
and analytical usability — three different jobs that need different rules and
different audiences.

**Longer answer:** Bronze is the raw landing zone — nothing is deleted or
transformed. If a business rule changes tomorrow (e.g. a new valid currency is
added), you can reprocess Bronze with the new rule without going back to the
source. Silver applies consistent validation rules (one place to update).
Gold is optimised for analysts — a clean star schema with surrogate keys and
derived flags (`is_success`, `is_failed`) so queries are simple and fast.

**In this project:** `bronze.raw_transactions` stores every CSV row as strings.
`silver.transactions` has typed fields and no duplicates. `silver.quarantine`
holds every rejected row with a documented reason. `gold.fact_transactions` is
the dimensional fact table that all 10 analytics queries run against.

---

### Why DuckDB instead of PostgreSQL?

**Short answer:** Zero configuration, column-oriented (fast aggregations),
ANSI SQL compatible, and the queries are Snowflake-portable.

**Longer answer:** For a local portfolio project, DuckDB is strictly better
than PostgreSQL: no server process to manage, no connection strings, no
user/password setup. The database is a single file (`data/paymentpulse.duckdb`)
that you can commit, copy, or share. DuckDB's columnar storage means
`SUM(amount) GROUP BY date` on 75,000 rows runs in milliseconds. Every query
in `sql/analytics/analytics.sql` is written in standard SQL that runs unmodified
on Snowflake.

---

### Why pandas instead of PySpark in Tier 1?

**Short answer:** The brief explicitly defers Spark to Tier 2. PySpark adds JVM
configuration complexity on Windows for zero marginal value at 75,000 rows.

**Longer answer:** The Silver transformation logic — type casting, deduplication,
quarantine — is implemented identically whether you use pandas or PySpark. The
pandas version is testable (pytest can import it without a Spark context), runs
on any laptop, and produces the same output. When Tier 2 is built, the
transformation logic will be ported to `pyspark.sql.functions` — the patterns
(`filter`, `withColumn`, `dropDuplicates`) map 1:1.

---

### How would this scale to millions of transactions?

**Short answer:** Partitioning, Parquet format, and Spark for the transformation
layer. The SQL stays essentially the same.

**Details:**
- Storage: replace DuckDB file with S3 Delta tables, partitioned by `YYYY/MM/DD`
- Compute: replace pandas with PySpark — same logical transformations, distributed
- Incremental loading: merge/UPSERT on `transaction_id` rather than full batch reload
- Query engine: Snowflake with appropriate clustering key on `ts` for time-range queries
- Orchestration: Airflow DAGs or Databricks Workflows

---

## Data Quality Questions

### How did you identify bad data?

**Short answer:** I deliberately injected 10 types of known problems at configurable
rates, then built checks to detect each type.

**Details:** The generator (`generate.py`) uses pre-computed index sets to inject:
null customer IDs, null amounts, duplicate transaction IDs, invalid currencies, invalid
statuses, orphan customer/merchant IDs, malformed timestamps, future timestamps, and
negative amounts. The rates are all in `config/config.yaml` so they're reproducible.

The DQ framework then runs 14 checks across 5 dimensions (completeness, uniqueness,
validity, referential integrity, freshness/volume) and produces a PASS/WARN/FAIL
result per check. This demonstrates end-to-end: you can see exactly which problems
were injected and which checks caught them.

---

### What happens to invalid records?

**Short answer:** They go to `silver.quarantine` with a documented rejection reason.
They are never silently deleted.

**Details:** The Silver transformation in `warehouse.py` evaluates every raw record
against 8 validation rules. If any rule fails, the record is written to
`silver.quarantine` with the rejection reason(s) concatenated. The `quarantine`
table retains the original JSON-serialised raw record for audit purposes.

CTL-07 (Reconciliation) then verifies that `raw count == silver + quarantine`,
proving no records were silently lost.

---

### How do you prevent duplicate transaction IDs?

**Short answer:** Deduplication in Silver — the second occurrence of any
`transaction_id` is quarantined, not promoted to Silver.

**Details:** The Silver transformation (`_build_silver` in `warehouse.py`) maintains
a `seen_txn_ids` set. Each record is checked before being added to the silver or
quarantine list. The first occurrence of a duplicate is kept (Silver); subsequent
occurrences are quarantined with reason `duplicate transaction_id: <id>`. CTL-01
then verifies the Gold fact table has zero duplicates.

---

### What is data reconciliation and why does it matter?

**Short answer:** Reconciliation proves that every raw record ended up either in
Silver or in Quarantine — no silent data loss.

**Details:** CTL-07 computes:
```
raw_count == silver_count + quarantine_count
```
If delta ≠ 0, some records were processed without being accounted for anywhere.
In a financial-services pipeline, this would be a critical defect — you cannot
explain to a regulator why a payment that arrived at the ingestion layer doesn't
appear in either the clean dataset or the rejection log.

In this project, delta is always 0 because every record that fails validation
is explicitly quarantined. The test `test_ctl_07_reconciliation_passes` verifies
this on every test run.

---

### How do you handle schema drift?

**Short answer:** CTL-06 queries `information_schema.columns` to verify that all
expected column names are present in the Gold tables after every pipeline run.

**Details:** If an upstream column was renamed or dropped, CTL-06 would FAIL
immediately — before any analytics ran on broken data. The ingestion layer also
runs schema validation (`validate_schema` in `ingest.py`) at the Bronze level,
catching schema problems before any transformation work is done.

---

## SQL Questions

### Explain your fact and dimension tables.

**Fact table:** `gold.fact_transactions` — one row per payment transaction.
Grain: one transaction. Contains measurable facts (amount, status flags) and
foreign keys to all dimensions. Designed for aggregation queries.

**Dimensions:**
- `dim_customer`: who initiated the payment (segment, country)
- `dim_merchant`: who received the payment (category, risk_category)
- `dim_payment_method`: how the payment was made (method group)
- `dim_date`: when the payment occurred (year, quarter, month, day, weekend flag)

This is a classic star schema — the fact table JOINs to dimensions via integer
surrogate keys. Surrogate keys are better than natural keys in a warehouse because
they isolate the analytical model from upstream source key changes.

---

### How would you optimise a slow query in Snowflake?

**Short answer:** Clustering key on the time dimension, appropriate warehouse size,
and materialised views for frequently-executed aggregations.

**Details:**
1. `CLUSTER BY (ts::DATE)` on `FACT_TRANSACTIONS` — time-range filters prune
   micro-partitions efficiently
2. Choose warehouse size to match workload — Small for interactive queries,
   Medium/Large for batch aggregations
3. Materialise `payment_daily_metrics` as a scheduled task — pre-aggregate daily
   KPIs so dashboards hit a summary table, not the 75M-row fact table
4. Use `RESULT_CACHE` for repeated identical queries (automatic in Snowflake)

---

## Payments Domain Questions

### What is a payment lifecycle?

**Short answer:** The sequence of states a payment passes through from
initiation to final settlement or failure.

**In this project:** INITIATED → SUCCESS | FAILED | PENDING → SUCCESS | REVERSED.
Every transaction starts as INITIATED. Most resolve to SUCCESS (≈78%) or FAILED
(≈12%). PENDING transactions are awaiting bank confirmation (e.g. open banking
or 3DS authentication). REVERSED indicates a post-settlement reversal (refund
or chargeback).

---

### What metrics matter most to a payments operations team?

**In priority order:**
1. **Success rate** — fraction of transactions that settle successfully. Drop
   below ~95% and it's an operational incident
2. **Failure rate by payment method** — a spike on one method points to a
   routing or acquiring issue
3. **Daily transaction volume and value** — baseline health metric; unusual
   spikes or drops are early warning signals
4. **Merchant failure rate** — specific merchants with high failure rates may
   indicate merchant-side technical issues or fraud targeting
5. **Geographic failure rate** — concentration of failures in one country may
   indicate network issues or local banking regulations

All five are answered by the 10 SQL queries in `sql/analytics/analytics.sql`.

---

### What could cause elevated payment failure rates?

**Technical causes:**
- Payment routing issues (bank connection timeouts)
- Card network outages (Visa/Mastercard)
- Merchant acquirer problems

**Business/risk causes:**
- Fraud rule misfires declining legitimate transactions
- Card expiry not updated by customers
- Insufficient funds (higher during end-of-month periods)
- 3DS authentication friction causing abandonment

**Data quality causes:**
- Malformed card data from merchant integration
- Currency mismatch between merchant and acquiring bank

---

## Controls Questions

### Why are data controls important in financial services?

**Short answer:** Regulators require auditable evidence that payment data is
accurate, complete, and controlled. Controls are that evidence.

**Longer answer:** Financial regulators (PRA, FCA in the UK; Basel III globally)
require that banks can demonstrate data integrity through documented controls.
A data-quality "score" isn't sufficient — you need to show that specific,
named controls with specific failure criteria were run, and that failures are
escalated and resolved. CTL-07 (Reconciliation) is particularly important because
it proves that no payment record was silently lost between the source and the
analytical layer.

---

### How would you monitor control failures in production?

**Short answer:** Alert on FAIL status from the control report; route to an
incident management system; track control breach counts on an operational dashboard.

**Production approach:**
- Write control results to a monitoring table in Snowflake
- Set up Datadog / CloudWatch alerts on `fail_count > 0`
- P1 incident for CTL-01 (uniqueness) or CTL-07 (reconciliation) — financial data
- P2 incident for CTL-05 (freshness) — operational impact within SLA
- Report control breach trends weekly to data governance committee

---

### What was your most important finding?

**Answer:** Based on our pipeline execution across 75,000 transactions:

1. **Failure & Friction Concentration:** While the overall platform failure rate is 5.47% (3,941 transactions), standing orders (5.69%) and bank transfers (5.59%) exhibit the highest failure rates, primarily driven by account-level verification delays and batch settlement windows.
2. **Merchant Risk Disparity:** High-risk tier merchants (10% of merchant base) experienced an elevated failure rate of over 30%, accounting for more than 25% of all platform transaction failures.
3. **Quarantine Distribution:** Of 2,947 quarantined records (3.93% quarantine rate), 366 were rejected due to null customer identifiers and 221 due to missing/unparseable amounts, proving that the primary data vulnerabilities stem from mobile/app client ingestion rather than batch back-office feeds.

---

### What recommendation would you give a payments operations team?

**Based on this dataset:**

> 1. **Implement Dynamic Pre-routing for High-Risk Merchants:** Route transactions originating from high-risk merchants through secondary acquiring channels with adaptive 3DS challenge rules.
> 2. **Client-Side Validation Hardening:** 587 quarantine errors occurred due to missing customer IDs and blank amounts at ingestion. Adding client-side payload validation on mobile and web checkout SDKs will prevent these flawed requests from ever entering the ingestion queue.
> 3. **Real-time Monitoring of CTL-07 Reconciliation:** Maintain continuous automated reconciliation alerts. The 0-delta balance between raw (75,000), curated Silver (72,053), and Quarantine (2,947) provides audit-proof evidence for FCA/PRA regulatory audits.

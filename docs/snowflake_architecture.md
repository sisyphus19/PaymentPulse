# PaymentPulse — Snowflake Architecture & Optimization Guide

**Execution Status:** Target Production Architecture (Not executed locally)  
**Target Platform:** Snowflake Enterprise on AWS eu-west-2 (London)  
**Local Equivalent:** Executed locally in DuckDB (ANSI SQL compatible)

---

## 1. Architectural Philosophy: Decoupled Compute & Storage

In traditional RDBMS (like PostgreSQL or on-premise Oracle), compute and storage scale jointly, meaning high concurrency reporting competes for IOPS with batch transformation pipelines.

Snowflake decouples compute from storage via three layers:
1. **Cloud Services Layer**: Metadata management, query compilation, transaction management, and access control.
2. **Virtual Warehouse Layer**: Independent MPP clusters of compute nodes that read from shared storage without data contention.
3. **Database Storage Layer**: Scalable object storage (AWS S3) formatted into Snowflake's proprietary columnar micro-partitions.

### Workload Isolation Strategy in PaymentPulse

```
                          ┌──────────────────────────┐
                          │  Shared Data in S3 /     │
                          │  Snowflake Micro-parts   │
                          └─────────────┬────────────┘
                                        │
                 ┌──────────────────────┴──────────────────────┐
                 ▼                                             ▼
     [PAYMENTS_ETL_WH]                             [PAYMENTS_ANALYTICS_WH]
     - Size: MEDIUM                                - Size: X-SMALL (Auto-scale 1-3)
     - Target: Batch dbt runs & pipeline ingestion - Target: Power BI & Operations
     - Auto-suspend: 60s                           - Auto-suspend: 120s
```

---

## 2. Micro-Partitioning & Clustering Strategy

Snowflake stores data in **micro-partitions** (typically 50MB to 500MB of uncompressed data). Each micro-partition contains columnar data with header metadata tracking min/max values for every column.

### Clustering Choice: `CLUSTER BY (TO_DATE(TS))`
On `FACT_TRANSACTIONS`, the table is clustered by transaction date:
```sql
ALTER TABLE FACT_TRANSACTIONS CLUSTER BY (TO_DATE(TS));
```

**Interview Defence:**
- **Natural Query Pattern:** Financial reporting and fraud audits are overwhelmingly time-bounded (e.g. "failures in the last 7 days" or "daily settlement reconciliation").
- **Partition Pruning:** When a query filters `WHERE ts >= '2026-09-01'`, Snowflake's compiler inspects partition min/max metadata and skips reading 95%+ of micro-partitions entirely, reducing scan time and compute credit consumption.
- **Why not index?** Snowflake does not have B-tree indexes. Attempting to create indexes like in Postgres reflects an outdated RDBMS mindset. Clustering provides equivalent or superior benefits in an immutable columnar architecture.

---

## 3. Constraint Handling in Snowflake

Snowflake allows defining `PRIMARY KEY` and `FOREIGN KEY` constraints, but **does not enforce them during INSERT / UPDATE operations** (with the exception of `NOT NULL`).

**Why we still declare them:**
```sql
CONSTRAINT fk_customer FOREIGN KEY (CUSTOMER_SK) REFERENCES DIM_CUSTOMER(CUSTOMER_SK) RELY NOT ENFORCED
```
1. **Join Elimination:** The Snowflake Cost-Based Optimizer (CBO) uses declared foreign keys to eliminate unnecessary joins if only the primary table attributes are requested.
2. **BI Tool Introspection:** Power BI, Tableau, and data governance catalogs automatically parse table relationships from metadata.
3. **Enforcement Shift:** Referential integrity and uniqueness are verified upstream in the pipeline (as proven by PaymentPulse controls CTL-01 and CTL-02).

---

## 4. Query Optimization & Caching Layers

Snowflake provides three levels of caching:

1. **Metadata Cache** (Cloud Services): Instant results for `COUNT(*)` or `MAX(date)`. Zero virtual warehouse compute is consumed.
2. **Query Result Cache** (Cloud Services): If an analyst runs the exact same query within 24 hours and underlying data has not changed, Snowflake returns the pre-computed result instantly for zero credits.
3. **Local Disk Cache** (Virtual Warehouse SSD): Frequently scanned micro-partitions remain on worker SSDs while the warehouse is active.

# PaymentPulse — Data Controls Documentation

**Execution environment:** Local — executed against DuckDB  
**Version:** 1.0 (Tier 1)

---

## Why Data Controls?

In financial services, data controls are mandatory governance artefacts. Unlike
data-quality checks (which detect problems statistically), controls are binary
assertions: the data either meets the control requirement or it does not. Control
failures trigger an incident process in production environments.

Regulators (PRA, FCA, Basel III) require that payment data pipelines have
documented controls over data integrity, completeness, and accuracy. This
framework simulates that governance layer.

---

## Control Inventory

| Control ID | Name | Layer | Status | Frequency |
|---|---|---|---|---|
| CTL-01 | Transaction Uniqueness | Gold | Binary (PASS/FAIL) | Per batch |
| CTL-02 | Referential Integrity | Gold | Binary (PASS/FAIL) | Per batch |
| CTL-03 | Amount Validation | Gold | Binary (PASS/FAIL) | Per batch |
| CTL-04 | Status Validity | Gold | Binary (PASS/FAIL) | Per batch |
| CTL-05 | Pipeline Freshness | Silver | Binary (PASS/FAIL) | Per batch |
| CTL-06 | Schema Validation | Gold | Binary (PASS/FAIL) | Per batch |
| CTL-07 | Reconciliation | Bronze/Silver | Binary (PASS/FAIL) | Per batch |

---

## CTL-01 — Transaction Uniqueness

**Why it exists:** Duplicate `transaction_id` values in the Gold fact table
would cause double-counting of transaction volumes and values in every
downstream report. For a payments platform, this would misrepresent revenue
and regulatory exposure metrics.

**What it checks:**
```sql
SELECT COUNT(*) - COUNT(DISTINCT transaction_id)
FROM gold.fact_transactions
-- Must equal 0
```

**Control owner:** Data Engineering  
**Failure severity:** Critical — analytical data is untrustworthy  
**Remediation:** Re-run Silver deduplication; investigate Bronze source for
upstream duplicate injection

---

## CTL-02 — Referential Integrity

**Why it exists:** Fact rows with NULL dimension keys cannot be attributed to
a customer or merchant. Merchant performance reports and customer spend analysis
both require complete dimension resolution. Orphan facts are silent data loss.

**What it checks:**
```sql
SELECT COUNT(*)
FROM gold.fact_transactions
WHERE customer_sk IS NULL
   OR merchant_sk IS NULL
   OR payment_method_sk IS NULL
-- Must equal 0
```

**Control owner:** Data Engineering  
**Failure severity:** High — dimension reports will be incomplete  
**Remediation:** Verify dim tables are populated before fact table; check
Silver→Gold join keys

---

## CTL-03 — Amount Validation

**Why it exists:** Transaction amounts must be positive and within a
configurable business ceiling. Negative amounts indicate upstream processing
errors or potentially fraudulent manipulation. Amounts above the ceiling
(default: £1,000,000) may indicate data entry errors or system faults.

**Configuration:** `controls.max_transaction_amount` in `config/config.yaml`

**What it checks:**
```sql
SELECT COUNT(*)
FROM gold.fact_transactions
WHERE amount IS NULL OR amount <= 0 OR amount > 1000000
-- Must equal 0
```

**Control owner:** Payments Operations  
**Failure severity:** High — financial exposure may be misstated  
**Remediation:** Quarantine invalid-amount records in Silver; investigate
source system for amount validation

---

## CTL-04 — Status Validity

**Why it exists:** Only the five approved payment lifecycle statuses are valid:
INITIATED, SUCCESS, FAILED, PENDING, REVERSED. Any other value indicates
schema drift in the upstream system or a processing error. Gold must contain
only approved values so that Boolean flags (`is_success`, `is_failed`) are
reliable.

**Approved values:** INITIATED, SUCCESS, FAILED, PENDING, REVERSED

**What it checks:**
```sql
SELECT COUNT(*)
FROM gold.fact_transactions
WHERE status NOT IN ('INITIATED','SUCCESS','FAILED','PENDING','REVERSED')
-- Must equal 0
```

**Control owner:** Payments Operations / Data Engineering  
**Failure severity:** High — KPI calculations (success rate) will be wrong  
**Remediation:** Add status to Silver quarantine criteria; alert upstream team

---

## CTL-05 — Pipeline Freshness

**Why it exists:** Stale data causes operations teams to make decisions based
on outdated payment flows. In a 24/7 payments environment, a pipeline that
stops delivering data is an operational incident.

**Configuration:** `controls.freshness_sla_hours` (default: 24 hours)

**What it checks:**
```sql
SELECT MAX(ts) FROM silver.transactions
-- Must be within NOW() - 24 hours
```

**Control owner:** Data Engineering / Payments Operations  
**Failure severity:** High — operational decisions may be based on stale data  
**Remediation:** Investigate pipeline schedule and source availability

> **Note (local execution):** The synthetic generator creates transactions
> spanning the last 90 days, so CTL-05 will FAIL in the local pipeline when
> the most recent generated transaction is older than the SLA. This is expected
> behaviour for synthetic historical data and documented here explicitly.
> In production, real-time feeds would populate recent timestamps and this
> control would be meaningful.

---

## CTL-06 — Schema Validation

**Why it exists:** Schema drift — columns being added, removed, or renamed
in upstream systems — is a common cause of silent analytical breakage. This
control detects structural changes before they corrupt downstream reports.

**What it checks:** Queries `information_schema.columns` to verify all expected
column names are present in Gold tables.

**Control owner:** Data Engineering  
**Failure severity:** Medium — pipeline may still run but analytics will break  
**Remediation:** Review DDL changes; version the schema; update downstream consumers

---

## CTL-07 — Reconciliation

**Why it exists:** This is the pipeline integrity control. In financial services,
every input record must be traceable to either a clean output or an explicit
rejection. Silent record loss — records that disappear between Bronze and Silver
without appearing in quarantine — is a critical defect. Regulators require that
input-to-output reconciliation is documented for payment data pipelines.

**Formula:** `raw_count == silver_count + quarantine_count`

**What it checks:**
```sql
-- Executes the reconciliation query in sql/controls/reconciliation.sql
-- Delta must equal 0
```

**Expected Silver shortfall:** Silver will contain fewer records than Bronze
because invalid records are moved to quarantine. This is by design. The
reconciliation formula accounts for this: every quarantined record is tracked.

**Control owner:** Data Engineering / Audit  
**Failure severity:** Critical — record loss in a financial pipeline  
**Remediation:** Audit Silver transformation for unlogged record drops;
add exception handling to quarantine any record that fails processing

---

## Control Report Format

Each control produces:

```
control_id            : CTL-07
control_name          : Reconciliation
status                : PASS
detail                : Raw=75000 | Silver=72340 | Quarantine=2660 | Delta=0 (balanced)
records_checked       : 75000
records_failed        : 0
execution_timestamp   : 2024-01-15T10:30:00Z
remediation           : (empty if PASS)
```

---

## Relationship Between DQ Checks and Controls

| Aspect | DQ Checks | Controls |
|---|---|---|
| Output | PASS / WARN / FAIL | PASS / FAIL |
| Nature | Statistical (rate-based) | Binary assertion |
| Scope | Silver layer | Gold + pipeline |
| Threshold | Configurable (warn/fail %) | Zero tolerance |
| Governance | Data quality reporting | Regulatory governance |
| Escalation | Dashboard / trend monitoring | Incident process |

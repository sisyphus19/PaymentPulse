-- PaymentPulse — Reconciliation Control (CTL-07)
-- ================================================
-- These SQL statements verify that no records are silently lost
-- between the Bronze raw layer and Silver + Quarantine layers.
-- In financial services, every input record must be accounted for —
-- either processed into Silver or explicitly rejected into Quarantine.
--
-- Usage: Run after warehouse.build_warehouse() for a specific batch.
-- Replace :batch_id with the actual batch UUID.
-- -------------------------------------------------------------------------

-- Step 1: Count raw records for the batch
SELECT
    'bronze.raw_transactions' AS layer,
    COUNT(*)                  AS record_count
FROM bronze.raw_transactions
WHERE batch_id = :batch_id;

-- Step 2: Count Silver records for the batch
SELECT
    'silver.transactions'     AS layer,
    COUNT(*)                  AS record_count
FROM silver.transactions
WHERE batch_id = :batch_id;

-- Step 3: Count quarantine records for the batch
SELECT
    'silver.quarantine'       AS layer,
    COUNT(*)                  AS record_count
FROM silver.quarantine
WHERE batch_id = :batch_id;

-- Step 4: Reconciliation summary — delta should be 0
SELECT
    raw.record_count                        AS raw_count,
    sil.record_count                        AS silver_count,
    qar.record_count                        AS quarantine_count,
    sil.record_count + qar.record_count     AS accounted_count,
    raw.record_count
        - (sil.record_count + qar.record_count) AS delta,
    CASE
        WHEN raw.record_count
             = sil.record_count + qar.record_count
        THEN 'PASS — fully reconciled'
        ELSE 'FAIL — unaccounted records: '
             || CAST(raw.record_count
                     - (sil.record_count + qar.record_count) AS VARCHAR)
    END AS reconciliation_status
FROM (
    SELECT COUNT(*) AS record_count
    FROM bronze.raw_transactions WHERE batch_id = :batch_id
) raw
CROSS JOIN (
    SELECT COUNT(*) AS record_count
    FROM silver.transactions WHERE batch_id = :batch_id
) sil
CROSS JOIN (
    SELECT COUNT(*) AS record_count
    FROM silver.quarantine WHERE batch_id = :batch_id
) qar;

-- Step 5: Top quarantine rejection reasons
SELECT
    rejection_reason,
    COUNT(*) AS occurrence_count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_of_quarantine
FROM silver.quarantine
WHERE batch_id = :batch_id
GROUP BY rejection_reason
ORDER BY occurrence_count DESC
LIMIT 20;

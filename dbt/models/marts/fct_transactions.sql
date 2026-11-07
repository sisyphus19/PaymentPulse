WITH stg_txns AS (
    SELECT * FROM {{ ref('stg_transactions') }}
)

SELECT
    transaction_id,
    customer_id,
    merchant_id,
    payment_method,
    ts,
    date_sk,
    amount,
    currency,
    country,
    channel,
    device_type,
    status,
    status = 'SUCCESS' AS is_success,
    status = 'FAILED' AS is_failed,
    status = 'REVERSED' AS is_reversed,
    batch_id
FROM stg_txns

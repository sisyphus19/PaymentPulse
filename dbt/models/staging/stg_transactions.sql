WITH source AS (
    SELECT * FROM {{ source('silver', 'transactions') }}
)

SELECT
    transaction_id,
    customer_id,
    merchant_id,
    payment_method,
    ts,
    CAST(strftime(ts::DATE, '%Y%m%d') AS INTEGER) AS date_sk,
    amount,
    currency,
    country,
    channel,
    device_type,
    status,
    batch_id,
    _loaded_at
FROM source

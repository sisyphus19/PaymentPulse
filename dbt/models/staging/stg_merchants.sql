WITH source AS (
    SELECT * FROM {{ source('silver', 'merchants') }}
)

SELECT
    merchant_id,
    name AS merchant_name,
    category AS merchant_category,
    country AS merchant_country,
    risk_category,
    batch_id
FROM source

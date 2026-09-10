WITH source AS (
    SELECT * FROM {{ source('silver', 'customers') }}
)

SELECT
    customer_id,
    name AS customer_name,
    email AS customer_email,
    segment AS customer_segment,
    country AS customer_country,
    customer_since,
    batch_id
FROM source

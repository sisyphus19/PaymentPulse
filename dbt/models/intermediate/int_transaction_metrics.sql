WITH transactions AS (

    SELECT *
    FROM {{ ref('stg_transactions') }}

),

daily_metrics AS (

    SELECT
        date_sk,
        ts::DATE AS metric_date,

        COUNT(*) AS total_transactions,

        COUNT(CASE WHEN status = 'SUCCESS' THEN 1 END)
            AS successful_transactions,

        COUNT(CASE WHEN status = 'FAILED' THEN 1 END)
            AS failed_transactions,

        COUNT(CASE WHEN status = 'PENDING' THEN 1 END)
            AS pending_transactions,

        COUNT(CASE WHEN status = 'REVERSED' THEN 1 END)
            AS reversed_transactions,

        COUNT(CASE WHEN status = 'INITIATED' THEN 1 END)
            AS initiated_transactions,

        ROUND(SUM(amount), 2)
            AS total_transaction_value,

        ROUND(AVG(amount), 2)
            AS average_transaction_value,

        ROUND(MIN(amount), 2)
            AS minimum_transaction_value,

        ROUND(MAX(amount), 2)
            AS maximum_transaction_value

    FROM transactions

    GROUP BY
        date_sk,
        ts::DATE

)

SELECT
    date_sk,
    metric_date,
    total_transactions,
    successful_transactions,
    failed_transactions,
    pending_transactions,
    reversed_transactions,
    initiated_transactions,
    total_transaction_value,
    average_transaction_value,
    minimum_transaction_value,
    maximum_transaction_value,

    ROUND(
        100.0 * successful_transactions
        / NULLIF(total_transactions, 0),
        2
    ) AS success_rate_pct,

    ROUND(
        100.0 * failed_transactions
        / NULLIF(total_transactions, 0),
        2
    ) AS failure_rate_pct,

    ROUND(
        100.0 * reversed_transactions
        / NULLIF(total_transactions, 0),
        2
    ) AS reversal_rate_pct

FROM daily_metrics
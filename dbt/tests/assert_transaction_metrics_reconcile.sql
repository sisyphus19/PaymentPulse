WITH metrics AS (

    SELECT
        metric_date,
        total_transactions,
        successful_transactions,
        failed_transactions,
        pending_transactions,
        reversed_transactions,
        initiated_transactions

    FROM {{ ref('int_transaction_metrics') }}

),

reconciled AS (

    SELECT
        metric_date,

        total_transactions,

        (
            successful_transactions
            + failed_transactions
            + pending_transactions
            + reversed_transactions
            + initiated_transactions
        ) AS status_total

    FROM metrics

)

SELECT *
FROM reconciled
WHERE total_transactions <> status_total
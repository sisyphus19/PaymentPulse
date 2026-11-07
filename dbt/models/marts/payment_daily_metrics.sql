SELECT
    date_sk,
    metric_date,

    total_transactions,
    successful_transactions,
    failed_transactions,
    pending_transactions,
    reversed_transactions,
    initiated_transactions,

    total_transaction_value AS total_volume_gbp,
    average_transaction_value AS avg_transaction_amount,

    success_rate_pct,
    failure_rate_pct,
    reversal_rate_pct

FROM {{ ref('int_transaction_metrics') }}

ORDER BY metric_date DESC
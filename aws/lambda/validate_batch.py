"""AWS Lambda hook for pre-deployment batch validation.

The function is intentionally small: SageMaker/Step Functions own orchestration,
while Lambda performs a cheap policy gate before a model promotion/deployment step.
"""

from __future__ import annotations


def handler(event, context):
    required = ["batch_id", "dq_score", "control_status", "reconciliation_delta"]
    missing = [key for key in required if key not in event]
    if missing:
        raise ValueError(f"Missing required fields: {missing}")

    approved = (
        float(event["dq_score"]) >= 95.0
        and event["control_status"] == "PASS"
        and int(event["reconciliation_delta"]) == 0
    )

    return {
        "batch_id": event["batch_id"],
        "approved": approved,
        "reason": "validation_passed" if approved else "data_quality_or_control_gate_failed",
    }

# PaymentPulse — MLOps & AWS Production Design

PaymentPulse's local implementation is intentionally cloud-independent. This document maps the same lifecycle to an AWS production operating model without claiming that the AWS resources have been deployed.

## Lifecycle

```text
Raw payments
    |
    v
S3 landing zone
    |
    v
Step Functions orchestration
    |
    +--> Lambda validation gate
    |       +-- schema / DQ / controls / reconciliation
    |
    v
SageMaker Processing
    |
    v
SageMaker Training --> MLflow experiment/model lineage
    |
    v
Model validation / promotion gate
    |
    v
SageMaker Model + Endpoint
    |
    +--> CloudWatch logs / metrics / alarms
    |
    +--> Feature drift monitor --> retraining workflow
```

## Service responsibilities

| Capability | AWS component | PaymentPulse implementation/design |
|---|---|---|
| Object storage | S3 | Raw data, curated datasets and model artifacts |
| Orchestration | Step Functions | State-machine reference in `aws/step_functions/` |
| Validation hook | Lambda | `aws/lambda/validate_batch.py` |
| ML workflow | SageMaker Pipelines | `aws/sagemaker_pipeline.py` |
| Model training | SageMaker Training | Scikit-learn Isolation Forest |
| Model tracking | MLflow | Local experiment tracking; production design uses remote artifact storage + DB-backed registry |
| Monitoring | CloudWatch | Pipeline/system/model metrics and alarms |
| CI/CD | GitHub Actions | `.github/workflows/ci.yml` |
| Packaging | Docker | `Dockerfile` |

## Governance gates

Model promotion should be blocked when:

- DQ score falls below the deployment threshold.
- A data control fails.
- Reconciliation delta is non-zero.
- Required model metadata or feature schema is missing.
- Operational risk-score distribution falls outside configured guardrails.

The local `mlops/validate.py` implements the model metadata gate. The Lambda function demonstrates the equivalent AWS pre-deployment control.

## Monitoring strategy

`mlops/monitor.py` implements a lightweight Population Stability Index (PSI) monitor for numerical risk features. In AWS, the resulting metrics can be published to CloudWatch and used by an alarm to trigger investigation or retraining through Step Functions/SageMaker Pipelines.

The project does **not** claim a deployed AWS endpoint, SageMaker job, or CloudWatch dashboard; those are the production target architecture represented by the code and design artifacts.

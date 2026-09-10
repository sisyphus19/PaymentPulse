# PaymentPulse MLOps

The MLOps layer turns the risk model into a repeatable lifecycle rather than a one-off model script.

## Local lifecycle

```powershell
pip install -e ".[dev,mlops]"
python pipelines\run_pipeline.py
python mlops\train.py
python mlops\validate.py
```

Optional MLflow tracking:

```powershell
python mlops\train.py --mlflow
mlflow server --host 127.0.0.1 --port 8080
```

The training script logs model parameters, operational metrics and the sklearn model artifact. MLflow provides experiment tracking and model lineage; a production setup would use remote artifact storage and a database-backed tracking/registry service.

## Drift monitoring

Create a baseline profile from a trusted reference dataset:

```powershell
python mlops\monitor.py --build-reference --reference artifacts\reference_profile.json
```

Then compare a later batch:

```powershell
python mlops\monitor.py --reference artifacts\reference_profile.json
```

PSI >= 0.20 is treated as a drift signal by default. This is an operational threshold, not a fraud-performance metric.

## AWS

See `docs/mlops_aws_architecture.md`, `aws/sagemaker_pipeline.py`, `aws/lambda/validate_batch.py`, and `aws/step_functions/paymentpulse_state_machine.json` for the production mapping to S3, SageMaker Pipelines, Lambda, Step Functions and CloudWatch.

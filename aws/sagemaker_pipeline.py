"""Build the AWS SageMaker Pipeline definition for PaymentPulse.

This file is a deployment-oriented reference implementation. It does not create
AWS resources automatically; credentials, S3 locations, IAM roles, and an AWS
account are required to submit the pipeline.
"""
from __future__ import annotations

import os


def build_pipeline():
    try:
        from sagemaker.workflow.pipeline import Pipeline
        from sagemaker.workflow.parameters import ParameterString
        from sagemaker.workflow.steps import ProcessingStep, TrainingStep
        from sagemaker.sklearn.processing import SKLearnProcessor
        from sagemaker.sklearn.estimator import SKLearn
        from sagemaker.processing import ProcessingInput, ProcessingOutput
    except ImportError as exc:
        raise RuntimeError("Install AWS dependencies with: pip install -e '.[aws]'") from exc

    role = os.environ["SAGEMAKER_EXECUTION_ROLE_ARN"]
    bucket = os.environ["PAYMENTPULSE_ARTIFACT_BUCKET"]
    processing_instance = os.environ.get("SAGEMAKER_PROCESSING_INSTANCE", "ml.t3.medium")
    training_instance = os.environ.get("SAGEMAKER_TRAINING_INSTANCE", "ml.m5.large")
    framework_version = os.environ.get("SKLEARN_FRAMEWORK_VERSION", "1.2-1")

    input_uri = ParameterString(name="InputDataUri", default_value=f"s3://{bucket}/input/")

    processor = SKLearnProcessor(
        framework_version=framework_version,
        role=role,
        instance_type=processing_instance,
        instance_count=1,
        base_job_name="paymentpulse-process",
    )
    processing_step = ProcessingStep(
        name="PrepareData",
        processor=processor,
        inputs=[ProcessingInput(source=input_uri, destination="/opt/ml/processing/input")],
        outputs=[
            ProcessingOutput(
                output_name="train",
                source="/opt/ml/processing/train",
                destination=f"s3://{bucket}/processed/",
            )
        ],
        code="mlops/train.py",
    )

    estimator = SKLearn(
        entry_point="mlops/train.py",
        role=role,
        instance_type=training_instance,
        instance_count=1,
        framework_version=framework_version,
        py_version="py3",
        base_job_name="paymentpulse-train",
    )
    training_step = TrainingStep(
        name="TrainRiskModel",
        estimator=estimator,
        depends_on=[processing_step],
    )

    return Pipeline(
        name="paymentpulse-mlops",
        parameters=[input_uri],
        steps=[processing_step, training_step],
    )


if __name__ == "__main__":
    pipeline = build_pipeline()
    print(pipeline.definition())

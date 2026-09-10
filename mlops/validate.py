"""Operational model validation gate used before deployment."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def validate(metadata_path: str = "artifacts/risk_model/metadata.json") -> None:
    path = Path(metadata_path)
    if not path.exists():
        raise SystemExit(f"Model metadata not found: {path}. Run mlops/train.py first.")

    metadata = json.loads(path.read_text(encoding="utf-8"))
    required = {"model_name", "model_type", "feature_columns", "training_rows", "high_risk_rate"}
    missing = required - metadata.keys()
    if missing:
        raise SystemExit(f"MODEL_VALIDATION_FAILED: missing metadata fields: {sorted(missing)}")

    failures = []
    if metadata["model_type"] != "IsolationForest":
        failures.append("unexpected model type")
    if metadata["training_rows"] < 1000:
        failures.append("insufficient training rows")
    if not 0.005 <= metadata["high_risk_rate"] <= 0.10:
        failures.append("high-risk rate outside operational guardrail [0.5%, 10%]")
    if len(metadata["feature_columns"]) != 8:
        failures.append("unexpected feature count")

    if failures:
        raise SystemExit("MODEL_VALIDATION_FAILED: " + "; ".join(failures))

    print("MODEL_VALIDATION_PASSED")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", default="artifacts/risk_model/metadata.json")
    args = parser.parse_args()
    validate(args.metadata)

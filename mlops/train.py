"""Train, validate, and optionally track the PaymentPulse risk model.

This is the local MLOps training entry point. It deliberately reuses the same
feature engineering and model code used by the analytics pipeline, so the
training path does not drift from production inference logic.

Local run:
    python mlops/train.py

With MLflow installed:
    pip install -e ".[mlops]"
    python mlops/train.py --mlflow
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path

import duckdb
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from paymentpulse.risk.features import extract_features  # noqa: E402
from paymentpulse.risk.model import AnomalyRiskModel, FEATURE_COLS  # noqa: E402


def train(config_path: str = "config/config.yaml", use_mlflow: bool = False) -> dict:
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    db_path = cfg["paths"]["db_path"]
    artifact_dir = ROOT / "artifacts" / "risk_model"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(db_path, read_only=True)
    try:
        features = extract_features(con)
    finally:
        con.close()

    model = AnomalyRiskModel()
    scored = model.fit_predict(features)

    model_path = artifact_dir / "model.pkl"
    metadata_path = artifact_dir / "metadata.json"
    with model_path.open("wb") as f:
        pickle.dump(model.model, f)

    high_rate = float((scored["risk_tier"] == "HIGH").mean())
    metadata = {
        "model_name": "paymentpulse-isolation-forest",
        "model_type": "IsolationForest",
        "feature_columns": FEATURE_COLS,
        "contamination": model.contamination,
        "random_state": model.random_state,
        "training_rows": len(scored),
        "high_risk_rate": round(high_rate, 6),
        "risk_score_mean": round(float(scored["risk_score"].mean()), 4),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    if use_mlflow:
        try:
            import mlflow
            import mlflow.sklearn
        except ImportError as exc:
            raise RuntimeError('Install MLflow with: pip install -e ".[mlops]"') from exc

        mlflow.set_experiment("PaymentPulse-Risk")
        with mlflow.start_run(run_name="isolation-forest-risk"):
            mlflow.log_params({
                "model_type": metadata["model_type"],
                "contamination": model.contamination,
                "n_estimators": 100,
                "random_state": model.random_state,
                "feature_count": len(FEATURE_COLS),
            })
            mlflow.log_metrics({
                "training_rows": len(scored),
                "high_risk_rate": high_rate,
                "risk_score_mean": metadata["risk_score_mean"],
            })
            mlflow.log_dict(metadata, "metadata.json")
            mlflow.sklearn.log_model(model.model, name="risk_model")

    print(json.dumps({**metadata, "model_path": str(model_path)}, indent=2))
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--mlflow", action="store_true", help="Track the run in MLflow")
    args = parser.parse_args()
    train(args.config, args.mlflow)


if __name__ == "__main__":
    main()

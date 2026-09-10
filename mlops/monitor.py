"""Simple production-style data drift monitor using Population Stability Index (PSI).

The script compares a reference feature profile against the current Silver dataset.
In AWS, the resulting metrics can be emitted to CloudWatch and used to trigger an
alert or retraining workflow.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import duckdb
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from paymentpulse.risk.features import extract_features  # noqa: E402

NUMERIC_FEATURES = ["amount", "amount_ratio", "customer_txn_count", "merchant_failure_rate", "hour_of_day"]


def psi(reference: np.ndarray, current: np.ndarray, bins: int = 10) -> float:
    edges = np.unique(np.quantile(reference, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return 0.0
    ref_hist, _ = np.histogram(reference, bins=edges)
    cur_hist, _ = np.histogram(current, bins=edges)
    ref_pct = np.clip(ref_hist / max(ref_hist.sum(), 1), 1e-6, None)
    cur_pct = np.clip(cur_hist / max(cur_hist.sum(), 1), 1e-6, None)
    return float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))


def build_reference(db_path: str, output: str) -> None:
    con = duckdb.connect(db_path, read_only=True)
    try:
        df = extract_features(con)
    finally:
        con.close()
    profile = {col: {"values": df[col].dropna().astype(float).tolist()} for col in NUMERIC_FEATURES}
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(profile), encoding="utf-8")
    print(f"Reference profile written to {output}")


def monitor(db_path: str, reference_path: str, threshold: float = 0.20) -> dict:
    profile = json.loads(Path(reference_path).read_text(encoding="utf-8"))
    con = duckdb.connect(db_path, read_only=True)
    try:
        current = extract_features(con)
    finally:
        con.close()
    results = {}
    for col in NUMERIC_FEATURES:
        reference = np.asarray(profile[col]["values"], dtype=float)
        current_values = current[col].dropna().to_numpy(dtype=float)
        score = psi(reference, current_values)
        results[col] = {"psi": round(score, 4), "status": "DRIFT" if score >= threshold else "STABLE"}
    print(json.dumps(results, indent=2))
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/paymentpulse.duckdb")
    parser.add_argument("--reference")
    parser.add_argument("--build-reference", action="store_true")
    parser.add_argument("--threshold", type=float, default=0.20)
    args = parser.parse_args()
    if args.build_reference:
        build_reference(args.db, args.reference or "artifacts/reference_profile.json")
    elif args.reference:
        monitor(args.db, args.reference, args.threshold)
    else:
        parser.error("Provide --reference or use --build-reference")

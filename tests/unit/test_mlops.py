"""Tests for the MLOps layer: the PSI drift monitor and the model validation gate."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "mlops" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


monitor = _load("pp_monitor", "monitor.py")
validate = _load("pp_validate", "validate.py")


# ---------------------------------------------------------------- PSI drift monitor

def test_psi_is_zero_for_identical_distributions():
    ref = np.random.default_rng(0).normal(size=5000)
    assert monitor.psi(ref, ref.copy()) < 1e-6


def test_psi_is_small_for_two_samples_of_the_same_distribution():
    rng = np.random.default_rng(1)
    ref, cur = rng.normal(size=20000), rng.normal(size=20000)
    assert monitor.psi(ref, cur) < 0.05


def test_psi_flags_a_shifted_distribution():
    rng = np.random.default_rng(2)
    ref, cur = rng.normal(0, 1, 20000), rng.normal(1.5, 1, 20000)
    assert monitor.psi(ref, cur) >= 0.20  # the default DRIFT threshold


def test_psi_with_constant_reference_does_not_divide_by_zero():
    assert monitor.psi(np.full(100, 3.0), np.random.default_rng(3).normal(size=100)) == 0.0


def test_monitor_reports_drift_only_for_the_shifted_feature(tmp_path, monkeypatch):
    rng = np.random.default_rng(4)
    n = 10000
    reference = {col: rng.normal(10, 2, n) for col in monitor.NUMERIC_FEATURES}
    ref_path = tmp_path / "reference.json"
    ref_path.write_text(
        json.dumps({c: {"values": v.tolist()} for c, v in reference.items()}), encoding="utf-8"
    )

    current = {col: rng.normal(10, 2, n) for col in monitor.NUMERIC_FEATURES}
    current["amount"] = rng.normal(16, 2, n)  # inject drift into one feature only

    class _FakeCon:
        def close(self):
            pass

    monkeypatch.setattr(monitor.duckdb, "connect", lambda *a, **k: _FakeCon())
    monkeypatch.setattr(monitor, "extract_features", lambda con: pd.DataFrame(current))

    results = monitor.monitor("unused.duckdb", str(ref_path), threshold=0.20)

    assert results["amount"]["status"] == "DRIFT"
    assert all(results[c]["status"] == "STABLE" for c in monitor.NUMERIC_FEATURES if c != "amount")


# ---------------------------------------------------------------- validation gate

def _metadata(**overrides):
    base = {
        "model_name": "paymentpulse-isolation-forest",
        "model_type": "IsolationForest",
        "feature_columns": [f"f{i}" for i in range(8)],
        "training_rows": 72053,
        "high_risk_rate": 0.045,
    }
    base.update(overrides)
    return base


def _write(tmp_path, metadata) -> str:
    path = tmp_path / "metadata.json"
    path.write_text(json.dumps(metadata), encoding="utf-8")
    return str(path)


def test_gate_passes_for_valid_metadata(tmp_path, capsys):
    validate.validate(_write(tmp_path, _metadata()))
    assert "MODEL_VALIDATION_PASSED" in capsys.readouterr().out


@pytest.mark.parametrize(
    "overrides, reason",
    [
        ({"model_type": "RandomForest"}, "unexpected model type"),
        ({"training_rows": 500}, "insufficient training rows"),
        ({"high_risk_rate": 0.20}, "outside operational guardrail"),
        ({"high_risk_rate": 0.001}, "outside operational guardrail"),
        ({"feature_columns": ["a", "b", "c"]}, "unexpected feature count"),
    ],
)
def test_gate_fails_when_a_guardrail_is_violated(tmp_path, overrides, reason):
    with pytest.raises(SystemExit) as exc:
        validate.validate(_write(tmp_path, _metadata(**overrides)))
    assert "MODEL_VALIDATION_FAILED" in str(exc.value)
    assert reason in str(exc.value)


def test_gate_fails_when_required_fields_are_missing(tmp_path):
    meta = _metadata()
    del meta["training_rows"]
    with pytest.raises(SystemExit) as exc:
        validate.validate(_write(tmp_path, meta))
    assert "missing metadata fields" in str(exc.value)


def test_gate_fails_when_metadata_file_is_absent(tmp_path):
    with pytest.raises(SystemExit) as exc:
        validate.validate(str(tmp_path / "nope.json"))
    assert "Run mlops/train.py first" in str(exc.value)

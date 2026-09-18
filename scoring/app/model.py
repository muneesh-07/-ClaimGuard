"""
Loads the Tier 1 trained model (tools/train_model.py's output, persisted
under scoring/models/) once per process and serves calibrated predictions
plus real SHAP explanations - the learned replacement for app.detector's
hardcoded fraud_score=0.9 / 0.85*ratio+0.15*burstiness rungs.

The M6 rungs are not discarded: app.features.build_feature_context() still
runs rung1_components/rung2_leiden/rung3_ppr internally to build this
model's feature columns, so the graph analytics survive as this model's
feature extractor rather than its final answer.

If no trained model exists on disk (a fresh checkout that hasn't run
`make train-model` yet), RingClassifier.load() returns None and callers
fall back to app.detector.detect() - a rule-based detector is a legitimate
answer to "the learned model isn't available yet," not a silent failure.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import shap
import xgboost as xgb

from app.features import ALL_FEATURES, FeatureContext, extract_features

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
MAX_SHAP_FEATURES = 5


@dataclass
class RingClassifier:
    """The loaded, ready-to-score Tier 1 model: the base XGBoost estimator (used
    directly by the SHAP TreeExplainer, which needs real tree structure, not a
    calibration wrapper around it), the isotonic calibrator that turns its raw
    score into an actual probability, and the metadata that names which features
    go in which order and what threshold separates FLAG from everything else."""

    base_model: xgb.XGBClassifier
    calibrated_model: object
    explainer: shap.TreeExplainer
    model_version: str
    flag_threshold: float
    review_threshold: float


# Loads every artifact tools/train_model.py persisted, or returns None if this checkout
# has never run training - callers must treat that as "use the rule-based fallback",
# not as an error, since a fresh clone legitimately has no model yet.
def load() -> RingClassifier | None:
    metadata_path = MODELS_DIR / "model_metadata.json"
    if not metadata_path.exists():
        return None

    metadata = json.loads(metadata_path.read_text())
    base_model = xgb.XGBClassifier()
    base_model.load_model(MODELS_DIR / "ring_classifier.json")
    calibrated_model = joblib.load(MODELS_DIR / "calibrator.joblib")
    explainer = shap.TreeExplainer(base_model)

    return RingClassifier(
        base_model=base_model, calibrated_model=calibrated_model, explainer=explainer,
        model_version=metadata["model_version"], flag_threshold=metadata["flag_threshold"],
        review_threshold=metadata["review_threshold"],
    )


@dataclass
class FeatureContribution:
    """One feature's SHAP attribution for one claim's prediction - the real
    feature_value it had, and the signed shap_value that pushed the score up
    or down because of it."""

    feature: str
    feature_value: float
    shap_value: float


# Scores one claim: extracts its feature row, runs the calibrated model, and returns the
# real SHAP attributions for those exact feature values (not a cached/precomputed table -
# SHAP's TreeExplainer is fast enough, ~milliseconds, to run per request). Returns None
# for a claim with no entity links, same contract as app.explain.build_score for a claim
# outside the graph.
def score_claim(classifier: RingClassifier, ctx: FeatureContext,
                 claim_id: str) -> tuple[float, list[FeatureContribution]] | None:
    features = extract_features(ctx, claim_id)
    if features is None:
        return None

    row = np.array([[features[name] for name in ALL_FEATURES]])
    probability = float(classifier.calibrated_model.predict_proba(row)[0, 1])

    shap_values = classifier.explainer.shap_values(row)[0]
    ranked = sorted(zip(ALL_FEATURES, shap_values), key=lambda t: -abs(t[1]))[:MAX_SHAP_FEATURES]
    contributions = [FeatureContribution(feature=name, feature_value=features[name], shap_value=float(value))
                      for name, value in ranked]

    return probability, contributions

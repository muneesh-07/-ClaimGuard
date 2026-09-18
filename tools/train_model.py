#!/usr/bin/env python3
"""
Tier 1 of the AI upgrade: trains a real, calibrated, learned ring-fraud
classifier and reports an honest ablation against the Tier 0 baselines,
instead of the M6 detector's hardcoded fraud_score=0.9 / 0.85*ratio+0.15*burst.

Follows GADBench's empirically-best architecture for this task (arXiv:2306.12251:
tree ensembles over aggregated graph features beat every GNN benchmarked,
including ones purpose-built for fraud) rather than reaching for a GNN because
it's the fashionable choice - see docs/scoring-contract.md for why.

Reports four things, all measured on a TEMPORAL split (train/val/test by
incident_date, see tools/gen_rings.py's split_day_offsets - a random split
would leak future ring members into training, which is not how fraud
actually arrives):

  1. An ablation table: tabular-only -> +graph features -> +calibration,
     AUPRC / precision@k / recall@k / confusion matrix, on the test split.
  2. The ring-injection experiment: recall specifically on the held-out
     rings (tools/gen_rings.py --held-out-rings) that were built entirely
     within the test period and never existed in train/val at all - the
     closest thing this project has to "an unseen fraud ring arrives",
     mirroring the ablation in arXiv:2607.19266.
  3. A SHAP sanity check on a handful of real predictions.
  4. Persisted artifacts (scoring/models/) the live service loads at
     startup - see app/scoring.py.

Temporal leak, found and fixed: an earlier version of this file built ONE
graph over every claim (train, val, and test periods all at once) and only
split the resulting FEATURE ROWS by date afterward - so a train-period
claim's graph-derived features (component_size, leiden_community_size,
ppr_score, two_hop_claim_count, ...) were computed from a graph that
already contained that claim's own future ring-mates, who in reality
hadn't been filed yet. That's not how fraud arrives, and it's exactly the
kind of leak temporal splitting is supposed to prevent - the split was
right, the FEATURES computed for it weren't. build_dataset() now builds
THREE graphs via app.graph.build_graph's `as_of` parameter (one frozen at
the train/val boundary, one at the val/test boundary, one unrestricted for
test) and takes each split's rows from its own as-of graph, never a later
one. The ablation numbers in scoring/models/eval_report.json are from
AFTER this fix; see the git history for the inflated numbers this
replaced, and don't trust any number measured before it.

Run with: cd scoring && uv run python ../tools/train_model.py
"""

import csv
import json
import sys
import time
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import shap
import xgboost as xgb
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator
from sklearn.metrics import average_precision_score, confusion_matrix, f1_score

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scoring"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import gen_rings  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.features import ALL_FEATURES, GRAPH_FEATURES, TABULAR_FEATURES, extract_features_bulk  # noqa: E402
from app.graph import build_graph  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MODELS_DIR = Path(__file__).resolve().parent.parent / "scoring" / "models"
MODEL_VERSION = "xgboost-ring-classifier-1.1.0"  # 1.1.0: fixed the temporal graph leak, see module docstring
OPERATING_K_VALUES = (50, 100, 500)


# Loads claim_id -> ring_id for every genuine ring member (same shape tools/eval.py uses).
def load_ground_truth(path: Path) -> dict[str, str]:
    with path.open() as f:
        return {row["claim_id"]: row["ring_id"] for row in csv.DictReader(f)}


# Loads the set of ring ids deliberately built entirely within the test period
# (tools/gen_rings.py's --held-out-rings), for the ring-injection ablation.
def load_held_out_ring_ids(path: Path) -> set[str]:
    with path.open() as f:
        return {row["ring_id"] for row in csv.DictReader(f)}


# Builds the full feature+label dataset: one row per claim, ALL_FEATURES as columns,
# plus incident_date (for the temporal split) and label (1 if a genuine ring member).
# Reads each split's rows from ITS OWN as-of graph (see module docstring) - train rows
# from g_train, val rows from g_val filtered down to the val-only period (g_val also
# contains the train period, needed to compute val claims' 2-hop/community features
# correctly, but its recomputed train-period rows are discarded - g_train's version of
# them is authoritative), and test rows from g_full filtered to the test-only period.
# This nesting relies on one fact: a claim's OWN entity links never depend on `as_of`,
# only on its own incident_date, so g_train's claim set is always exactly a subset of
# g_val's, which is always exactly a subset of g_full's - a claim can only ever be
# picked up once, by the first (earliest-cutoff) graph its own date qualifies it for.
def build_dataset(ground_truth: dict[str, str]) -> tuple[pd.DataFrame, dict]:
    train_end_day, val_end_day = gen_rings.split_day_offsets()
    train_end_date = gen_rings.EPOCH + timedelta(days=train_end_day)
    val_end_date = gen_rings.EPOCH + timedelta(days=val_end_day)

    session = SessionLocal()
    try:
        t0 = time.perf_counter()
        g_train = build_graph(session, as_of=train_end_date)
        g_val = build_graph(session, as_of=val_end_date)
        g_full = build_graph(session)
        print(f"Graphs built in {time.perf_counter() - t0:.2f}s - "
              f"train {g_train.vcount():,}v/{g_train.ecount():,}e, "
              f"val {g_val.vcount():,}v/{g_val.ecount():,}e, "
              f"full {g_full.vcount():,}v/{g_full.ecount():,}e")

        t0 = time.perf_counter()
        train_rows = extract_features_bulk(g_train)
        val_rows = {cid: feats for cid, feats in extract_features_bulk(g_val).items()
                    if cid not in train_rows}
        test_rows = {cid: feats for cid, feats in extract_features_bulk(g_full).items()
                     if cid not in train_rows and cid not in val_rows}
        feature_rows = {**train_rows, **val_rows, **test_rows}
        print(f"Features extracted in {time.perf_counter() - t0:.2f}s - "
              f"{len(train_rows):,} train / {len(val_rows):,} val / {len(test_rows):,} test "
              f"({len(feature_rows):,} total)")

        incident_dates = {}
        for v in g_full.vs:
            if v["kind"] == "claim":
                d = v["incident_date"]
                incident_dates[v["name"]] = d.isoformat() if hasattr(d, "isoformat") else d
    finally:
        session.close()

    df = pd.DataFrame.from_dict(feature_rows, orient="index", columns=ALL_FEATURES)
    df["label"] = [1 if claim_id in ground_truth else 0 for claim_id in df.index]
    return df, incident_dates


# Splits claim ids into train/val/test by incident_date, using the SAME day-offset
# boundaries tools/gen_rings.py used to place held-out rings - the one shared
# definition, so the split the model trains on and the split the generator built
# held-out rings against can never quietly disagree (same reasoning as detector.py's
# FLAG_AT/REVIEW_AT or CanonicalJson elsewhere in this project).
def temporal_split(df: pd.DataFrame, incident_dates: dict) -> tuple[pd.Index, pd.Index, pd.Index]:
    train_end_day, val_end_day = gen_rings.split_day_offsets()
    train_end_date = (gen_rings.EPOCH + timedelta(days=train_end_day)).isoformat()
    val_end_date = (gen_rings.EPOCH + timedelta(days=val_end_day)).isoformat()

    dates = pd.Series({cid: incident_dates.get(cid) for cid in df.index})
    train_ids = dates[dates <= train_end_date].index
    val_ids = dates[(dates > train_end_date) & (dates <= val_end_date)].index
    test_ids = dates[dates > val_end_date].index
    return train_ids, val_ids, test_ids


# Trains one XGBoost variant on the given feature columns, weighting the positive class
# by the train split's actual imbalance ratio (the base rate is ~2%, so an unweighted fit
# would just predict "not fraud" for everything and still score >97% accuracy).
def train_variant(X_train: pd.DataFrame, y_train: pd.Series) -> xgb.XGBClassifier:
    pos = int(y_train.sum())
    neg = len(y_train) - pos
    scale_pos_weight = neg / pos if pos > 0 else 1.0
    model = xgb.XGBClassifier(
        n_estimators=300, max_depth=5, learning_rate=0.1,
        scale_pos_weight=scale_pos_weight, eval_metric="aucpr",
        random_state=42,
    )
    model.fit(X_train, y_train)
    return model


# Precision/recall at a rank cutoff k: of the top-k claims by predicted score, what
# fraction are true ring members (precision), and what fraction of ALL true ring
# members in this split are captured within the top k (recall).
def precision_recall_at_k(y_true: np.ndarray, scores: np.ndarray, k: int) -> tuple[float, float]:
    order = np.argsort(-scores)[:k]
    hits = y_true[order].sum()
    total_positive = y_true.sum()
    precision = hits / k if k > 0 else 0.0
    recall = hits / total_positive if total_positive > 0 else 0.0
    return float(precision), float(recall)


# Picks the score threshold that maximizes F1 on the validation split - the confusion
# matrix reported for a variant is at ITS OWN threshold, not one borrowed from another
# variant's calibration, so variants stay comparable on equal footing. This becomes the
# model's FLAG boundary: the balanced point for automatic action.
def best_threshold(y_val: np.ndarray, scores_val: np.ndarray) -> float:
    candidates = np.linspace(0.01, 0.99, 99)
    f1s = [f1_score(y_val, scores_val >= t, zero_division=0) for t in candidates]
    return float(candidates[int(np.argmax(f1s))])


# Picks the LOWEST threshold that still reaches target_recall on the validation split -
# this becomes the model's REVIEW boundary. Unlike the F1-optimal FLAG threshold (balanced
# precision/recall, meant for automatic action), REVIEW is meant to catch nearly everything
# worth a human's attention, erring toward over-flagging rather than under-flagging - the
# same reasoning FLAG_AT/REVIEW_AT split served for the old rule-based scores, just derived
# from the calibrated model's own validation performance instead of two hand-picked constants.
def review_threshold(y_val: np.ndarray, scores_val: np.ndarray, target_recall: float = 0.95) -> float:
    candidates = np.linspace(0.99, 0.01, 99)
    for t in candidates:
        preds = scores_val >= t
        recall = preds[y_val == 1].mean() if (y_val == 1).any() else 0.0
        if recall >= target_recall:
            return float(t)
    return 0.01


# Full evaluation of one variant's predictions on the test split: AUPRC, precision@k/
# recall@k at a few cutoffs, and a confusion matrix at the F1-optimal threshold (chosen
# on the VALIDATION split, never the test split itself).
def evaluate(name: str, y_val: np.ndarray, scores_val: np.ndarray,
             y_test: np.ndarray, scores_test: np.ndarray) -> dict:
    auprc = average_precision_score(y_test, scores_test)
    flag_t = best_threshold(y_val, scores_val)
    review_t = review_threshold(y_val, scores_val)
    preds = (scores_test >= flag_t).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_test, preds, labels=[0, 1]).ravel()

    at_k = {}
    for k in OPERATING_K_VALUES:
        p, r = precision_recall_at_k(y_test, scores_test, min(k, len(scores_test)))
        at_k[k] = {"precision": round(p, 4), "recall": round(r, 4)}

    result = {
        "auprc": round(float(auprc), 4),
        "flag_threshold": round(flag_t, 3),
        "review_threshold": round(review_t, 3),
        "confusion_matrix": {"tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn)},
        "precision_recall_at_k": at_k,
    }
    print(f"\n--- {name} ---")
    print(f"  AUPRC: {result['auprc']}   flag_threshold: {result['flag_threshold']}   "
          f"review_threshold: {result['review_threshold']}   confusion: {result['confusion_matrix']}")
    for k, v in at_k.items():
        print(f"  @{k:>4}: precision={v['precision']}  recall={v['recall']}")
    return result


# The headline experiment: among claims belonging to a held-out ring (built entirely
# within the test period, per tools/gen_rings.py --held-out-rings - the model has never
# seen any part of these rings during training), what fraction score above the operating
# threshold? Reported for the tabular-only and full-graph variants side by side, mirroring
# arXiv:2607.19266's fraud-ring injection ablation.
def ring_injection_ablation(df: pd.DataFrame, test_ids: pd.Index, ground_truth: dict[str, str],
                             held_out_ring_ids: set[str], variants: dict) -> dict:
    held_out_claim_ids = [cid for cid in test_ids
                           if ground_truth.get(cid) in held_out_ring_ids]
    if not held_out_claim_ids:
        return {"held_out_claims": 0, "note": "no held-out ring claims fell in the test split"}

    result = {"held_out_claims": len(held_out_claim_ids),
              "held_out_rings": len({ground_truth[c] for c in held_out_claim_ids})}
    for variant_name, (model, feature_cols, threshold) in variants.items():
        X = df.loc[held_out_claim_ids, feature_cols]
        scores = model.predict_proba(X)[:, 1]
        recall = float((scores >= threshold).mean())
        result[variant_name] = {"recall_at_own_threshold": round(recall, 4),
                                 "mean_score": round(float(scores.mean()), 4)}
    print("\n--- Ring-injection ablation (held-out rings, never seen in train/val) ---")
    print(f"  {result['held_out_claims']} claims across {result['held_out_rings']} held-out rings")
    for variant_name in variants:
        v = result[variant_name]
        print(f"  {variant_name:>16}: recall={v['recall_at_own_threshold']}  "
              f"mean_score={v['mean_score']}")
    return result


# Sanity-checks that SHAP explanations are actually usable: computes real attributions
# for a handful of test-split claims and prints the top contributing feature for each,
# so a silent SHAP misconfiguration (wrong feature order, wrong explainer type) is caught
# here rather than discovered later in a live scoring response.
def shap_sanity_check(model: xgb.XGBClassifier, X_test: pd.DataFrame, y_test: pd.Series) -> None:
    positive_examples = X_test[y_test == 1].head(3)
    if positive_examples.empty:
        print("\nNo positive test examples to SHAP-check against.")
        return
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(positive_examples)
    print("\n--- SHAP sanity check (3 real fraud-labelled test claims) ---")
    for i, claim_id in enumerate(positive_examples.index):
        contributions = sorted(zip(ALL_FEATURES, shap_values[i]), key=lambda t: -abs(t[1]))[:3]
        top = ", ".join(f"{name}={value:+.3f}" for name, value in contributions)
        print(f"  {claim_id}: top features -> {top}")


# Persists the final model, its calibrator, feature list, and the full eval report to
# scoring/models/ - what app/scoring.py loads at startup instead of the hardcoded rungs,
# and what a new backend endpoint can serve to the frontend for the "Model & Evaluation" view.
def persist_artifacts(model: xgb.XGBClassifier, calibrated_model: CalibratedClassifierCV,
                       flag_t: float, review_t: float, report: dict) -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model.save_model(MODELS_DIR / "ring_classifier.json")

    import joblib
    joblib.dump(calibrated_model, MODELS_DIR / "calibrator.joblib")

    metadata = {
        "model_version": MODEL_VERSION,
        "trained_at": pd.Timestamp.now("UTC").isoformat(),
        "features": ALL_FEATURES,
        "tabular_features": TABULAR_FEATURES,
        "graph_features": GRAPH_FEATURES,
        "flag_threshold": flag_t,
        "review_threshold": review_t,
    }
    (MODELS_DIR / "model_metadata.json").write_text(json.dumps(metadata, indent=2))
    (MODELS_DIR / "eval_report.json").write_text(json.dumps(report, indent=2))
    print(f"\nArtifacts written to {MODELS_DIR}/")


def main() -> None:
    ground_truth = load_ground_truth(DATA_DIR / "ground_truth_rings.csv")
    held_out_ring_ids = load_held_out_ring_ids(DATA_DIR / "held_out_rings.csv")

    df, incident_dates = build_dataset(ground_truth)
    train_ids, val_ids, test_ids = temporal_split(df, incident_dates)
    print(f"\nTemporal split: train={len(train_ids):,}  val={len(val_ids):,}  test={len(test_ids):,}")
    print(f"Positive rate - train={df.loc[train_ids, 'label'].mean():.4%}  "
          f"val={df.loc[val_ids, 'label'].mean():.4%}  test={df.loc[test_ids, 'label'].mean():.4%}")

    y_train, y_val, y_test = df.loc[train_ids, "label"], df.loc[val_ids, "label"], df.loc[test_ids, "label"]

    report = {"model_version": MODEL_VERSION, "ablation": {}}
    variants_for_ablation = {}

    # Ablation stage 1: tabular-only (no entity-sharing information at all).
    tabular_model = train_variant(df.loc[train_ids, TABULAR_FEATURES], y_train)
    scores_val = tabular_model.predict_proba(df.loc[val_ids, TABULAR_FEATURES])[:, 1]
    scores_test = tabular_model.predict_proba(df.loc[test_ids, TABULAR_FEATURES])[:, 1]
    report["ablation"]["tabular_only"] = evaluate(
        "Tabular-only XGBoost (no graph)", y_val.values, scores_val, y_test.values, scores_test)
    variants_for_ablation["tabular_only"] = (
        tabular_model, TABULAR_FEATURES, report["ablation"]["tabular_only"]["flag_threshold"])

    # Ablation stage 2: + graph-derived features (the M6 rungs, as features not verdicts).
    graph_model = train_variant(df.loc[train_ids, ALL_FEATURES], y_train)
    scores_val = graph_model.predict_proba(df.loc[val_ids, ALL_FEATURES])[:, 1]
    scores_test = graph_model.predict_proba(df.loc[test_ids, ALL_FEATURES])[:, 1]
    report["ablation"]["plus_graph_features"] = evaluate(
        "+ Graph features (k-core, Leiden, PPR, 2-hop aggregation)",
        y_val.values, scores_val, y_test.values, scores_test)
    variants_for_ablation["plus_graph_features"] = (
        graph_model, ALL_FEATURES, report["ablation"]["plus_graph_features"]["flag_threshold"])

    # Ablation stage 3: + isotonic calibration on top of the full-graph model, fit on the
    # VALIDATION split (never train, never test) via sklearn's FrozenEstimator - the
    # modern replacement for the now-removed CalibratedClassifierCV(cv="prefit").
    calibrated_model = CalibratedClassifierCV(FrozenEstimator(graph_model), method="isotonic")
    calibrated_model.fit(df.loc[val_ids, ALL_FEATURES], y_val)
    scores_val_cal = calibrated_model.predict_proba(df.loc[val_ids, ALL_FEATURES])[:, 1]
    scores_test_cal = calibrated_model.predict_proba(df.loc[test_ids, ALL_FEATURES])[:, 1]
    report["ablation"]["plus_calibration"] = evaluate(
        "+ Isotonic calibration", y_val.values, scores_val_cal, y_test.values, scores_test_cal)
    final_flag_threshold = report["ablation"]["plus_calibration"]["flag_threshold"]
    final_review_threshold = report["ablation"]["plus_calibration"]["review_threshold"]

    report["ring_injection_ablation"] = ring_injection_ablation(
        df, test_ids, ground_truth, held_out_ring_ids, variants_for_ablation)

    shap_sanity_check(graph_model, df.loc[test_ids, ALL_FEATURES], y_test)

    persist_artifacts(graph_model, calibrated_model, final_flag_threshold, final_review_threshold, report)


if __name__ == "__main__":
    main()

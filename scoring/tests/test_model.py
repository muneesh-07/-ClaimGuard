import uuid
from datetime import date, timedelta

import pytest

from app.explain import build_model_score
from app.features import build_feature_context
from app.model import MODELS_DIR, load, score_claim
from tests.graph_helpers import make_bipartite_graph

# These tests need a real trained model (tools/train_model.py's output) on disk. A fresh
# checkout that hasn't run `make train-model` yet legitimately has none - app.scoring falls
# back to the rule-based detector in that case (see app/scoring.py) - so these tests skip
# rather than fail, the same way the rest of this suite would if Postgres weren't running.
requires_trained_model = pytest.mark.skipif(
    not (MODELS_DIR / "model_metadata.json").exists(),
    reason="no trained model at scoring/models/ - run `make train-model` first",
)


def _ring_graph():
    # build_model_score()/build_score() construct real ClaimScores (claim_id: UUID), so
    # the graph's claim vertex names must be actual UUID strings, same reasoning as
    # test_explain.py's test_build_score_explains_a_ring_member_with_its_shared_entity.
    ring_claim_ids = sorted(str(uuid.uuid4()) for _ in range(5))
    base_date = date(2026, 1, 1)
    dates = {c: base_date + timedelta(days=i) for i, c in enumerate(ring_claim_ids)}
    amounts = {c: 50000.0 for c in ring_claim_ids}
    edges = [(c, "phone-ring") for c in ring_claim_ids]
    g = make_bipartite_graph(edges, dates=dates, amounts=amounts,
                              entity_types={"phone-ring": "PHONE"})
    return g, ring_claim_ids


@requires_trained_model
def test_load_returns_a_usable_classifier():
    classifier = load()

    assert classifier is not None
    assert classifier.model_version
    assert 0.0 <= classifier.flag_threshold <= 1.0
    assert 0.0 <= classifier.review_threshold <= classifier.flag_threshold


@requires_trained_model
def test_score_claim_returns_a_probability_and_ranked_shap_contributions():
    g, ring_claim_ids = _ring_graph()
    ctx = build_feature_context(g)
    classifier = load()

    result = score_claim(classifier, ctx, ring_claim_ids[0])

    assert result is not None
    probability, contributions = result
    assert 0.0 <= probability <= 1.0
    assert len(contributions) > 0
    # Ranked by |shap_value| descending - the first contribution must be at least as
    # influential as the last, not just "some list of features in feature order."
    magnitudes = [abs(c.shap_value) for c in contributions]
    assert magnitudes == sorted(magnitudes, reverse=True)


@requires_trained_model
def test_score_claim_returns_none_for_a_claim_outside_the_graph():
    g, _ring_claim_ids = _ring_graph()
    ctx = build_feature_context(g)
    classifier = load()

    assert score_claim(classifier, ctx, str(uuid.uuid4())) is None


@requires_trained_model
def test_build_model_score_produces_feature_contribution_evidence():
    g, ring_claim_ids = _ring_graph()
    ctx = build_feature_context(g)
    classifier = load()

    score = build_model_score(g, ctx, classifier, ring_claim_ids[0])

    assert score is not None
    assert score.model_version == classifier.model_version
    assert score.rung == "xgboost"
    feature_evidence = [e for e in score.explanation.evidence if e.type == "FEATURE_CONTRIBUTION"]
    assert len(feature_evidence) > 0
    # decision_hint must be internally consistent with the score's own reported
    # thresholds, not the rule-based detector's unrelated FLAG_AT/REVIEW_AT constants.
    thresholds = score.explanation.thresholds
    if score.decision_hint == "FLAG":
        assert score.fraud_score >= thresholds.flag_at
    elif score.decision_hint == "REVIEW":
        assert thresholds.review_at <= score.fraud_score < thresholds.flag_at
    else:
        assert score.fraud_score < thresholds.review_at

"""
Tests app/narrative.py's grounding logic directly - deliberately without a
real Ollama call, so this suite passes on a fresh checkout with no local
LLM pulled at all (the same reasoning test_model.py skips its tests
without a trained model, just enforced by mocking here instead of
skipping, since app.narrative always has a safe fallback to exercise).
The one thing these tests must prove beyond doubt: a narrative that
mentions a claim id outside its own evidence is NEVER what a caller gets
back - that guarantee is the entire point of this module.
"""

import uuid
from unittest.mock import patch

import httpx

from app.models import (
    ClaimScore,
    Explanation,
    FeatureContributionEvidence,
    SharedEntityEvidence,
    Thresholds,
    now_utc,
)
from app.narrative import _allowed_claim_ids, _is_grounded, generate_narrative


def _make_score(claim_id=None, other_ids=()):
    claim_id = claim_id or uuid.uuid4()
    return ClaimScore(
        claim_id=claim_id,
        model_version="xgboost-ring-classifier-1.0.0",
        scored_at=now_utc(),
        fraud_score=0.9,
        decision_hint="FLAG",
        ring_id="leiden-1",
        rung="xgboost",
        explanation=Explanation(
            summary="Part of a flagged cluster.",
            evidence=[
                SharedEntityEvidence(
                    entity_type="PHONE", entity_value="+9*****71",
                    entity_degree=len(other_ids) + 1, shared_with_claim_ids=list(other_ids),
                ),
                FeatureContributionEvidence(
                    feature="claimants_per_entity_1hop", feature_value=4.0, shap_value=0.8,
                ),
            ],
            thresholds=Thresholds(flag_at=0.26, review_at=0.01),
        ),
    )


def test_allowed_claim_ids_includes_the_claim_itself_and_every_shared_neighbor():
    claim_id = uuid.uuid4()
    other1, other2 = uuid.uuid4(), uuid.uuid4()
    score = _make_score(claim_id, [other1, other2])

    allowed = _allowed_claim_ids(score)

    assert allowed == {str(claim_id), str(other1), str(other2)}


def test_is_grounded_accepts_text_that_only_mentions_allowed_ids():
    other = uuid.uuid4()
    text = f"This claim shares a phone number with claim {other}, matching the ring."

    assert _is_grounded(text, {str(other)}) is True


def test_is_grounded_rejects_text_that_mentions_an_invented_claim_id():
    invented = uuid.uuid4()
    text = f"This claim is also connected to claim {invented}, which looks suspicious."

    assert _is_grounded(text, {str(uuid.uuid4())}) is False
    # Sanity check the fixture itself actually contains what the assertion is testing for.
    assert str(invented) in text


def test_is_grounded_rejects_empty_text():
    assert _is_grounded("", {str(uuid.uuid4())}) is False


def test_generate_narrative_uses_the_models_text_when_it_is_grounded():
    other = uuid.uuid4()
    score = _make_score(other_ids=[other])
    fake_response = httpx.Response(
        200, json={"message": {"content": f'{{"narrative": "Shares a phone with claim {other}."}}'}},
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )

    with patch("app.narrative.httpx.post", return_value=fake_response):
        result = generate_narrative(score)

    assert result.grounded is True
    assert result.model_version.startswith("ollama:")
    assert str(other) in result.text


def test_generate_narrative_falls_back_when_the_model_invents_a_claim_id():
    real_other = uuid.uuid4()
    invented = uuid.uuid4()
    score = _make_score(other_ids=[real_other])
    fake_response = httpx.Response(
        200, json={"message": {"content": f'{{"narrative": "Also connects to claim {invented}."}}'}},
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )

    with patch("app.narrative.httpx.post", return_value=fake_response):
        result = generate_narrative(score)

    # An ungrounded model output must never reach the caller - the fallback is the
    # deterministic template summary computed straight from this claim's own evidence.
    assert result.model_version == "template-fallback"
    assert result.text == score.explanation.summary
    assert str(invented) not in result.text


def test_generate_narrative_falls_back_when_ollama_is_unreachable():
    score = _make_score()

    with patch("app.narrative.httpx.post", side_effect=httpx.ConnectError("connection refused")):
        result = generate_narrative(score)

    assert result.model_version == "template-fallback"
    assert result.text == score.explanation.summary
    assert result.grounded is True

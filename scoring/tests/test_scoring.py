import uuid

from app.scoring import score_claims


def test_score_claims_flags_a_real_planted_ring(refreshed_scoring_cache, scoring_session):
    ring_claim_ids = refreshed_scoring_cache

    results = score_claims(scoring_session, ring_claim_ids)

    assert len(results) == 3
    for result in results:
        assert result.decision_hint == "FLAG"
        # Whichever scoring method produced this (rule-based rungs or the Tier 1 trained
        # model), a FLAG decision must be internally consistent with the flag_at threshold
        # the SAME result reports - not a specific score, which is method-dependent.
        assert result.fraud_score >= result.explanation.thresholds.flag_at
        assert result.model_version
    # all three should have landed in the same detected community
    assert len({r.ring_id for r in results}) == 1


def test_score_claims_skips_ids_that_were_never_scored(refreshed_scoring_cache, scoring_session):
    results = score_claims(scoring_session, [uuid.uuid4()])

    assert results == []

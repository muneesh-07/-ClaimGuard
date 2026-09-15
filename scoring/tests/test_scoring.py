from app.scoring import mask_entity_value, score_claim


def test_two_claims_sharing_an_entity_are_each_others_evidence(scoring_session, two_linked_claims):
    claim_a, claim_b = two_linked_claims

    result = score_claim(scoring_session, claim_a)

    assert result is not None
    assert result.claim_id == claim_a
    assert result.model_version == "stub-component-size-0.1.0"
    assert result.rung == "stub"
    assert result.ring_id is None

    shared_entity_evidence = [e for e in result.explanation.evidence if e.type == "SHARED_ENTITY"]
    assert len(shared_entity_evidence) == 1
    assert shared_entity_evidence[0].shared_with_claim_ids == [claim_b]
    assert shared_entity_evidence[0].entity_degree == 2


def test_a_claim_with_no_entities_returns_none(scoring_session, unlinked_claim):
    result = score_claim(scoring_session, unlinked_claim)

    assert result is None


def test_entity_values_are_masked_not_shown_raw(scoring_session, two_linked_claims):
    claim_a, _ = two_linked_claims

    result = score_claim(scoring_session, claim_a)

    shared_entity_evidence = [e for e in result.explanation.evidence if e.type == "SHARED_ENTITY"][0]
    assert shared_entity_evidence.entity_value != shared_entity_evidence.entity_value.replace("*", "")
    assert "*" in shared_entity_evidence.entity_value


def test_mask_entity_value_keeps_only_the_edges():
    assert mask_entity_value("+919876500011") == "+9*********11"
    assert mask_entity_value("ab") == "**"

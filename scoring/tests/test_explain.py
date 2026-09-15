import uuid

from app.detector import detect
from app.explain import build_score, mask_entity_value
from tests.graph_helpers import make_bipartite_graph


def test_mask_entity_value_keeps_only_the_edges():
    assert mask_entity_value("+919876500011") == "+9*********11"
    assert mask_entity_value("ab") == "**"


def test_build_score_explains_a_ring_member_with_its_shared_entity():
    # build_score() constructs a real ClaimScore (claim_id: UUID), so the graph's claim
    # vertex names must be actual UUID strings here, unlike the readable "claim-0" style
    # names used in test_detector.py, which never reach a UUID-typed Pydantic field.
    ring_claim_ids = [str(uuid.uuid4()) for _ in range(5)]
    ring_edges = [(claim_id, "phone-ring") for claim_id in ring_claim_ids]
    g = make_bipartite_graph(ring_edges, entity_types={"phone-ring": "PHONE"})
    name_to_index = {v["name"]: v.index for v in g.vs if v["kind"] == "claim"}
    verdicts = detect(g, min_ring_size=3)

    score = build_score(g, name_to_index, verdicts, ring_claim_ids[0], "test-model-0.0.1")

    assert score is not None
    assert str(score.claim_id) == ring_claim_ids[0]
    assert score.model_version == "test-model-0.0.1"
    assert score.decision_hint == "FLAG"
    assert score.ring_id is not None

    shared_entity_evidence = [e for e in score.explanation.evidence if e.type == "SHARED_ENTITY"]
    assert len(shared_entity_evidence) == 1
    assert shared_entity_evidence[0].entity_type == "PHONE"
    assert "*" in shared_entity_evidence[0].entity_value
    assert len(shared_entity_evidence[0].shared_with_claim_ids) == 4


def test_build_score_returns_none_for_an_unknown_claim():
    claim_a, claim_b = str(uuid.uuid4()), str(uuid.uuid4())
    g = make_bipartite_graph([(claim_a, "phone-a"), (claim_b, "phone-a")])
    name_to_index = {v["name"]: v.index for v in g.vs if v["kind"] == "claim"}
    verdicts = detect(g)

    assert build_score(g, name_to_index, verdicts, str(uuid.uuid4()), "test-model") is None

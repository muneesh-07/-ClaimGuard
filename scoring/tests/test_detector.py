from datetime import date

from app.detector import (
    _burstiness,
    _claimants_per_entity_ratio,
    _suspiciousness,
    detect,
    rung1_components,
)
from app.graph import idf_weight
from tests.graph_helpers import make_bipartite_graph as _bipartite_graph


def test_idf_weight_favors_rare_entities_over_common_ones():
    rare = idf_weight(3)
    common = idf_weight(1000)

    assert rare > common
    assert 0 < common < rare


def test_claimants_per_entity_ratio_is_high_for_a_ring_shape():
    ring_ratio = _claimants_per_entity_ratio(claim_count=12, entity_count=1)
    ordinary_ratio = _claimants_per_entity_ratio(claim_count=2, entity_count=2)

    assert ring_ratio == 12.0
    assert ordinary_ratio == 1.0
    assert ring_ratio > ordinary_ratio


def test_burstiness_is_high_when_claims_cluster_in_time():
    clustered = [date(2026, 1, 1), date(2026, 1, 3), date(2026, 1, 5)]
    spread_out = [date(2026, 1, 1), date(2026, 4, 1), date(2026, 8, 1)]

    assert _burstiness(clustered) == 1.0
    assert _burstiness(spread_out) < _burstiness(clustered)


def test_suspiciousness_combines_ratio_and_burstiness_with_ratio_dominant():
    ring_like = _suspiciousness(claimants_per_entity=5.0, burstiness=1.0)
    ordinary = _suspiciousness(claimants_per_entity=1.0, burstiness=0.0)

    assert ring_like > 0.9
    assert ordinary == 0.0


def test_rung1_finds_a_tight_ring_but_not_isolated_pairs():
    edges = [(f"claim-{i}", "phone-ring") for i in range(5)]  # 5 claims, 1 low-degree entity
    edges += [("claim-x", "shop-a"), ("claim-y", "shop-a")]  # an unrelated pair, too small to count
    g = _bipartite_graph(edges, entity_types={"phone-ring": "PHONE", "shop-a": "SHOP"})

    result = rung1_components(g, min_ring_size=3)  # uses the real per-type default thresholds

    assert all(result[f"claim-{i}"] == result["claim-0"] for i in range(5))
    assert "claim-x" not in result
    assert "claim-y" not in result


def test_detect_flags_a_planted_ring_and_clears_ordinary_claims():
    # A real ring: 6 claims, one low-degree shared phone, nothing else.
    ring_edges = [(f"claim-{i}", "phone-ring") for i in range(6)]

    # Ordinary background claims: each has its OWN unique phone (so it isn't an
    # isolated singleton in the graph) and ALSO happens to use a common, busy shop -
    # exactly the "many unrelated claimants, one popular shop" shape from the real
    # generator (tools/gen_rings.py) that a naive detector mistakes for a ring. Scaled to
    # 60 noise claims so shop-common's degree (61) clears the real SHOP prune threshold
    # (50) the same way a real repair shop does in production, not an arbitrary test-only number.
    noise_edges = []
    for i in range(60):
        noise_edges.append((f"claim-noise-{i}", f"phone-noise-{i}"))
        noise_edges.append((f"claim-noise-{i}", "shop-common"))
    lone_edges = [("claim-lone", "phone-lone"), ("claim-lone", "shop-common")]

    g = _bipartite_graph(
        ring_edges + lone_edges + noise_edges,
        entity_types={"phone-ring": "PHONE", "shop-common": "SHOP",
                      **{f"phone-noise-{i}": "PHONE" for i in range(60)}, "phone-lone": "PHONE"},
    )

    # phone-ring's degree is 6, well below the real PHONE threshold (50); shop-common's
    # degree is 61 (60 noise + 1 lone), above the real SHOP threshold (50) - both prune
    # exactly the way they would on the real dataset, using the real default thresholds.
    verdicts = detect(g, min_ring_size=3)

    ring_scores = [verdicts[f"claim-{i}"].fraud_score for i in range(6)]
    assert all(score >= 0.75 for score in ring_scores)
    assert len({verdicts[f"claim-{i}"].ring_id for i in range(6)}) == 1

    assert verdicts["claim-lone"].fraud_score < 0.75
    assert all(verdicts[f"claim-noise-{i}"].fraud_score < 0.75 for i in range(60))

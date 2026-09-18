"""
Turns the bipartite claim<->entity graph into a flat feature row per claim,
for the Tier 1 learned model (tools/train_model.py). This is deliberately
NOT a second implementation of the graph analytics - every graph-derived
feature here is computed from the same primitives app.detector already
uses (idf_weight, claimants-per-entity ratio, burstiness, k-core
components, Leiden communities, personalized PageRank), so the M6 rungs
are not thrown away, they become this model's feature extractor.

Features are split into TABULAR_FEATURES (no entity-sharing information at
all - what a single-claim scoring system would have) and GRAPH_FEATURES
(everything that requires the bipartite graph), so tools/train_model.py's
ablation table can train on either subset and report the difference
directly, instead of the difference being asserted rather than measured.

Per GADBench (arXiv:2306.12251): 2 hops of neighbour-feature aggregation
into a tree ensemble is what actually correlates with fraud-detection
performance, not a separate learned embedding on top - this file's 1-hop/
2-hop aggregate features are that aggregation step, done directly, rather
than training a node2vec embedding whose signal substantially overlaps
with degree/PPR/community features this module already computes.
"""

from dataclasses import dataclass
from datetime import date

import igraph as ig

from app.detector import (
    DEFAULT_DEGREE_THRESHOLDS,
    FALLBACK_DEGREE_THRESHOLD,
    _burstiness,
    _claimants_per_entity_ratio,
    rung1_components,
    rung2_leiden,
    rung3_ppr,
)

TABULAR_FEATURES = ["claim_amount", "day_of_week", "is_weekend"]
GRAPH_FEATURES = [
    "entity_degree_min", "entity_degree_mean", "entity_degree_max",
    "idf_weighted_degree",
    "one_hop_entity_count", "two_hop_claim_count",
    "claimants_per_entity_1hop", "claimants_per_entity_2hop",
    "burstiness_2hop",
    "component_size",
    "leiden_community_size", "leiden_suspiciousness",
    "ppr_score",
]
ALL_FEATURES = TABULAR_FEATURES + GRAPH_FEATURES


@dataclass
class FeatureContext:
    """Graph-wide computations shared across every claim's feature row - built
    once per scoring pass, not recomputed per claim (component membership,
    Leiden partition, and PPR seeds are each an O(claims) computation on
    their own; doing that once instead of once-per-claim is the difference
    between this being fast enough to run on a whole graph and not).
    name_to_index exists for the same reason: igraph's g.vs.find(name=...)
    is a linear scan with no index behind it, so calling it once per claim
    (or worse, once per 2-hop neighbour, per claim) turns a 51k-claim graph
    into an O(V^2) feature pass - this dict makes every lookup O(1) instead."""

    g: ig.Graph
    name_to_index: dict[str, int]
    component_of: dict[str, str]
    component_size: dict[str, int]
    leiden_verdicts: dict
    ppr_scores: dict[str, float]


# Builds one FeatureContext for a graph: runs rung1 (components) and rung2 (Leiden) once,
# then seeds rung3 (PPR) from whatever either rung already flagged - the same seed logic
# detect() uses, reused here so "which claims are provisional seeds" can never quietly
# differ between the rule-based detector and this feature extractor.
def build_feature_context(g: ig.Graph) -> FeatureContext:
    name_to_index = {v["name"]: v.index for v in g.vs}
    rung1 = rung1_components(g)
    component_size: dict[str, int] = {}
    for ring_id in set(rung1.values()):
        component_size[ring_id] = sum(1 for v in rung1.values() if v == ring_id)

    leiden_verdicts = rung2_leiden(g)

    seeds = {c for c in rung1} | {c for c, v in leiden_verdicts.items() if v.fraud_score >= 0.75}
    ppr_scores = rung3_ppr(g, seeds)

    return FeatureContext(g=g, name_to_index=name_to_index, component_of=rung1,
                           component_size=component_size, leiden_verdicts=leiden_verdicts,
                           ppr_scores=ppr_scores)


# The tabular-only slice of a claim's features - claim_amount plus calendar features
# derived from incident_date. Zero entity-sharing information, by construction: this is
# what tools/train_model.py's "tabular-only" ablation row trains on.
def _tabular_features(g: ig.Graph, claim_index: int) -> dict[str, float]:
    amount = g.vs[claim_index]["claim_amount"] or 0.0
    incident_date = g.vs[claim_index]["incident_date"]
    if isinstance(incident_date, str):
        incident_date = date.fromisoformat(incident_date)
    weekday = incident_date.weekday() if incident_date else 0
    return {
        "claim_amount": float(amount),
        "day_of_week": float(weekday),
        "is_weekend": float(weekday >= 5),
    }


# The graph-derived slice of a claim's features - everything that needs the bipartite
# graph to compute. A claim with no entity edges at all (shouldn't happen post entity-
# resolution, but the graph shouldn't crash if it does) gets all-zero graph features
# rather than raising, since a truly isolated claim is a legitimate, if unusual, input.
def _graph_features(ctx: FeatureContext, claim_id: str, claim_index: int) -> dict[str, float]:
    g = ctx.g
    incident_eids = g.incident(claim_index)
    entity_indices = [g.es[eid].target if g.es[eid].source == claim_index else g.es[eid].source
                       for eid in incident_eids]
    degrees = [g.vs[i]["degree_raw"] for i in entity_indices] or [0]
    weighted_degree = sum(g.es[eid]["weight"] for eid in incident_eids)

    # Walking through an entity above its type's k-core pruning threshold (a shop shared
    # by thousands of unrelated claims) contributes essentially no 2-hop signal - the IDF
    # weighting already tells the rest of this feature set that such an entity barely
    # holds anything together - but DOES contribute O(degree) work per claim that touches
    # it, so skipping it here is both more correct and what keeps this O(claims), not
    # O(claims * max_entity_degree), the same class of hazard app/local_push.py's docstring
    # names for exactly this kind of hub.
    two_hop_claims: set[str] = set()
    for entity_index in entity_indices:
        entity_type = g.vs[entity_index]["entity_type"]
        degree_raw = g.vs[entity_index]["degree_raw"] or 0
        if degree_raw > DEFAULT_DEGREE_THRESHOLDS.get(entity_type, FALLBACK_DEGREE_THRESHOLD):
            continue
        for neighbor_index in g.neighbors(entity_index):
            if g.vs[neighbor_index]["kind"] == "claim":
                two_hop_claims.add(g.vs[neighbor_index]["name"])
    two_hop_claims.discard(claim_id)

    ratio_1hop = _claimants_per_entity_ratio(1, len(entity_indices)) if entity_indices else 0.0
    ratio_2hop = _claimants_per_entity_ratio(len(two_hop_claims) + 1, len(entity_indices)) \
        if entity_indices else 0.0

    two_hop_dates = []
    for name in two_hop_claims | {claim_id}:
        idx = ctx.name_to_index[name]
        d = g.vs[idx]["incident_date"]
        if isinstance(d, str):
            d = date.fromisoformat(d)
        two_hop_dates.append(d)
    burst = _burstiness(two_hop_dates)

    component_id = ctx.component_of.get(claim_id)
    component_size = ctx.component_size.get(component_id, 1) if component_id else 1

    leiden_verdict = ctx.leiden_verdicts.get(claim_id)
    leiden_size = len(leiden_verdict.community_claim_ids) if leiden_verdict else 1
    leiden_score = leiden_verdict.fraud_score if leiden_verdict else 0.0

    return {
        "entity_degree_min": float(min(degrees)),
        "entity_degree_mean": float(sum(degrees) / len(degrees)),
        "entity_degree_max": float(max(degrees)),
        "idf_weighted_degree": float(weighted_degree),
        "one_hop_entity_count": float(len(entity_indices)),
        "two_hop_claim_count": float(len(two_hop_claims)),
        "claimants_per_entity_1hop": float(ratio_1hop),
        "claimants_per_entity_2hop": float(ratio_2hop),
        "burstiness_2hop": float(burst),
        "component_size": float(component_size),
        "leiden_community_size": float(leiden_size),
        "leiden_suspiciousness": float(leiden_score),
        "ppr_score": float(ctx.ppr_scores.get(claim_id, 0.0)),
    }


# Builds the full feature row (tabular + graph) for one claim. This is the single function
# both training (tools/train_model.py) and live scoring (app/scoring.py) call, so a feature
# can never be computed one way at training time and a subtly different way at serving time.
def extract_features(ctx: FeatureContext, claim_id: str) -> dict[str, float] | None:
    claim_index = ctx.name_to_index.get(claim_id)
    if claim_index is None or ctx.g.vs[claim_index]["kind"] != "claim":
        return None
    return {**_tabular_features(ctx.g, claim_index), **_graph_features(ctx, claim_id, claim_index)}


# Builds feature rows for every claim vertex in the graph at once - the bulk path
# training and full-graph evaluation actually use, since calling extract_features in a
# Python loop per claim is fine for one claim but is the dominant cost at 50k+ claims.
def extract_features_bulk(g: ig.Graph) -> dict[str, dict[str, float]]:
    ctx = build_feature_context(g)
    return {
        v["name"]: extract_features(ctx, v["name"])
        for v in g.vs if v["kind"] == "claim"
    }

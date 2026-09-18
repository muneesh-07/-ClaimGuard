"""
The ring-detector ladder: cheap-to-expensive rungs, run in order, with
which rung fired recorded as part of the explanation. Each rung is
independently disable-able and its contribution independently
reportable - see tools/eval.py.
"""

from dataclasses import dataclass, field

import igraph as ig
import leidenalg as la

DEFAULT_MIN_RING_SIZE = 3
DEFAULT_LEIDEN_RESOLUTION = 1.2
BURSTINESS_WINDOW_DAYS = 14

# Rung 1's degree threshold, per entity type rather than one flat number, tuned against
# the real dataset. PHONE tops out at degree 12 (matching planted ring sizes) and SHOP
# sits uniformly above 1,000, so both are easy calls at 50. ADDRESS is the hard case:
# its smaller combinatorial space makes unrelated claims coincidentally collide on one
# far more often, and letting any shared address into Rung 1 chains background claims
# into artificially large "rings" - precision was 0.958 at threshold=1 vs 0.194 at
# threshold=3, for the same 100% ring recall either way. At threshold=1 a degree-1
# entity is a graph leaf and can never connect two claims, so Rung 1 ends up effectively
# phone-driven - matching what's actually true here: phone is the deterministic signal.
DEFAULT_DEGREE_THRESHOLDS = {"PHONE": 50, "ADDRESS": 1, "SHOP": 50}
FALLBACK_DEGREE_THRESHOLD = 50

# Decision thresholds shared by detect()'s own seed selection and by explain.py's
# decision_hint - one definition, so the two can never quietly disagree on what "FLAG" means.
FLAG_AT = 0.75
REVIEW_AT = 0.40


@dataclass
class ClaimVerdict:
    """One claim's detector output: its score, which rung produced it,
    and (if any) the community/ring it belongs to."""

    fraud_score: float
    rung: str
    ring_id: str | None
    community_claim_ids: list[str] = field(default_factory=list)


# Rung 1 prep: entities above their type's degree threshold get pruned before anything
# else runs - a repair shop touching thousands of claims (or, as it turns out, a
# moderately-collision-prone address touching a dozen) otherwise merges unrelated claims
# into one component and hides every real, tightly-connected ring inside it.
def _prune_high_degree_entities(g: ig.Graph, degree_thresholds: dict[str, int]) -> ig.Graph:
    to_delete = [
        v.index for v in g.vs
        if v["kind"] == "entity"
        and g.degree(v.index) > degree_thresholds.get(v["entity_type"], FALLBACK_DEGREE_THRESHOLD)
    ]
    pruned = g.copy()
    pruned.delete_vertices(to_delete)
    return pruned


# Rung 1: connected components on the pruned graph. Catches blatant rings for almost no
# compute - a ring whose claims share ONLY low-degree entities shows up as its own
# small component once the noisy hubs are gone.
def rung1_components(g: ig.Graph, degree_thresholds: dict[str, int] = DEFAULT_DEGREE_THRESHOLDS,
                      min_ring_size: int = DEFAULT_MIN_RING_SIZE) -> dict[str, str]:
    pruned = _prune_high_degree_entities(g, degree_thresholds)
    result: dict[str, str] = {}
    for component_index, component in enumerate(pruned.connected_components()):
        claim_members = [pruned.vs[i]["name"] for i in component if pruned.vs[i]["kind"] == "claim"]
        if len(claim_members) >= min_ring_size:
            ring_id = f"kcore-{component_index}"
            for claim_id in claim_members:
                result[claim_id] = ring_id
    return result


# The ring fingerprint: a real ring is many claimants funnelled through few real
# entities. A community that's mostly one claim per entity (ratio ~1) is just ordinary
# claims that happen to touch the same handful of things - not a ring.
def _claimants_per_entity_ratio(claim_count: int, entity_count: int) -> float:
    if entity_count == 0:
        return 0.0
    return claim_count / entity_count


# How tightly clustered in time a community's claims are: the largest fraction of the
# community that was filed within any BURSTINESS_WINDOW_DAYS-day window. Rings tend to
# file in bursts; unrelated claims that coincidentally share an entity don't.
def _burstiness(dates: list) -> float:
    valid_dates = sorted(d for d in dates if d is not None)
    if len(valid_dates) < 2:
        return 0.0
    best = 1
    for i, start in enumerate(valid_dates):
        count = sum(1 for d in valid_dates if 0 <= (d - start).days <= BURSTINESS_WINDOW_DAYS)
        best = max(best, count)
    return best / len(valid_dates)


# Squashes the ring-fingerprint ratio and temporal burstiness into one 0-1 suspiciousness
# score for a community. Ratio alone can already clear the FLAG threshold - it's the
# stronger, more specific signal, and a ring that files slowly over months is still a
# ring. Burstiness only adds confidence on top; its absence must never be what keeps an
# obvious ring under the threshold.
def _suspiciousness(claimants_per_entity: float, burstiness: float) -> float:
    ratio_score = min(1.0, max(0.0, (claimants_per_entity - 1.0) / 4.0))
    return round(min(1.0, 0.85 * ratio_score + 0.15 * burstiness), 4)


# Rung 2: Leiden community detection on the FULL weighted bipartite graph (no pruning -
# the IDF weights already tell Leiden that high-degree entities barely hold communities
# together), then a suspiciousness score per community from the ring fingerprint + burstiness.
def rung2_leiden(g: ig.Graph, resolution: float = DEFAULT_LEIDEN_RESOLUTION,
                  min_ring_size: int = DEFAULT_MIN_RING_SIZE, seed: int = 42) -> dict[str, ClaimVerdict]:
    # Leiden's local-move phase is randomized, so leaving the seed unset makes every
    # run (and every eval number) slightly different - fine for production, not for a
    # documented, reproducible metric. Pinned so `make eval` gives the same answer twice.
    partition = la.find_partition(
        g, la.RBConfigurationVertexPartition, weights="weight", resolution_parameter=resolution,
        seed=seed,
    )

    result: dict[str, ClaimVerdict] = {}
    for community_index, members in enumerate(partition):
        claim_member_indices = [i for i in members if g.vs[i]["kind"] == "claim"]
        entity_count = sum(1 for i in members if g.vs[i]["kind"] == "entity")
        if len(claim_member_indices) < min_ring_size:
            continue

        claim_members = [g.vs[i]["name"] for i in claim_member_indices]
        ratio = _claimants_per_entity_ratio(len(claim_members), entity_count)
        dates = [g.vs[i]["incident_date"] for i in claim_member_indices]
        burst = _burstiness(dates)
        score = _suspiciousness(ratio, burst)

        ring_id = f"leiden-{community_index}"
        for claim_id in claim_members:
            result[claim_id] = ClaimVerdict(
                fraud_score=score, rung="leiden_community", ring_id=ring_id,
                community_claim_ids=claim_members,
            )
    return result


# Rung 3: personalized PageRank restarting from the claims Rung 1/2 already flagged -
# propagates suspicion to claims that are NEAR a ring (share an entity with a flagged
# claim) without being densely connected enough to land in the ring's own community.
# This is the gap the first two rungs leave.
def rung3_ppr(g: ig.Graph, seed_claim_ids: set[str], damping: float = 0.85) -> dict[str, float]:
    if not seed_claim_ids:
        return {}
    # reset_vertices takes actual vertex names/ids for a uniform restart set - NOT a
    # pre-built probability vector (that's the separate `reset` parameter; passing a
    # full-length vector here is a type error, igraph tries to read it as vertex ids).
    # Callers always pass seeds drawn from this same graph's own verdicts, so every
    # name is guaranteed to already be a vertex here.
    pagerank = g.personalized_pagerank(reset_vertices=list(seed_claim_ids), weights="weight", damping=damping)
    max_score = max(pagerank) or 1.0
    return {
        g.vs[i]["name"]: pagerank[i] / max_score
        for i in range(len(pagerank))
        if g.vs[i]["kind"] == "claim" and g.vs[i]["name"] not in seed_claim_ids
    }


# Runs all three rungs and combines them. Rung 1 and Rung 2 each independently produce a
# candidate verdict for a claim; where both fire, the HIGHER-confidence one wins - it must
# never be possible for a weaker rung to silently override a stronger one just by being
# computed second. Rung 3 then fills in every remaining claim with its PPR-propagated score.
def detect(g: ig.Graph, degree_thresholds: dict[str, int] = DEFAULT_DEGREE_THRESHOLDS,
           resolution: float = DEFAULT_LEIDEN_RESOLUTION,
           min_ring_size: int = DEFAULT_MIN_RING_SIZE) -> dict[str, ClaimVerdict]:
    rung1 = rung1_components(g, degree_thresholds, min_ring_size)
    rung2 = rung2_leiden(g, resolution, min_ring_size)

    # rung1 only maps claim_id -> ring_id; group it back into ring_id -> members so k_core
    # verdicts can report their community size too, not just Leiden ones.
    rung1_members: dict[str, list[str]] = {}
    for claim_id, ring_id in rung1.items():
        rung1_members.setdefault(ring_id, []).append(claim_id)

    # Sorted, not a bare set: Python's set iteration order is hash-randomized per process,
    # and with hundreds of claims tied at the exact same score (0.9 for every k_core
    # verdict), that non-determinism silently changed which claims landed in a top-k
    # cutoff between runs - a real reproducibility bug caught by running `make eval` twice.
    all_claim_ids = sorted({v["name"] for v in g.vs if v["kind"] == "claim"})

    verdicts: dict[str, ClaimVerdict] = {}
    for claim_id in all_claim_ids:
        candidates = []
        if claim_id in rung1:
            ring_id = rung1[claim_id]
            candidates.append(ClaimVerdict(
                fraud_score=0.9, rung="k_core", ring_id=ring_id,
                community_claim_ids=rung1_members[ring_id],
            ))
        if claim_id in rung2:
            candidates.append(rung2[claim_id])
        if candidates:
            verdicts[claim_id] = max(candidates, key=lambda v: v.fraud_score)

    seeds = {claim_id for claim_id, verdict in verdicts.items() if verdict.fraud_score >= FLAG_AT}
    ppr_scores = rung3_ppr(g, seeds)
    for claim_id, score in ppr_scores.items():
        if claim_id not in verdicts and score > 0.05:
            verdicts[claim_id] = ClaimVerdict(fraud_score=round(score, 4), rung="ppr", ring_id=None)

    for v in g.vs:
        if v["kind"] == "claim" and v["name"] not in verdicts:
            verdicts[v["name"]] = ClaimVerdict(fraud_score=0.0, rung="none", ring_id=None)

    return verdicts

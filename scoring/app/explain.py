"""
Turns a claim's position in the graph into the evidence array a human
reviewer reads. Per docs/APPROACH.md Layer 1: "the path claim A -
[phone:+919876500011] - claim B IS the explanation" - this walks
exactly that path, sorted so the rarest (highest-weight, most specific)
shared entities are listed first. It is not a separate model from the
detector; it reads the same graph the detector scored the claim on.
"""

import igraph as ig

from app.detector import FLAG_AT, REVIEW_AT, ClaimVerdict
from app.models import ClaimScore, Explanation, RingMetricEvidence, SharedEntityEvidence, Thresholds, now_utc

MAX_EVIDENCE_ENTITIES = 5
MAX_NEIGHBORS_PER_ENTITY = 10


# Masks a raw entity value for API output, keeping only enough to be recognisable - full
# values belong in the audit trail (once M7 wires scoring into it), not a scoring response.
def mask_entity_value(raw_value: str) -> str:
    if len(raw_value) <= 4:
        return "*" * len(raw_value)
    return raw_value[:2] + "*" * (len(raw_value) - 4) + raw_value[-2:]


# Builds the full ClaimScore (score + evidence) for one claim, reading everything off the
# already-scored graph - no new database queries needed once the graph and verdicts exist.
def build_score(g: ig.Graph, name_to_index: dict[str, int], verdicts: dict[str, ClaimVerdict],
                 claim_id: str, model_version: str) -> ClaimScore | None:
    verdict = verdicts.get(claim_id)
    claim_index = name_to_index.get(claim_id)
    if verdict is None or claim_index is None:
        return None

    incident_edge_ids = sorted(
        g.incident(claim_index), key=lambda eid: g.es[eid]["weight"], reverse=True,
    )[:MAX_EVIDENCE_ENTITIES]

    evidence: list[SharedEntityEvidence] = []
    for edge_id in incident_edge_ids:
        edge = g.es[edge_id]
        entity_index = edge.target if edge.source == claim_index else edge.source
        entity_vertex = g.vs[entity_index]
        neighbor_names = [
            g.vs[n]["name"] for n in g.neighbors(entity_index) if g.vs[n]["name"] != claim_id
        ][:MAX_NEIGHBORS_PER_ENTITY]

        evidence.append(SharedEntityEvidence(
            entity_type=entity_vertex["entity_type"],
            entity_value=mask_entity_value(entity_vertex["canonical_value"]),
            entity_degree=entity_vertex["degree_raw"],
            shared_with_claim_ids=neighbor_names,
        ))

    if verdict.community_claim_ids:
        evidence.append(RingMetricEvidence(
            metric="community_size",
            value=float(len(verdict.community_claim_ids)),
            baseline=1.0,
        ))

    if verdict.rung == "none" or not evidence:
        summary = "No shared entities with any other claim."
    elif verdict.ring_id:
        summary = (
            f"Part of a {len(verdict.community_claim_ids)}-claim cluster ({verdict.ring_id}) "
            f"detected via {verdict.rung}."
        )
    else:
        summary = f"Elevated risk via proximity to a flagged cluster (rung: {verdict.rung})."

    return ClaimScore(
        claim_id=claim_id,
        model_version=model_version,
        scored_at=now_utc(),
        fraud_score=verdict.fraud_score,
        decision_hint=_decision_hint(verdict.fraud_score),
        ring_id=verdict.ring_id,
        rung=verdict.rung,
        explanation=Explanation(
            summary=summary,
            evidence=evidence,
            thresholds=Thresholds(flag_at=FLAG_AT, review_at=REVIEW_AT),
        ),
    )


def _decision_hint(score: float) -> str:
    if score >= FLAG_AT:
        return "FLAG"
    if score >= REVIEW_AT:
        return "REVIEW"
    return "CLEAR"

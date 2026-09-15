"""
The M5 stub scorer. Deliberately not a fraud detector: there is no
graph library, no Leiden, no PageRank here yet (that ladder is M6, per
docs/APPROACH.md Layer 2). What this DOES do honestly is read the real
bipartite graph out of Postgres and score a claim by how many OTHER
claims it's connected to through a shared entity - "component size" in
miniature, one hop out. That's enough to exercise the full contract
end to end (Java <-> Python, the JSON shape, decision thresholds) before
the real algorithm exists, which is the entire point of M5.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import (
    STUB_MODEL_VERSION,
    ClaimScore,
    Explanation,
    RingMetricEvidence,
    SharedEntityEvidence,
    Thresholds,
    now_utc,
)

FLAG_AT = 0.75
REVIEW_AT = 0.40


# Masks a raw entity value for API output, keeping only enough to be recognisable - full
# values belong in the audit trail (once M7 wires scoring into it), not a scoring response.
def mask_entity_value(raw_value: str) -> str:
    if len(raw_value) <= 4:
        return "*" * len(raw_value)
    return raw_value[:2] + "*" * (len(raw_value) - 4) + raw_value[-2:]


# Fetches every (entity_id, entity_type, canonical_value, claim_count) row a claim references.
def _entities_for_claim(session: Session, claim_id: UUID):
    return session.execute(
        text("""
            select e.id, e.entity_type, e.canonical_value, e.claim_count
            from claim_entities l
            join entities e on e.id = l.entity_id
            where l.claim_id = :claim_id
        """),
        {"claim_id": str(claim_id)},
    ).all()


# Fetches every other claim id that shares the given entity, excluding the claim itself.
def _claims_sharing_entity(session: Session, entity_id, claim_id: UUID) -> list[UUID]:
    rows = session.execute(
        text("select claim_id from claim_entities where entity_id = :entity_id and claim_id != :claim_id"),
        {"entity_id": entity_id, "claim_id": str(claim_id)},
    ).all()
    return [row[0] for row in rows]


# Squashes an unbounded neighbour count into (0, 1) - more connections means a higher score,
# but with diminishing returns, so one claim with thousands of neighbours doesn't just read as 1.0.
def _score_from_neighbor_count(neighbor_count: int) -> float:
    return round(neighbor_count / (neighbor_count + 5), 4)


# Turns a raw score into the three-way decision a human workflow actually acts on.
def _decision_hint(score: float) -> str:
    if score >= FLAG_AT:
        return "FLAG"
    if score >= REVIEW_AT:
        return "REVIEW"
    return "CLEAR"


# Scores one claim: reads its entities and their neighbourhoods from Postgres, builds the
# evidence array straight off that graph data, and returns the full contract-shaped result.
def score_claim(session: Session, claim_id: UUID) -> ClaimScore | None:
    entity_rows = _entities_for_claim(session, claim_id)
    if not entity_rows:
        return None

    evidence: list[SharedEntityEvidence] = []
    all_neighbors: set[UUID] = set()

    for entity_id, entity_type, canonical_value, claim_count in entity_rows:
        neighbor_ids = _claims_sharing_entity(session, entity_id, claim_id)
        if not neighbor_ids:
            continue
        all_neighbors.update(neighbor_ids)
        evidence.append(SharedEntityEvidence(
            entity_type=entity_type,
            entity_value=mask_entity_value(canonical_value),
            entity_degree=claim_count,
            shared_with_claim_ids=neighbor_ids,
        ))

    neighbor_count = len(all_neighbors)
    score = _score_from_neighbor_count(neighbor_count)

    ring_evidence = RingMetricEvidence(
        metric="one_hop_neighbor_count",
        value=float(neighbor_count),
        baseline=0.0,
    )

    if neighbor_count == 0:
        summary = "Shares no entity with any other claim in the system."
    else:
        summary = (
            f"Connected to {neighbor_count} other claim(s) through "
            f"{len(evidence)} shared entit{'y' if len(evidence) == 1 else 'ies'}."
        )

    return ClaimScore(
        claim_id=claim_id,
        model_version=STUB_MODEL_VERSION,
        scored_at=now_utc(),
        fraud_score=score,
        decision_hint=_decision_hint(score),
        ring_id=None,
        rung="stub",
        explanation=Explanation(
            summary=summary,
            evidence=[*evidence, ring_evidence],
            thresholds=Thresholds(flag_at=FLAG_AT, review_at=REVIEW_AT),
        ),
    )

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
from app.features import FeatureContext
from app.model import FeatureContribution, RingClassifier, score_claim
from app.models import (
    ClaimScore,
    Explanation,
    FeatureContributionEvidence,
    RingMetricEvidence,
    SharedEntityEvidence,
    Thresholds,
    now_utc,
)

MAX_EVIDENCE_ENTITIES = 5
MAX_NEIGHBORS_PER_ENTITY = 10


# Masks a raw entity value for API output, keeping only enough to be recognisable - full
# values belong in the audit trail (once M7 wires scoring into it), not a scoring response.
def mask_entity_value(raw_value: str) -> str:
    if len(raw_value) <= 4:
        return "*" * len(raw_value)
    return raw_value[:2] + "*" * (len(raw_value) - 4) + raw_value[-2:]


# Walks a claim's incident edges (highest-weight/rarest entity first) and builds one
# SharedEntityEvidence per entity - the "claim A -[phone]- claim B IS the explanation"
# path both the rule-based and the model-based scoring paths show a reviewer, since which
# entities a claim shares is a fact about the graph, independent of which method scored it.
def _shared_entity_evidence(g: ig.Graph, claim_index: int, claim_id: str) -> list[SharedEntityEvidence]:
    incident_edge_ids = sorted(
        g.incident(claim_index), key=lambda eid: g.es[eid]["weight"], reverse=True,
    )[:MAX_EVIDENCE_ENTITIES]

    evidence = []
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
    return evidence


# Builds the full ClaimScore (score + evidence) for one claim using the Tier 1 trained
# model: a calibrated fraud probability plus real per-prediction SHAP attributions, rather
# than app.detector's hardcoded rung scores. Falls back to None (not an exception) for a
# claim with no entity links at all - same contract as the rule-based build_score.
def build_model_score(g: ig.Graph, ctx: FeatureContext, classifier: RingClassifier,
                       claim_id: str) -> ClaimScore | None:
    claim_index = ctx.name_to_index.get(claim_id)
    if claim_index is None:
        return None

    scored = score_claim(classifier, ctx, claim_id)
    if scored is None:
        return None
    probability, contributions = scored

    evidence: list = _shared_entity_evidence(g, claim_index, claim_id)
    evidence.extend(_feature_contribution_evidence(contributions))

    ring_id = ctx.component_of.get(claim_id)
    leiden_verdict = ctx.leiden_verdicts.get(claim_id)
    if ring_id is None and leiden_verdict is not None:
        ring_id = leiden_verdict.ring_id

    if not evidence:
        summary = "No shared entities with any other claim."
    else:
        top_feature = contributions[0].feature if contributions else None
        summary = (f"Fraud probability {probability:.2f} from the trained ring classifier"
                   f"{f' (driven mainly by {top_feature})' if top_feature else ''}.")

    return ClaimScore(
        claim_id=claim_id,
        model_version=classifier.model_version,
        scored_at=now_utc(),
        fraud_score=round(probability, 4),
        decision_hint=_decision_hint(probability, classifier.flag_threshold, classifier.review_threshold),
        ring_id=ring_id,
        rung="xgboost",
        explanation=Explanation(
            summary=summary,
            evidence=evidence,
            thresholds=Thresholds(flag_at=classifier.flag_threshold, review_at=classifier.review_threshold),
        ),
    )


# Turns SHAP feature attributions into FeatureContributionEvidence rows, ranked strongest
# (by absolute SHAP value) first - already the order app.model.score_claim returns them in.
def _feature_contribution_evidence(
        contributions: list[FeatureContribution]) -> list[FeatureContributionEvidence]:
    return [
        FeatureContributionEvidence(feature=c.feature, feature_value=c.feature_value, shap_value=c.shap_value)
        for c in contributions
    ]


# Builds the full ClaimScore (score + evidence) for one claim, reading everything off the
# already-scored graph - no new database queries needed once the graph and verdicts exist.
# Kept as the rule-based fallback path (see app.model.load) for a checkout with no trained
# model yet, and for what tools/eval.py measures the Tier 0 detector's own numbers against.
def build_score(g: ig.Graph, name_to_index: dict[str, int], verdicts: dict[str, ClaimVerdict],
                 claim_id: str, model_version: str) -> ClaimScore | None:
    verdict = verdicts.get(claim_id)
    claim_index = name_to_index.get(claim_id)
    if verdict is None or claim_index is None:
        return None

    evidence: list = _shared_entity_evidence(g, claim_index, claim_id)

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


# Defaults to the rule-based detector's fixed FLAG_AT/REVIEW_AT constants (a real ring
# there always scores a flat 0.9, so those constants only ever needed to separate 0.9 from
# lower rungs). The Tier 1 model passes ITS OWN flag_threshold/review_threshold instead -
# thresholds chosen from that model's actual calibrated score distribution on real
# validation data, not two numbers tuned for a different scoring method entirely.
def _decision_hint(score: float, flag_at: float = FLAG_AT, review_at: float = REVIEW_AT) -> str:
    if score >= flag_at:
        return "FLAG"
    if score >= review_at:
        return "REVIEW"
    return "CLEAR"

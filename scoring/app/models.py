"""
The scoring contract - written down here AND in docs/scoring-contract.md,
which must stay in sync. This is the versioned interface between the two
services: Java only ever needs to trust these shapes, never the Python
implementation behind them. Per docs/EXECUTION_PLAN.md M5, get the
contract right before the algorithm is any good - a stub score that
flows through this exact shape is worth more than a brilliant detector
nothing can call.
"""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class SharedEntityEvidence(BaseModel):
    """One piece of evidence: this claim shares a specific entity with other claims."""

    type: Literal["SHARED_ENTITY"] = "SHARED_ENTITY"
    entity_type: str
    entity_value: str
    entity_degree: int
    shared_with_claim_ids: list[UUID]


class RingMetricEvidence(BaseModel):
    """One piece of evidence: a ring-level metric computed for whatever cluster the claim sits in."""

    type: Literal["RING_METRIC"] = "RING_METRIC"
    metric: str
    value: float
    baseline: float


class FeatureContributionEvidence(BaseModel):
    """One piece of evidence: how much one feature's SHAP value pushed the Tier 1
    model's score up or down for this specific claim - a real, per-prediction
    attribution from tools/train_model.py's trained classifier, not a hand-written
    explanation string. Positive shap_value pushed the score toward FLAG."""

    type: Literal["FEATURE_CONTRIBUTION"] = "FEATURE_CONTRIBUTION"
    feature: str
    feature_value: float
    shap_value: float


Evidence = SharedEntityEvidence | RingMetricEvidence | FeatureContributionEvidence


class Thresholds(BaseModel):
    """The score cutoffs decision_hint was derived from, so a caller never has to hardcode them."""

    flag_at: float
    review_at: float


class Explanation(BaseModel):
    """Why a claim got the score it did, read directly off the entity graph - not a separate model."""

    summary: str
    evidence: list[Evidence]
    thresholds: Thresholds


class ClaimScore(BaseModel):
    """One claim's full scoring result - the unit both /score/batch and the
    eventual claim.scored Kafka event carry."""

    claim_id: UUID
    model_version: str
    scored_at: datetime
    fraud_score: float = Field(ge=0.0, le=1.0)
    decision_hint: Literal["CLEAR", "REVIEW", "FLAG"]
    ring_id: str | None
    rung: str
    explanation: Explanation


class ScoreBatchRequest(BaseModel):
    """What Java sends: the claim ids to score, batched rather than one call per claim."""

    claim_ids: list[UUID] = Field(min_length=1, max_length=1000)


class ScoreBatchResponse(BaseModel):
    """What Java gets back: one ClaimScore per requested claim id that actually exists."""

    results: list[ClaimScore]


class NarrativeRequest(BaseModel):
    """What a caller sends to generate an investigator narrative: one claim id
    at a time (unlike /score/batch), since narrative generation runs a local
    LLM and takes seconds, not milliseconds - see app.narrative."""

    claim_id: UUID


class NarrativeResponse(BaseModel):
    """What a caller gets back: the narrative text, whether it passed the
    grounding check (app.narrative._is_grounded) or fell back to the
    deterministic template summary, which model actually produced it, and
    how long generation took - real, measured fields, not decoration."""

    claim_id: UUID
    narrative: str
    grounded: bool
    model_version: str
    generation_ms: float
    generated_at: datetime


# The version string stamped on every score this stub produces. Bump this
# whenever the scoring logic changes - it's what an audit row would
# record as "which model produced this decision" once M7 wires scoring
# into the workflow.
STUB_MODEL_VERSION = "stub-component-size-0.1.0"


# Builds the current UTC timestamp in the exact form ClaimScore.scored_at expects.
def now_utc() -> datetime:
    return datetime.now(UTC)

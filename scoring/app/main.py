"""
FastAPI entry point for the ClaimGuard scoring service. Owns exactly two
endpoints for now: a health check, and batch scoring. Batch, not
one-claim-per-call, per docs/EXECUTION_PLAN.md M5 - the Java side will
eventually call this once per Kafka batch, not once per claim.
"""

from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import ScoreBatchRequest, ScoreBatchResponse
from app.scoring import score_claim

app = FastAPI(title="ClaimGuard Scoring Service", version="0.1.0")


# Liveness check - no database dependency on purpose, so it stays meaningful even if Postgres is unreachable.
@app.get("/health")
def health():
    return {"status": "UP", "service": "claimguard-scoring"}


# Scores every claim id in the request that actually exists (and has entity links);
# unknown ids are silently skipped rather than failing the whole batch.
@app.post("/score/batch", response_model=ScoreBatchResponse)
def score_batch(request: ScoreBatchRequest, session: Session = Depends(get_session)):
    results = []
    for claim_id in request.claim_ids:
        result = score_claim(session, claim_id)
        if result is not None:
            results.append(result)
    return ScoreBatchResponse(results=results)

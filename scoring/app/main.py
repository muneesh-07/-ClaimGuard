"""
FastAPI entry point for the ClaimGuard scoring service. Three endpoints:
a health check, batch scoring (backed by the M6 ring detector), and a
manual graph refresh. Batch, not one-claim-per-call, per
docs/EXECUTION_PLAN.md M5 - the Java side will eventually call this once
per Kafka batch, not once per claim.
"""

from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import ScoreBatchRequest, ScoreBatchResponse
from app.scoring import refresh, score_claims

app = FastAPI(title="ClaimGuard Scoring Service", version="0.1.0")


# Liveness check - no database dependency on purpose, so it stays meaningful even if Postgres is unreachable.
@app.get("/health")
def health():
    return {"status": "UP", "service": "claimguard-scoring"}


# Scores every claim id in the request that actually exists (and has entity links) against
# the cached detector graph; unknown ids are silently skipped rather than failing the batch.
@app.post("/score/batch", response_model=ScoreBatchResponse)
def score_batch(request: ScoreBatchRequest, session: Session = Depends(get_session)):
    results = score_claims(session, request.claim_ids)
    return ScoreBatchResponse(results=results)


# Rebuilds the graph and reruns the detector ladder - call after loading new data, since
# the graph is otherwise cached for the life of the process (see app/scoring.py).
@app.post("/graph/refresh")
def graph_refresh(session: Session = Depends(get_session)):
    claims_scored = refresh(session)
    return {"claims_scored": claims_scored}

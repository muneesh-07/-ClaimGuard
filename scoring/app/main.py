"""
FastAPI entry point for the ClaimGuard scoring service: a health check,
batch scoring (backed by the Tier 1 trained model, or the rule-based
detector as a fallback - see app/scoring.py), a manual graph refresh, and
two read-only endpoints over tools/train_model.py's persisted artifacts
so the frontend can show real training/evaluation output, not a number
typed into the UI by hand. Batch, not one-claim-per-call, per
docs/EXECUTION_PLAN.md M5 - the Java side will eventually call this once
per Kafka batch, not once per claim.
"""

import json

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.db import get_session
from app.model import MODELS_DIR
from app.models import ScoreBatchRequest, ScoreBatchResponse
from app.scoring import refresh, score_claims

app = FastAPI(title="ClaimGuard Scoring Service", version="0.1.0")

# Lets the frontend (frontend/, served on its own origin/port) read /model/metadata and
# /model/eval-report directly, the same reasoning as the backend's
# SecurityConfig.corsConfigurationSource - scoped to localhost only, a local dev/demo
# frontend, not a public one. POST /score/batch isn't meant to be called from a browser at
# all (Java is the only real caller), so this stays read-only in spirit even though CORS
# itself doesn't distinguish routes.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["GET"],
    allow_headers=["*"],
)


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


# Reads one JSON file tools/train_model.py wrote to scoring/models/, or 404s with a
# specific reason - "never trained" and "file unreadable" are different failure modes a
# caller (this scoring service has no write access to fix either) should be able to tell apart.
def _read_model_artifact(filename: str, not_found_detail: str) -> dict:
    path = MODELS_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail=not_found_detail)
    return json.loads(path.read_text())


# The trained model's version, feature list, and operating thresholds - what a "Model"
# panel in the frontend needs without exposing the raw model file itself.
@app.get("/model/metadata")
def model_metadata():
    return _read_model_artifact(
        "model_metadata.json", "No trained model yet - run `make train-model` first.")


# The full ablation report tools/train_model.py produced: tabular-only vs +graph-features
# vs +calibration, and the ring-injection ablation on held-out rings never seen in
# training - real, measured numbers from the last training run, not hardcoded example data.
@app.get("/model/eval-report")
def model_eval_report():
    return _read_model_artifact(
        "eval_report.json", "No evaluation report yet - run `make train-model` first.")

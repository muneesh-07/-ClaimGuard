"""
Orchestrates fraud scoring for the API: builds the bipartite graph once,
runs it through the Tier 1 trained classifier (tools/train_model.py) if one
has been trained, and caches everything in process memory so /score/batch
doesn't rebuild a 50k+ claim graph on every request. This is a simplified
stand-in for M9's eventual "nightly global Leiden pass, real-time scoring
serves from the last good partition" - one process-lifetime cache instead
of a scheduled job, since there's no scheduler wired up yet. POST
/graph/refresh rebuilds it on demand (e.g. after loading new data).

If scoring/models/ has no trained model (a fresh checkout that hasn't run
`make train-model` yet), this falls back to app.detector's rule-based
rungs - a legitimate answer, not a degraded one, to "no learned model
exists here yet."
"""

from dataclasses import dataclass
from uuid import UUID

import igraph as ig
from sqlalchemy.orm import Session

from app.detector import ClaimVerdict, detect
from app.explain import build_model_score, build_score
from app.features import FeatureContext, build_feature_context
from app.graph import build_graph
from app.model import RingClassifier
from app.model import load as load_classifier
from app.models import ClaimScore

RULE_BASED_MODEL_VERSION = "ring-detector-0.1.0"

# Loaded once at import time, not per-request or per-refresh: the trained model doesn't
# change while this process is running (a new training run means a new deploy), so
# there's nothing to gain from re-reading it from disk on every graph refresh.
_classifier: RingClassifier | None = load_classifier()


@dataclass
class _Cache:
    graph: ig.Graph | None = None
    name_to_index: dict[str, int] | None = None
    verdicts: dict[str, ClaimVerdict] | None = None
    feature_context: FeatureContext | None = None


_cache = _Cache()


# Rebuilds the graph from Postgres. If a Tier 1 model is loaded, also builds the
# FeatureContext it scores against (which itself runs the rung1/rung2/rung3 graph
# analytics as feature inputs - see app.features); otherwise falls back to running
# app.detector.detect()'s rule-based ladder directly. Returns how many claims are
# now scoreable.
def refresh(session: Session) -> int:
    g = build_graph(session)
    _cache.graph = g
    _cache.name_to_index = {v["name"]: v.index for v in g.vs if v["kind"] == "claim"}

    if _classifier is not None:
        _cache.feature_context = build_feature_context(g)
        _cache.verdicts = None
        return len(_cache.name_to_index)

    _cache.verdicts = detect(g)
    _cache.feature_context = None
    return len(_cache.verdicts)


# Scores a batch of claim ids against the cached graph, building it first if this is the
# first call since startup. Uses the Tier 1 model when one is loaded, otherwise the
# rule-based detector - the same fallback refresh() sets up.
def score_claims(session: Session, claim_ids: list[UUID]) -> list[ClaimScore]:
    if _cache.graph is None:
        refresh(session)

    results = []
    for claim_id in claim_ids:
        if _classifier is not None:
            score = build_model_score(_cache.graph, _cache.feature_context, _classifier, str(claim_id))
        else:
            score = build_score(_cache.graph, _cache.name_to_index, _cache.verdicts,
                                 str(claim_id), RULE_BASED_MODEL_VERSION)
        if score is not None:
            results.append(score)
    return results

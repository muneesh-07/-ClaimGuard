"""
Orchestrates the real ring detector (M6) for the API: builds the
bipartite graph once, runs the full rung ladder once, and caches both
in process memory so /score/batch doesn't rebuild a 50k+ claim graph on
every request. This is a simplified stand-in for M9's eventual "nightly
global Leiden pass, real-time scoring serves from the last good
partition" - one process-lifetime cache instead of a scheduled job,
since there's no scheduler wired up yet. POST /graph/refresh rebuilds
it on demand (e.g. after loading new data).
"""

from dataclasses import dataclass
from uuid import UUID

import igraph as ig
from sqlalchemy.orm import Session

from app.detector import ClaimVerdict, detect
from app.explain import build_score
from app.graph import build_graph
from app.models import ClaimScore

MODEL_VERSION = "ring-detector-0.1.0"


@dataclass
class _Cache:
    graph: ig.Graph | None = None
    name_to_index: dict[str, int] | None = None
    verdicts: dict[str, ClaimVerdict] | None = None


_cache = _Cache()


# Rebuilds the graph from Postgres and reruns the full detector ladder
# over it. Returns how many claims now have a verdict.
def refresh(session: Session) -> int:
    g = build_graph(session)
    verdicts = detect(g)
    _cache.graph = g
    _cache.name_to_index = {v["name"]: v.index for v in g.vs if v["kind"] == "claim"}
    _cache.verdicts = verdicts
    return len(verdicts)


# Scores a batch of claim ids against the cached graph, building it
# first if this is the first call since startup.
def score_claims(session: Session, claim_ids: list[UUID]) -> list[ClaimScore]:
    if _cache.graph is None:
        refresh(session)

    results = []
    for claim_id in claim_ids:
        score = build_score(_cache.graph, _cache.name_to_index, _cache.verdicts, str(claim_id), MODEL_VERSION)
        if score is not None:
            results.append(score)
    return results

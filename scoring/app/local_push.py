"""
Local-push approximate personalized PageRank (Andersen, Chung & Lang,
"Local Graph Partitioning using PageRank Vectors", FOCS 2006), for M9's
incremental scoring path. Unlike app.detector.rung3_ppr (which calls
igraph's personalized_pagerank - a GLOBAL computation that necessarily
touches every vertex in the graph), this only ever visits vertices whose
accumulated residual exceeds a threshold relative to their degree -
provably O(1 / (alpha * epsilon)) of them, independent of how large the
rest of the graph is. That's what lets a brand-new claim be scored by
pushing outward from just its own node, instead of rebuilding the whole
51k-claim graph the way M7's `refresh()` fallback currently does.
"""

from collections import deque

import igraph as ig

DEFAULT_ALPHA = 0.15
DEFAULT_EPSILON = 1e-5
MAX_PUSHES = 200_000


# The weighted degree of a vertex: sum of its incident edge weights (falls
# back to 1.0 for an isolated vertex - avoids a division by zero, with no
# real effect since it has no edges to push along anyway).
def _weighted_degree(g: ig.Graph, vertex: int, cache: dict[int, float]) -> float:
    if vertex not in cache:
        total = sum(g.es[eid]["weight"] for eid in g.incident(vertex))
        cache[vertex] = total if total > 0 else 1.0
    return cache[vertex]


# One push operation: moves alpha of a vertex's residual permanently into
# its PageRank estimate, and distributes the rest to its neighbours in
# proportion to edge weight. Mass is conserved exactly - p[u] gains
# alpha*r[u], and the (1-alpha)*r[u] pushed out is what neighbours'
# residuals gain, so sum(p) + sum(r) never changes.
def _push(g: ig.Graph, u: int, p: dict[int, float], r: dict[int, float],
          alpha: float, degree_cache: dict[int, float]) -> list[int]:
    du = _weighted_degree(g, u, degree_cache)
    ru = r.get(u, 0.0)
    p[u] = p.get(u, 0.0) + alpha * ru
    mass = (1 - alpha) * ru
    r[u] = 0.0

    newly_active = []
    for eid in g.incident(u):
        edge = g.es[eid]
        v = edge.target if edge.source == u else edge.source
        weight = edge["weight"]
        share = mass * (weight / du)
        r[v] = r.get(v, 0.0) + share
        newly_active.append(v)
    return newly_active


# Runs the local-push algorithm from one seed vertex until every vertex's
# residual-to-degree ratio drops below epsilon (or max_pushes is hit, as a
# hard safety bound). Returns the sparse PageRank estimate p and the set of
# vertices actually PUSHED FROM (processed off the queue) - the quantity
# the ACL theorem bounds at O(1/(alpha*epsilon)), independent of graph
# size. Deliberately NOT "every vertex that ever received a residual
# crumb": if the push reaches a high-degree hub (a repair shop shared by
# thousands of claims), every one of its neighbours gets a tiny residual
# share in one step, but only the handful whose share clears the epsilon
# threshold are ever queued and pushed from - counting the rest as
# "touched" would overstate how much work was actually done and understate
# how local the computation really was.
def local_push_ppr(g: ig.Graph, seed: int, alpha: float = DEFAULT_ALPHA,
                    epsilon: float = DEFAULT_EPSILON) -> tuple[dict[int, float], set[int]]:
    p: dict[int, float] = {}
    r: dict[int, float] = {seed: 1.0}
    degree_cache: dict[int, float] = {}
    pushed_from: set[int] = set()

    queue: deque[int] = deque([seed])
    in_queue = {seed}
    pushes = 0

    while queue and pushes < MAX_PUSHES:
        u = queue.popleft()
        in_queue.discard(u)
        du = _weighted_degree(g, u, degree_cache)
        if r.get(u, 0.0) / du <= epsilon:
            continue

        pushes += 1
        newly_active = _push(g, u, p, r, alpha, degree_cache)
        pushed_from.add(u)

        for v in newly_active:
            dv = _weighted_degree(g, v, degree_cache)
            if r.get(v, 0.0) / dv > epsilon and v not in in_queue:
                queue.append(v)
                in_queue.add(v)

    return p, pushed_from

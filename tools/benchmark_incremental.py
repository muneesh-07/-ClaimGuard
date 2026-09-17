#!/usr/bin/env python3
"""
M9: measures the actual speedup local-push approximate PPR
(app/local_push.py) buys over the full-rebuild path (rebuilding the
whole graph and rerunning the complete k-core -> Leiden -> global-PPR
detector ladder, app/detector.py's detect()) for scoring ONE new claim,
at increasing graph sizes. This is the real motivation for local-push:
a claim arriving after the cached graph was last built currently costs
a full rebuild (see app/scoring.py's refresh() and
scoring/consumer.py's fallback) - local-push is the M9 answer to how
that gets cheap.

Builds graphs in memory (bypassing Postgres/COPY entirely) at each
scale - this benchmark is about algorithmic scaling, not ETL, which is
already measured in M4 (tools/load_bulk.sh).

local-push's work is a LOCAL property of whichever claim it starts
from, not the graph's total size. Two different claims can have very
different costs even at the SAME scale: an ordinary background claim
sits next to large, diffuse shared entities (a common shop, a common
area code) where residual mass dilutes fast and the push stops within
a few hops; a fraud-ring member sits in a small, tightly-connected
neighbourhood where mass stays concentrated and the push reaches
further before decaying below epsilon. Both are still bounded and both
are still independent of the OTHER 10k/50k/200k background claims that
happen to exist elsewhere in the graph - but averaging the two claim
types together produces a noisy number that looks unstable across
scale for no real reason. So this benchmark samples each category
separately (SAMPLE_SIZE background claims, SAMPLE_SIZE ring-member
claims) at every scale and reports them side by side.

Run with: cd scoring && uv run python ../tools/benchmark_incremental.py
"""

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scoring"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import igraph as ig  # noqa: E402
from gen_rings import make_background_claim, make_ring  # noqa: E402

from app.detector import detect  # noqa: E402
from app.graph import idf_weight  # noqa: E402
from app.local_push import local_push_ppr  # noqa: E402

SAMPLE_SIZE = 20


# Builds an in-memory bipartite claim<->entity graph at the given scale, in the exact same
# shape app.graph.build_graph() produces from Postgres, plus up to SAMPLE_SIZE claim ids of
# each kind ("background", "ring") to seed local-push from - kept separate so the benchmark
# can report each category's cost on its own terms instead of blending two different local
# neighbourhood shapes into one noisy average.
def build_benchmark_graph(
        n_background: int, n_rings: int, seed: int = 42) -> tuple[ig.Graph, dict[str, list[str]]]:
    rng = random.Random(seed)
    background_claims = [make_background_claim(rng) for _ in range(n_background)]
    ring_claims = []
    for i in range(n_rings):
        members, _phone, _shop, _address = make_ring(rng, f"bench-ring-{i}", size=rng.randint(4, 10))
        ring_claims.extend(members)
    claims = background_claims + ring_claims

    rng.shuffle(background_claims)
    rng.shuffle(ring_claims)
    sample_claim_ids = {
        "background": [c.claim_id for c in background_claims[:SAMPLE_SIZE]],
        "ring": [c.claim_id for c in ring_claims[:SAMPLE_SIZE]],
    }

    entity_degree: dict[str, tuple[str, int]] = {}
    edges: list[tuple[str, str]] = []
    for c in claims:
        for entity_type, raw_value in (
                ("PHONE", c.claimant_phone), ("ADDRESS", c.claimant_address), ("SHOP", c.repair_shop_name)):
            if not raw_value:
                continue
            kind, count = entity_degree.get(raw_value, (entity_type, 0))
            entity_degree[raw_value] = (kind, count + 1)
            edges.append((c.claim_id, raw_value))

    claim_names = [c.claim_id for c in claims]
    entity_names = list(entity_degree)
    all_names = claim_names + entity_names
    index_of = {name: i for i, name in enumerate(all_names)}

    g = ig.Graph()
    g.add_vertices(len(all_names))
    g.vs["name"] = all_names
    g.vs["kind"] = ["claim"] * len(claim_names) + ["entity"] * len(entity_names)
    g.vs["entity_type"] = [None] * len(claim_names) + [entity_degree[n][0] for n in entity_names]
    g.vs["canonical_value"] = [None] * len(claim_names) + list(entity_names)
    g.vs["degree_raw"] = [None] * len(claim_names) + [entity_degree[n][1] for n in entity_names]
    g.vs["incident_date"] = [None] * len(all_names)
    g.vs["claim_amount"] = [None] * len(all_names)

    g.add_edges([(index_of[c], index_of[e]) for c, e in edges])
    g.es["weight"] = [idf_weight(entity_degree[e][1]) for _c, e in edges]

    return g, sample_claim_ids


# Runs local-push for every claim id in one category (background or ring) and returns
# mean timing plus mean/min/max of how many vertices got pushed from.
def _benchmark_category(g: ig.Graph, claim_ids: list[str]) -> dict:
    local_push_times = []
    pushed_counts = []
    for claim_id in claim_ids:
        claim_index = g.vs.find(name=claim_id).index
        t0 = time.perf_counter()
        _p, pushed_from = local_push_ppr(g, claim_index)
        local_push_times.append(time.perf_counter() - t0)
        pushed_counts.append(len(pushed_from))

    return {
        "local_push_s": sum(local_push_times) / len(local_push_times),
        "pushed_mean": sum(pushed_counts) / len(pushed_counts),
        "pushed_min": min(pushed_counts),
        "pushed_max": max(pushed_counts),
    }


# Times a full detect() rebuild once, then benchmarks local-push separately for a sample of
# background claims and a sample of ring-member claims on the same graph.
def benchmark_one_scale(n_background: int, n_rings: int) -> dict:
    g, sample_claim_ids = build_benchmark_graph(n_background, n_rings)

    t0 = time.perf_counter()
    detect(g)
    full_rebuild_s = time.perf_counter() - t0

    background_stats = _benchmark_category(g, sample_claim_ids["background"])
    ring_stats = _benchmark_category(g, sample_claim_ids["ring"])

    return {
        "claims": sum(1 for v in g.vs if v["kind"] == "claim"),
        "vertices": g.vcount(),
        "edges": g.ecount(),
        "full_rebuild_s": full_rebuild_s,
        "background": background_stats,
        "ring": ring_stats,
    }


def _format_category(label: str, stats: dict, full_rebuild_s: float) -> str:
    pushed = f"{stats['pushed_mean']:.0f} ({stats['pushed_min']}-{stats['pushed_max']})"
    speedup = full_rebuild_s / stats["local_push_s"] if stats["local_push_s"] > 0 else float("inf")
    return (f"    {label:>10}  local-push {stats['local_push_s']:.4f}s  "
            f"pushed {pushed:>18}  speedup {speedup:.1f}x")


def main() -> None:
    for n_background in (10_000, 50_000, 200_000):
        n_rings = max(1, n_background // 500)
        result = benchmark_one_scale(n_background, n_rings)
        print(f"{n_background:>10,} background claims, {n_rings} rings -> "
              f"{result['vertices']:,} vertices, {result['edges']:,} edges, "
              f"full rebuild {result['full_rebuild_s']:.3f}s")
        print(_format_category("background", result["background"], result["full_rebuild_s"]))
        print(_format_category("ring", result["ring"], result["full_rebuild_s"]))


if __name__ == "__main__":
    main()

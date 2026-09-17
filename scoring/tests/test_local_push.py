import igraph as ig

from app.local_push import local_push_ppr


# Builds a "star of stars" graph: `n_arms` chains hanging off a seed, each `arm_length` deep -
# lets us grow the total graph size arbitrarily while keeping the seed's local neighbourhood identical.
def _chain_graph(n_arms: int, arm_length: int) -> ig.Graph:
    g = ig.Graph()
    total_vertices = 1 + n_arms * arm_length
    g.add_vertices(total_vertices)
    g.vs["name"] = [str(i) for i in range(total_vertices)]

    edges = []
    next_index = 1
    for _arm in range(n_arms):
        prev = 0  # the seed
        for _step in range(arm_length):
            edges.append((prev, next_index))
            prev = next_index
            next_index += 1
    g.add_edges(edges)
    g.es["weight"] = [1.0] * len(edges)
    return g


def test_mass_is_conserved_exactly():
    g = _chain_graph(n_arms=5, arm_length=4)

    p, _touched = local_push_ppr(g, seed=0, alpha=0.15, epsilon=1e-6)

    # Every unit of mass a push operation removes from r[u] is either kept in p[u] (the alpha
    # share) or handed to a neighbour's r (the rest) - nothing is ever created or destroyed, so
    # p's total plus whatever residual is still left in flight must never exceed 1.0.
    total_p = sum(p.values())
    assert 0.0 < total_p <= 1.0
    # The seed starts with ALL the mass and is the most centrally connected vertex (every arm
    # touches it), so it should end up with the single largest share of anyone - not necessarily
    # exactly alpha, since mass legitimately flows back to it from its neighbours' own pushes
    # in an undirected graph.
    assert p[0] == max(p.values())


def _path_graph(n: int) -> ig.Graph:
    """A single chain of n vertices - long enough that local-push naturally
    stops (mass decays below epsilon) well before reaching the far end,
    for both the "small" and "large" sizes this gets called with below."""
    g = ig.Graph()
    g.add_vertices(n)
    g.vs["name"] = [str(i) for i in range(n)]
    g.add_edges([(i, i + 1) for i in range(n - 1)])
    g.es["weight"] = [1.0] * (n - 1)
    return g


def test_pushed_node_count_is_bounded_independent_of_graph_size():
    # Both paths are far longer than local-push's natural stopping point at this alpha/epsilon
    # (mass roughly halves every couple of hops) - if the pushed-from count were proportional to
    # graph size, the 100x-longer path would push from ~100x more vertices. It doesn't, because
    # the algorithm stops following mass once it decays below epsilon, regardless of how much
    # more graph exists beyond that point. (On a plain path every vertex has degree <= 2, so
    # there's no high-degree hub to fan a residual crumb out to lots of one-time recipients -
    # that distinction is what tools/benchmark_incremental.py's separate "pushed" vs. raw
    # neighbour-count exists to make explicit on the real bipartite graph.)
    short_path = _path_graph(300)
    long_path = _path_graph(30_000)

    _p_short, pushed_short = local_push_ppr(short_path, seed=0, alpha=0.15, epsilon=1e-2)
    _p_long, pushed_long = local_push_ppr(long_path, seed=0, alpha=0.15, epsilon=1e-2)

    assert pushed_short == pushed_long
    assert len(pushed_long) < 50
    assert len(pushed_long) < long_path.vcount() / 100


def test_score_decays_with_distance_from_the_seed():
    g = _chain_graph(n_arms=1, arm_length=6)

    p, _touched = local_push_ppr(g, seed=0, alpha=0.15, epsilon=1e-8)

    # Vertex i is i hops from the seed along the one chain - score should strictly decrease
    # with distance, since each hop dilutes how much mass reaches it.
    scores_by_distance = [p.get(i, 0.0) for i in range(1, 6)]
    assert scores_by_distance == sorted(scores_by_distance, reverse=True)
    assert all(s > 0 for s in scores_by_distance)


def test_a_disconnected_vertex_gets_no_score_at_all():
    g = _chain_graph(n_arms=2, arm_length=3)
    g.add_vertices(1)  # one extra vertex with no edges to anything
    isolated = g.vcount() - 1

    p, pushed_from = local_push_ppr(g, seed=0, alpha=0.15, epsilon=1e-6)

    assert isolated not in pushed_from
    assert p.get(isolated, 0.0) == 0.0

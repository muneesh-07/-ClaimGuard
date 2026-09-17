"""Shared test helper for building small synthetic graphs in the same
shape app.graph.build_graph() produces, without needing a real database."""

from datetime import date

import igraph as ig

from app.graph import idf_weight


def make_bipartite_graph(claim_entity_edges: list[tuple[str, str]],
                          dates: dict[str, date] | None = None,
                          entity_types: dict[str, str] | None = None,
                          amounts: dict[str, float] | None = None) -> ig.Graph:
    dates = dates or {}
    entity_types = entity_types or {}
    amounts = amounts or {}
    claim_names = sorted({c for c, _e in claim_entity_edges})
    entity_names = sorted({e for _c, e in claim_entity_edges})
    all_names = claim_names + entity_names
    index_of = {name: i for i, name in enumerate(all_names)}

    entity_degree = {e: sum(1 for _c2, e2 in claim_entity_edges if e2 == e) for e in entity_names}

    g = ig.Graph()
    g.add_vertices(len(all_names))
    g.vs["name"] = all_names
    g.vs["kind"] = ["claim"] * len(claim_names) + ["entity"] * len(entity_names)
    g.vs["incident_date"] = [dates.get(c) for c in claim_names] + [None] * len(entity_names)
    g.vs["claim_amount"] = [amounts.get(c, 0.0) for c in claim_names] + [None] * len(entity_names)
    g.vs["entity_type"] = [None] * len(claim_names) + [entity_types.get(e, "PHONE") for e in entity_names]
    g.vs["canonical_value"] = [None] * len(claim_names) + list(entity_names)
    g.vs["degree_raw"] = [None] * len(claim_names) + [entity_degree[e] for e in entity_names]
    g.add_edges([(index_of[c], index_of[e]) for c, e in claim_entity_edges])
    g.es["weight"] = [idf_weight(entity_degree[e]) for _c, e in claim_entity_edges]
    return g

"""
Builds the bipartite claim<->entity graph this whole detector runs on.
Bipartite, never projected to claim-claim edges - see docs/APPROACH.md
Layer 1 for why: a shop entity touching 1,000 claims would otherwise
become ~500,000 claim-claim edges, and the projected edge would have
thrown away the reason it existed (the explanation IS the bipartite
path, so keeping it is also what makes ExplanationBuilder-style code
trivial instead of needing a second model to reconstruct "why").
"""

import math

import igraph as ig
from sqlalchemy import text
from sqlalchemy.orm import Session


# Fetches every claim<->entity link plus the entity's degree (claim_count) -
# the raw edge list for the bipartite graph.
def _fetch_links(session: Session):
    return session.execute(text("""
        select l.claim_id, l.entity_id, e.entity_type, e.canonical_value, e.claim_count
        from claim_entities l
        join entities e on e.id = l.entity_id
    """)).all()


# Fetches per-claim attributes (amount, incident date) needed for
# suspiciousness scoring, keyed by claim id string.
def _fetch_claim_attributes(session: Session):
    rows = session.execute(text("select id, claim_amount, incident_date from claims")).all()
    return {str(claim_id): (float(amount), incident_date) for claim_id, amount, incident_date in rows}


# The IDF-style hub weight from docs/APPROACH.md Layer 1: an entity shared by 3 claims is
# strong evidence, one shared by 5,000 is almost none - this is what lets Rung 2's
# suspiciousness scoring tell a real ring apart from a busy repair shop.
def idf_weight(entity_degree: int) -> float:
    return 1.0 / math.log(1 + entity_degree) if entity_degree > 0 else 0.0


# Builds the full bipartite graph from Postgres: claim vertices and entity vertices,
# edges weighted by idf_weight(entity degree). Claim vertices carry amount/incident_date
# attributes; entity vertices carry entity_type/canonical_value/degree.
def build_graph(session: Session) -> ig.Graph:
    links = _fetch_links(session)
    claim_attrs = _fetch_claim_attributes(session)

    claim_ids: set[str] = set()
    entity_meta: dict[str, tuple] = {}
    edges: list[tuple[str, str, float]] = []

    for claim_id, entity_id, entity_type, canonical_value, degree in links:
        claim_id_str = str(claim_id)
        entity_id_str = str(entity_id)
        claim_ids.add(claim_id_str)
        entity_meta[entity_id_str] = (entity_type, canonical_value, degree)
        edges.append((claim_id_str, entity_id_str, idf_weight(degree)))

    claim_names = sorted(claim_ids)
    entity_names = sorted(entity_meta)
    all_names = claim_names + entity_names
    index_of = {name: i for i, name in enumerate(all_names)}

    g = ig.Graph()
    g.add_vertices(len(all_names))
    g.vs["name"] = all_names
    g.vs["kind"] = ["claim"] * len(claim_names) + ["entity"] * len(entity_names)
    g.vs["entity_type"] = [None] * len(claim_names) + [entity_meta[n][0] for n in entity_names]
    g.vs["canonical_value"] = [None] * len(claim_names) + [entity_meta[n][1] for n in entity_names]
    g.vs["degree_raw"] = [None] * len(claim_names) + [entity_meta[n][2] for n in entity_names]
    n_entities = len(entity_names)
    g.vs["claim_amount"] = [claim_attrs.get(n, (None, None))[0] for n in claim_names] + [None] * n_entities
    g.vs["incident_date"] = [claim_attrs.get(n, (None, None))[1] for n in claim_names] + [None] * n_entities

    g.add_edges([(index_of[c], index_of[e]) for c, e, _w in edges])
    g.es["weight"] = [w for _c, _e, w in edges]

    return g

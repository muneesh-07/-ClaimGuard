"""
Builds the bipartite claim<->entity graph this whole detector runs on.
Bipartite, never projected to claim-claim edges - see docs/APPROACH.md
Layer 1 for why: a shop entity touching 1,000 claims would otherwise
become ~500,000 claim-claim edges, and the projected edge would have
thrown away the reason it existed (the explanation IS the bipartite
path, so keeping it is also what makes ExplanationBuilder-style code
trivial instead of needing a second model to reconstruct "why").

`as_of` exists for tools/train_model.py's temporal split: passing a
cutoff date restricts the graph to only claims filed on or before that
date, so a claim's graph-derived features (component size, Leiden
community, PPR score, ...) can be computed from a graph that couldn't
have known about claims filed after it - the honest version of "what
would this claim's features have looked like at train time," not "what
do they look like now that the whole dataset, including this claim's
own future ring-mates, exists." See tools/train_model.py's module
docstring for the leak this closes and the measured effect of closing it.
"""

import math
from collections import Counter
from datetime import date

import igraph as ig
from sqlalchemy import text
from sqlalchemy.orm import Session


# Fetches every claim<->entity link, restricted to claims filed on or before `as_of`
# when given. Deliberately does NOT select entities.claim_count - that column is a
# GLOBAL running total across every claim ever linked to that entity, which is exactly
# the wrong number once `as_of` restricts which claims exist in this graph (see
# build_graph: degree is recomputed from the edges actually returned here instead).
def _fetch_links(session: Session, as_of: date | None = None):
    query = """
        select l.claim_id, l.entity_id, e.entity_type, e.canonical_value
        from claim_entities l
        join entities e on e.id = l.entity_id
        join claims c on c.id = l.claim_id
    """
    params: dict = {}
    if as_of is not None:
        query += " where c.incident_date <= :as_of"
        params["as_of"] = as_of
    return session.execute(text(query), params).all()


# Fetches per-claim attributes (amount, incident date) needed for suspiciousness
# scoring, keyed by claim id string - same `as_of` restriction as _fetch_links, so a
# graph built with a cutoff never gains a claim vertex through this path that
# _fetch_links already excluded (or vice versa).
def _fetch_claim_attributes(session: Session, as_of: date | None = None):
    query = "select id, claim_amount, incident_date from claims"
    params: dict = {}
    if as_of is not None:
        query += " where incident_date <= :as_of"
        params["as_of"] = as_of
    rows = session.execute(text(query), params).all()
    return {str(claim_id): (float(amount), incident_date) for claim_id, amount, incident_date in rows}


# The IDF-style hub weight from docs/APPROACH.md Layer 1: an entity shared by 3 claims is
# strong evidence, one shared by 5,000 is almost none - this is what lets Rung 2's
# suspiciousness scoring tell a real ring apart from a busy repair shop.
def idf_weight(entity_degree: int) -> float:
    return 1.0 / math.log(1 + entity_degree) if entity_degree > 0 else 0.0


# Builds the bipartite graph from Postgres: claim vertices and entity vertices, edges
# weighted by idf_weight(entity degree). Claim vertices carry amount/incident_date
# attributes; entity vertices carry entity_type/canonical_value/degree. With `as_of`
# given, only claims filed on or before that date exist in the graph at all - see the
# module docstring.
def build_graph(session: Session, as_of: date | None = None) -> ig.Graph:
    links = _fetch_links(session, as_of)
    claim_attrs = _fetch_claim_attributes(session, as_of)

    claim_ids: set[str] = set()
    entity_meta: dict[str, tuple] = {}
    edges_raw: list[tuple[str, str]] = []

    for claim_id, entity_id, entity_type, canonical_value in links:
        claim_id_str = str(claim_id)
        entity_id_str = str(entity_id)
        claim_ids.add(claim_id_str)
        entity_meta[entity_id_str] = (entity_type, canonical_value)
        edges_raw.append((claim_id_str, entity_id_str))

    # Degree = how many of THESE (possibly as_of-restricted) edges actually touch this
    # entity - not a value trusted from the database, see _fetch_links.
    degree = Counter(entity_id for _claim_id, entity_id in edges_raw)

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
    g.vs["degree_raw"] = [None] * len(claim_names) + [degree[n] for n in entity_names]
    n_entities = len(entity_names)
    g.vs["claim_amount"] = [claim_attrs.get(n, (None, None))[0] for n in claim_names] + [None] * n_entities
    g.vs["incident_date"] = [claim_attrs.get(n, (None, None))[1] for n in claim_names] + [None] * n_entities

    g.add_edges([(index_of[c], index_of[e]) for c, e in edges_raw])
    g.es["weight"] = [idf_weight(degree[e]) for _c, e in edges_raw]

    return g

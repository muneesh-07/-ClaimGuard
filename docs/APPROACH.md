# ClaimGuard — Approach, Datasets, and Build Order

Research notes and design decisions for the fraud-ring detection + auditable
workflow system. Written after reviewing the published literature on
network-based insurance fraud detection and auditing the current scaffold.

---

## 1. One correction to the framing, before anything else

The problem statement says single-claim scoring is what "basically everything
else in this space, from academic papers to prototype apps" does. That is true
of Kaggle notebooks and student projects. It is **not** true of the insurance
industry or of academia — network-based insurance fraud detection is a
well-established line of work:

- Šubelj, Furlan & Bajec (2011), *An expert system for detecting automobile
  insurance fraud using social network analysis* — builds a collision network of
  participants and vehicles, detects groups with an Iterative Assessment
  Algorithm ([arXiv:1104.3904](https://arxiv.org/abs/1104.3904)).
- Van Vlasselaer et al. (2017), *GOTCHA!* — guilt-by-association propagation for
  social-security fraud rings.
- Óskarsdóttir et al. (2022), *Social Network Analytics for Supervised Fraud
  Detection in Insurance*, *Risk Analysis*
  ([arXiv:2009.08313](https://arxiv.org/abs/2009.08313)) — the closest
  methodological match to this project.
- Commercial products (Neo4j GDS, Linkurious, SAS) ship insurance fraud-ring
  templates, and there are granted US patents on vehicle fraud-ring
  identification.

**Why this matters:** claiming novelty here is the one thing an insurtech
interviewer would catch immediately, and it would cost more credibility than the
claim buys. The defensible positioning is stronger anyway:

> Fraud rings are where the loss concentration is, and the published methods for
> finding them are network-based — but they are hard to operate: they produce
> false positives on legitimate hubs, they don't explain themselves, and they
> don't come with the audit trail that financial-services AI regulation now
> expects. ClaimGuard implements a known-good method *correctly* and wraps it in
> a regulator-grade audit trail end to end.

That is a project about engineering judgement, which is exactly what a fresher
portfolio should be demonstrating. "I invented a new algorithm" is not.

The regulatory half of the framing, by contrast, holds up and is *strengthening*:
insurance AI that affects claims outcomes is high-risk under EU AI Act Annex III
(obligations phasing in through August 2026), and the NAIC Model Bulletin on the
Use of AI Systems by Insurers (adopted Dec 2023) has been taken up by ~25 US
state regulators. Both demand documented decisions, traceability to a model
version, human-override logging, and retained evidence. Build to that and the
audit log stops being a nice-to-have.

---

## 2. The right way to solve it — four layers

The instinct in the problem statement ("claims are nodes, shared entities create
edges") is directionally right but gets two things backwards that matter a lot.
Here is the method that the literature converges on.

### Layer 0 — Entity resolution (skipped by everyone; where this project lives or dies)

You cannot create an edge on "same phone number" with string equality. Real
intake data contains `+91-9876500011`, `9876500011`, `098765 00011`,
`+91 98765 00011`. Addresses are far worse. Repair shop names come in as
`SpeedFix Auto Works`, `Speedfix Auto`, `SPEEDFIX AUTOWORKS PVT LTD`.

With naive equality your graph has almost no edges, ring recall collapses, and
you will never know why. So, before any graph:

1. **Phone** → normalise to E.164. `libphonenumber` (Java) / `phonenumbers`
   (Python). Exact match after normalisation is fine.
2. **Address** → lowercase, strip punctuation, expand abbreviations
   (`rd`→`road`), extract and pin on the postal code, then fuzzy-match within
   postal code using `rapidfuzz.token_set_ratio` above a tuned threshold.
   Postal code is the **blocking key** — it turns an O(n²) comparison into
   O(n · block size).
3. **Shop / garage name** → strip legal suffixes (`pvt ltd`, `& sons`), collapse
   whitespace, fuzzy-match within city.
4. Emit a canonical **entity ID** per resolved real-world thing, and persist the
   claim→entity mapping.

This is cheap to build, it is the difference between a graph and a pile of
strings, and "I implemented blocking + fuzzy entity resolution so the edges are
real rather than string-equality artifacts" is a genuinely good answer to
"what was the hard part?"

### Layer 1 — Build a *bipartite* graph, not a claim–claim graph

Model it as **claims ↔ entities**, with an edge when a claim references an
entity. Do **not** project it down to claim–claim edges. Three reasons, in order
of importance:

- **Size.** A repair shop appearing on 500 claims produces 500 bipartite edges,
  but 500 × 499 / 2 ≈ 125,000 claim–claim edges. Projection is quadratic in hub
  degree and it will dominate everything else you do. This is the single biggest
  efficiency decision in the project, and it is structural — not a tuning knob.
- **Explainability is free.** The path `claim A — [phone:+919876500011] — claim B`
  *is* the explanation. A projected edge has thrown away the reason it exists,
  and you would have to reconstruct it for the audit log.
- **Hub weighting.** Bipartite keeps entity degree visible, which you need for
  the next point.

**Weight edges inversely by entity degree.** An edge through a phone number seen
on 3 claims is strong evidence. An edge through a garage seen on 5,000 claims is
almost no evidence — it is a busy business. Use an IDF-style weight:

```
w(claim, entity) = 1 / log(1 + degree(entity))
```

Skipping this is the classic failure mode: every large repair shop gets reported
as a fraud ring, investigators lose trust in the tool in week one, and the
project's own stated goal (precision over recall) is lost. Mention this trade-off
explicitly in the README — it is a design decision to defend, not a detail.

### Layer 2 — Ring detection as a ladder of three scores

Don't pick one algorithm; run a cheap-to-expensive ladder and record which rung
fired, because that also becomes part of the explanation.

1. **k-core / connected components on the pruned, weighted graph.** Catches
   blatant rings for almost no compute. Caveat: plain weakly-connected components
   on a graph with hubs gives you one giant component containing everything.
   Prune entities above a degree threshold first, or use k-core to strip the
   periphery, then look at what survives.
2. **Community detection — Leiden (prefer it over Louvain).** Traag et al. (2019)
   showed Louvain can return internally *disconnected* communities; Leiden
   guarantees well-connected ones. Use `leidenalg` + `python-igraph`. Then score
   each community for **suspiciousness** rather than treating its existence as
   the signal:
   - internal density vs. a configuration-model null expectation (is this
     tighter than chance? — directly answers the problem statement's
     "more than random chance would explain")
   - entity-sharing ratio: distinct claimants ÷ distinct entities (a ring has
     many "people" sharing few real entities — this ratio is the ring
     fingerprint)
   - temporal burstiness: rings file in clusters, not uniformly
   - claim-amount concentration and just-under-threshold amounts
3. **Guilt-by-association propagation — personalized PageRank / BiRank seeded on
   known-fraud claims.** This is the Óskarsdóttir recipe and it fixes the gap the
   first two rungs leave: most suspicious claims are not in a tidy dense cluster,
   they are *near* one. It also produces a continuous **per-claim** score, which
   is what the Java workflow actually needs to act on.

Then, if you have labels: **network features + claim features → LightGBM/XGBoost
+ SHAP.** The published finding is that the combination beats either feature set
alone, and it buys you calibrated probabilities, precision@k evaluation, and
per-claim attribution for the audit record.

**Skip the GNN for v1.** Label scarcity, explainability cost (you'd then need
GNNExplainer to recover what the bipartite path gave you for free), and the
tabular+network-features model is the documented strong baseline. List it as a
future extension. "I chose the simpler model and here is why" reads better than
a half-converged GCN.

### Layer 3 — Optional stretch: camouflage-resistant dense blocks

**FRAUDAR** (Hooi et al., KDD 2016,
[paper](https://bhooi.github.io/papers/fraudar_kdd16.pdf)) detects dense
bipartite blocks under a suspiciousness metric that provably cannot be decreased
by adding "camouflage" edges to legitimate targets. It is greedy peeling, roughly
200 lines, and it directly answers "what if the ring pads itself with normal-
looking claims?" Good stretch goal with a strong citation. Not P0.

---

## 3. Datasets — the honest answer

**No public insurance claims dataset contains the shared-entity columns this
project needs.** Verified:

| Dataset | Size | Has ring structure? |
|---|---|---|
| Kaggle `insurance_claims.csv` (auto, `fraud_reported`) | 1,000 rows, 39 cols | **No.** One row per distinct policy; `incident_location` is free text and effectively unique. No repeated entities → no edges. |
| Kaggle Vehicle Claim Fraud Detection (`carclaims`, Angoss) | 15,420 rows | **No.** Categorical attributes only, no entity identifiers at all. |
| IEEE-CIS Fraud Detection | 590k txns | Card transactions, not insurance. Usable as a *graph-method* sanity check only. |

Anyone reporting "graph fraud detection on the Kaggle auto insurance dataset" is
running community detection over edges that do not exist. Worth knowing — it is
also a differentiator you can state.

### Use these three, in this order

**1. iFraudSimulator — the credible primary dataset.**
Campo & Antonio, *An engine to simulate insurance fraud network data*, European
Actuarial Journal (2024) — [arXiv:2308.11659](https://arxiv.org/abs/2308.11659),
code at [github.com/BavoDC/iFraudSimulator](https://github.com/BavoDC/iFraudSimulator).

A peer-reviewed R simulation engine that generates claims **together with the
social network of parties involved** (policyholders, brokers, experts, garages),
with controllable numbers of policyholders and parties, a controllable
fraud-generating model, and a controllable class-imbalance level. It exists
precisely because real fraud-network data is confidential and no public benchmark
exists — i.e. it is the published answer to your dataset problem.

Using it signals that you read the literature rather than grabbing the first
Kaggle CSV. You need R exactly once; containerise it and never think about R
again:

```bash
docker run --rm -v "$PWD/data:/out" rocker/r-ver:4.4.1 Rscript -e '
  install.packages("devtools", repos="https://cloud.r-project.org");
  devtools::install_github("BavoDC/iFraudSimulator", dependencies=TRUE);
  library(iFraudSimulator);
  # see vignette("iFraudSimulator") for the generator signature + parameters
  # write the claim table and the party/edge table out as CSV:
  # write.csv(<claims>, "/out/claims.csv", row.names=FALSE)
  # write.csv(<parties>, "/out/parties.csv", row.names=FALSE)
'
```

Then load the CSVs into Postgres and the rest of the project is pure Java/Python.

**2. Kaggle Healthcare Provider Fraud Detection — the real-data validation set.**
[`rohitrox/healthcare-provider-fraud-detection-analysis`](https://www.kaggle.com/datasets/rohitrox/healthcare-provider-fraud-detection-analysis)
— real Medicare inpatient/outpatient/beneficiary claims, ~558k claims across
5,410 providers, of which 506 carry a `PotentialFraud` label (≈9:1 imbalance).

Crucially it has genuine cross-claim entity structure: `Provider`, `BeneID`,
`AttendingPhysician`, `OperatingPhysician`, `OtherPhysician`. Physicians shared
across providers and beneficiaries shared across providers are exactly the
"unrelated claims secretly connected" pattern, on real data, with real labels.

Note the labels are at **provider** level, not claim level. That suits this
project: it validates *ring/cluster* detection rather than per-claim
classification. Being able to say "my ring detector, trained on nothing,
recovers the labelled fraudulent providers at X precision on real Medicare data"
is the strongest single number you can put on the resume.

**3. Your own ring generator — for the demo and for the precision/recall curve.**
A small Python/Faker generator that plants N rings with **known membership**, so
you have ground truth. Make these tunable, because each one is a talking point:

- ring size distribution, and entity-sharing density within a ring
- **camouflage level**: how many legitimate-looking claims each ring also files
- **background collision rate**: legitimate people *do* share a repair shop and
  *do* live at the same address. If your generator has zero background
  collisions your precision number is meaningless and an interviewer will say so.

State plainly in the README that the data is simulated and why (real
fraud-network data is confidential; cite the paper). Disclosed synthetic data is
a strength; undisclosed synthetic data is the thing that sinks the interview.

---

## 4. Review of the current scaffold

What's here — `Claim`, `ClaimStatus`, `ClaimRequest`, `ClaimController`,
`ClaimRepository`, Postgres in Compose, actuator — is clean, minimal, correctly
layered for step 2, and the comments already anticipate the graph work. Good
base. Gaps to close, roughly in order of how much they matter:

**Schema / persistence**

1. **No entity tables.** This is the big one. Add:
   ```
   entities(id, entity_type, canonical_value, first_seen_at, claim_count)
   claim_entities(claim_id, entity_id, role, raw_value)
   ```
   Unique index on `(entity_type, canonical_value)`; index `claim_entities` both
   ways. Without this, entity resolution has nowhere to live, graph construction
   re-parses strings on every run, and there is no cheap way to answer "has this
   phone appeared before" — which is the hot-path query.
2. **Move to Flyway now, drop `ddl-auto: update`.** The config comment says
   you'd switch "before anything resembling production" — do it before the audit
   table exists, because migrating an append-only table later is annoying, and
   because a reviewer reads migrations as production maturity. One dependency,
   one `V1__init.sql`.
3. **Index the linking columns** — `claimant_phone`, `claimant_address`,
   `repair_shop_name` (and the normalised forms). Already flagged in the
   efficiency notes; just make sure it's in the migration, not ad hoc.
4. **Add `@Version` to `Claim`** for optimistic locking. Two adjusters acting on
   one claim currently produces a silent lost update. Three lines, and it's the
   kind of thing that gets noticed.
5. Store normalised values alongside raw: keep the raw string for the audit
   trail, and the canonical form for matching. Never overwrite what the claimant
   actually typed — an auditor may need it.

**The audit log — make this the standout feature**

6. ```
   claim_audit_events(
     id, claim_id, seq, event_type, from_status, to_status,
     actor_id, actor_role, reason,
     fraud_score, ring_id, explanation_json, model_version,
     occurred_at, prev_hash, hash
   )
   ```
   Two details turn this from a log table into the project's headline:
   - **Hash chain.** `hash = sha256(prev_hash || canonical_json(this_row))`.
     Now the log is *tamper-evident*: altering or deleting a past decision breaks
     the chain, and a `GET /api/claims/{id}/audit/verify` endpoint can prove
     integrity on demand. ~20 lines of code.
   - **Append-only, enforced by the database.** A `BEFORE UPDATE OR DELETE`
     trigger that raises an exception, not just a code convention.

   `model_version` and `explanation_json` being mandatory on every scoring event
   is what closes the regulatory loop: claim → score → which model produced it →
   which shared entities justified it → who acted on it and why.

**Application structure**

7. **Introduce `ClaimService`** before step 3. The controller currently calls the
   repository directly, which is fine today but the status transition + audit
   write must be one `@Transactional` unit — partial writes here are exactly the
   failure that makes an audit trail worthless.
8. **Model the workflow as an explicit state machine**, not `if` statements: a
   table or enum map of legal `(from, to)` transitions, and reject illegal ones
   with a 409. Then "claims cannot skip review" is provable rather than
   incidental.
9. **Don't return the JPA entity from the controller** — add a `ClaimResponse`
   record. Returning entities leaks the schema into the API and couples the two.
10. **Add `@ControllerAdvice` returning Spring 6 `ProblemDetail`** (RFC 7807).
    Validation failures currently surface as default Boot error bodies.
11. **RBAC is in the README but absent from the code.** The audit trail needs a
    real actor to be worth anything. Spring Security with roles
    `ADJUSTER` / `INVESTIGATOR` / `AUDITOR` (auditor = read-only, including the
    audit log). Every audit row records the authenticated principal.
12. **Testcontainers for Postgres.** The only test today is the context-load
    test, and the README notes the scaffold was never actually built. A
    Testcontainers integration test that posts a claim, drives it through the
    workflow, and verifies the hash chain makes the whole thing demonstrably
    real. High signal per line of code.

**Async path**

13. **Use the transactional outbox pattern** for `ClaimSubmitted`. Writing the
    claim and publishing to Kafka are two systems; do it naively and a crash
    between them loses the scoring trigger silently. Insert an `outbox` row in
    the same transaction as the claim, then a poller publishes and marks it sent.
    Named, recognised pattern — cheap to implement, disproportionately good to
    be able to explain.
14. **Make the Python consumer idempotent** (dedupe on claim id + model version).
    At-least-once delivery means you *will* score the same claim twice.

---

## 5. Efficiency — sharpening the levers

The levers in the problem statement are the right ones. Three upgrades:

**"Only update the local neighbourhood" has a name and a citation.** The
technique is **local-push approximate personalized PageRank** —
Andersen, Chung & Lang (2006), *Local Graph Partitioning using PageRank Vectors*,
and the PageRank-Nibble procedure. It computes an ε-approximate PPR vector while
touching only O(1/ε) nodes, **independent of total graph size**. So a new claim
pushes locally from its own node; nothing global is recomputed. Being able to
name the algorithm and its complexity bound is worth far more in an interview
than "I only update the affected part."

**Hybrid schedule: nightly global pass + real-time local pass.** Leiden is a
global algorithm and is not meaningfully incremental — don't pretend otherwise.
Run it nightly over the whole graph to assign/refresh ring IDs, and serve
per-claim scoring in real time from the local PPR path against the last good
partition. This is how production systems are actually structured, and saying so
is a credible architecture answer.

**Use igraph, not NetworkX.** NetworkX is pure Python and becomes the bottleneck
well before a million edges; `python-igraph` is C-backed and is typically one to
two orders of magnitude faster on community detection. Keep Postgres as the
source of truth and materialise the in-memory graph from `claim_entities`.

**Redis, used specifically.** Cache (a) entity → list of claim IDs (the postings
list you hit constantly), and (b) the computed ring verdict per component, keyed
by ring ID + graph version. Invalidate on the nightly pass. Vague "add Redis for
caching" is weaker than naming the two keys.

**Make precision a budget, not an adjective.** Evaluate with **precision@k** and
**lift in the top 1% / 5%**, and frame k as the investigator's daily capacity:
"one investigator reviews ~50 claims/day; at k=50 our precision is X%, versus Y%
for a single-claim baseline." That sentence is the difference between a Kaggle
notebook and a system. Also report the recall you gave up, on purpose, with the
reason.

---

## 6. Build order (and what to cut)

The real risk for a portfolio project is not finishing. Priorities:

**P0 — the spine. Without all of this there is no project.**
- Flyway migrations; entity + `claim_entities` tables; indexes
- Entity resolution (phone E.164, address blocking + fuzzy, shop normalisation)
- Bipartite graph, IDF hub weighting, Leiden + community suspiciousness scoring
- Workflow state machine in a transactional `ClaimService`
- Hash-chained, DB-enforced append-only audit log + `/audit/verify`
- Kafka async scoring via outbox; idempotent consumer; versioned explanation JSON
- Synthetic ring generator **with ground-truth ring membership**
- README with one screenshot of a detected ring and real measured numbers

**P1 — the credibility layer.**
- RBAC (adjuster / investigator / auditor) wired into audit actors
- Testcontainers integration test covering workflow + chain verification
- Evaluation harness: precision@k, lift, ring-level recall, p95 scoring latency
- Local-push PPR incremental path, benchmarked against full rebuild
- iFraudSimulator data loaded and scored

**P2 — only if P0 and P1 are done.**
- LightGBM + SHAP supervised layer on network + claim features
- Validation against the real Medicare provider-fraud dataset
- Redis caches; FRAUDAR; GNN; graph visualisation front end

On the front end: a single page rendering a detected ring with labelled
shared-entity edges (cytoscape.js or vis-network) is the highest-ROI optional
item in the whole list, because one screenshot of a real detected ring in the
README communicates the entire project in two seconds. But it is still P2 — it
is worthless without P0 behind it.

**What the README must contain when you're done**, because this is what actually
gets read: the one-sentence problem, the architecture diagram, one ring
screenshot, a table of measured numbers (ring recall, precision@k, p95 latency,
local-update speedup vs. full rebuild), the precision/recall trade-off stated as
a deliberate choice, and a plain sentence that the data is simulated and why.

---

## References

- Šubelj, Furlan & Bajec (2011). *An expert system for detecting automobile insurance fraud using social network analysis.* [arXiv:1104.3904](https://arxiv.org/abs/1104.3904)
- Óskarsdóttir et al. (2022). *Social Network Analytics for Supervised Fraud Detection in Insurance.* Risk Analysis. [arXiv:2009.08313](https://arxiv.org/abs/2009.08313)
- Campo & Antonio (2024). *An engine to simulate insurance fraud network data.* European Actuarial Journal. [arXiv:2308.11659](https://arxiv.org/abs/2308.11659) · [code](https://github.com/BavoDC/iFraudSimulator)
- Hooi et al. (2016). *FRAUDAR: Bounding Graph Fraud in the Face of Camouflage.* KDD. [PDF](https://bhooi.github.io/papers/fraudar_kdd16.pdf)
- Andersen, Chung & Lang (2006). *Local Graph Partitioning using PageRank Vectors.* FOCS.
- Traag, Waltman & van Eck (2019). *From Louvain to Leiden: guaranteeing well-connected communities.* Scientific Reports.
- Neo4j. [*Detecting Insurance Fraud Using Graph Algorithms*](https://neo4j.com/developer/snowflake-analytics/neo4j-insurance-fraud/)
- Kaggle. [*Healthcare Provider Fraud Detection Analysis*](https://www.kaggle.com/datasets/rohitrox/healthcare-provider-fraud-detection-analysis)

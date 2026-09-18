# ClaimGuard

Insurance claims fraud detection that looks **across** claims instead of at one
claim at a time, and keeps a tamper-evident audit trail of every decision.

Most fraud scoring asks "does this single claim look suspicious?" That misses
organised fraud rings — groups of claims that look unrelated on paper (different
names, different dates) but are connected through shared details: the same phone
number, the same address, the same repair shop. ClaimGuard builds a graph of
claims and the entities they share, finds clusters that are more tightly
connected than chance explains, and records *why* it flagged each one in an
append-only, hash-chained audit log that an auditor can verify.

> **Status: in active development.** The milestone table below is the honest
> state of things. Numbers go in this README when they have actually been
> measured — there are no placeholder metrics here.

## Why two services

| | Owns | Stack |
|---|---|---|
| `backend/` | Claim intake, workflow state machine, RBAC, the audit log. The source of truth. | Java 21, Spring Boot 3.5, Postgres, Flyway, Kafka |
| `scoring/` | Entity graph construction, fraud-ring detection, explanations. | Python, FastAPI, igraph, leidenalg |

Java owns correctness and auditability; Python owns the exploratory graph and ML
work. They communicate over a versioned HTTP contract and Kafka events, and the
Python service holds **read-only** database credentials so "Java owns writes" is
enforced by Postgres rather than by convention.

## AI / ML components

Three layers, cheapest-and-most-certain first:

1. **Rule-based ring detector** (`scoring/app/detector.py`) — k-core components →
   Leiden community detection → personalized PageRank, run in that order as a
   cheap-to-expensive ladder. `make eval` reports ring-level recall and
   precision@k against the planted ground truth.
2. **Trained ring classifier** (`scoring/app/model.py`, `tools/train_model.py`) —
   a calibrated XGBoost model over graph-derived features (k-core, Leiden,
   PPR, IDF hub weighting, 2-hop aggregation) plus the tabular claim fields,
   explained per-prediction with real SHAP attributions. `make train-model`
   reports a measured ablation: **AUPRC 0.0338 (tabular-only, no graph) →
   0.8907 (+ graph features)** — the actual, measured case for why this is a
   *network*-based detector and not a single-claim scorer. Full report at
   `scoring/models/eval_report.json`.
3. **Investigator narrative** (`scoring/app/narrative.py`) — a **local**
   `llama3.2:3b` model (via [Ollama](https://ollama.com), free, runs on an 8GB
   Apple Silicon laptop) turns a flagged claim's real SHAP + shared-entity
   evidence into a short, investigator-readable sentence, on demand from the
   claim detail view. It never decides anything — fraud_score/ring_id/
   decision_hint are already final by the time a claim reaches it — and every
   narrative is checked against its own evidence before being shown: if it
   mentions a claim id it wasn't given, it's discarded and the deterministic
   template summary is shown instead. `make eval-narrative` measures how often
   that actually happens; on the last run, **20/20 (100%) of real FLAGged
   claims passed the grounding check**, median latency 3.2s / p95 5.1s. Full
   report at `scoring/models/narrative_eval_report.json`.

## Layout

```
claimguard/
├── backend/   Spring Boot service — intake, workflow, audit
├── scoring/   FastAPI service — entity graph, ring detection
├── tools/     Data generators, loaders, evaluation harness
├── infra/     docker-compose: Postgres, Kafka, Redis
└── docs/      Design brief, execution plan, scoring contract
```

## Documentation

- **[docs/APPROACH.md](docs/APPROACH.md)** — the method, why it is built this
  way, which datasets can actually support ring detection, and the trade-offs
  being made on purpose.
- **[docs/EXECUTION_PLAN.md](docs/EXECUTION_PLAN.md)** — milestones, checklists,
  and the acceptance test for each one.

## Quick start

Requires JDK 21+ and a working Docker daemon.

```bash
make up        # start Postgres (and later Kafka + Redis)
make run       # start the backend on :8080
curl localhost:8080/api/health
```

Create a claim:

```bash
curl -X POST localhost:8080/api/claims \
  -H 'Content-Type: application/json' \
  -d '{
    "claimantName":    "Asha Menon",
    "policyNumber":    "POL-10021",
    "claimAmount":     45000,
    "incidentDate":    "2026-08-14",
    "claimantPhone":   "+91-9876500011",
    "claimantAddress": "12 Lake View Road, Coimbatore",
    "repairShopName":  "SpeedFix Auto Works"
  }'
```

`make help` lists the rest. The investigator-narrative feature additionally needs
a local [Ollama](https://ollama.com) daemon running with `llama3.2:3b` pulled
(`ollama pull llama3.2:3b`) — everything else works without it.

## Progress

| | Milestone | State |
|---|---|---|
| M0 | Repo, build, toolchain | done |
| M1 | Flyway, service layer, RFC 7807 errors, Testcontainers | done |
| M2 | Entity resolution (phone, address, repair shop) | done |
| M3 | Workflow state machine + hash-chained audit log | done |
| M4 | Synthetic ring data with ground truth | done |
| M5 | Python scoring service + versioned contract | done |
| M6 | Ring detector (k-core → Leiden → personalized PageRank) | done |
| M7 | Async scoring via transactional outbox + Kafka | done |
| M8 | RBAC — adjuster / investigator / auditor | done |
| M9 | Evaluation, efficiency benchmarks, final README | in progress — local-push incremental PPR + benchmark done; fuzzy entity merging, Medicare validation, nightly Leiden job, and the final metrics table are not |
| — | Tier 1: trained XGBoost ring classifier + SHAP, calibrated | done |
| — | Tier 2: local-LLM investigator narrative, grounded + evaluated | done |
| M10 | Ring visualisation | optional |

## A note on data

Real insurance fraud-network data is confidential, and **no public insurance
claims dataset contains the shared-entity columns that ring detection needs** —
the commonly used Kaggle auto-insurance sets have one row per policy and no
repeated entities, so a graph built on them has no real edges.

ClaimGuard is therefore evaluated on (1) **iFraudSimulator**, the peer-reviewed
simulation engine from Campo & Antonio, *An engine to simulate insurance fraud
network data*, European Actuarial Journal 2024
([arXiv:2308.11659](https://arxiv.org/abs/2308.11659)), which generates claims
together with the social network of parties involved; (2) a local generator that
plants rings with known membership so precision and recall can be measured
against ground truth; and (3) the real Medicare provider-fraud dataset for
validation on non-synthetic data. See [docs/APPROACH.md](docs/APPROACH.md) §3.

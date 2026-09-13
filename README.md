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

`make help` lists the rest.

## Progress

| | Milestone | State |
|---|---|---|
| M0 | Repo, build, toolchain | in progress |
| M1 | Flyway, service layer, RFC 7807 errors, Testcontainers | not started |
| M2 | Entity resolution (phone, address, repair shop) | not started |
| M3 | Workflow state machine + hash-chained audit log | not started |
| M4 | Synthetic ring data with ground truth | not started |
| M5 | Python scoring service + versioned contract | not started |
| M6 | Ring detector (k-core → Leiden → personalized PageRank) | not started |
| M7 | Async scoring via transactional outbox + Kafka | not started |
| M8 | RBAC — adjuster / investigator / auditor | not started |
| M9 | Evaluation, efficiency benchmarks, final README | not started |
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

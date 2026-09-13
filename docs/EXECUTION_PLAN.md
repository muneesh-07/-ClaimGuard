# ClaimGuard — Execution Plan

Working checklist. Companion to [`APPROACH.md`](./APPROACH.md), which explains
*why* each of these choices is the right one. This document is only *what to do,
in what order, and how you know it's done.*

**Current state:** Spring Boot skeleton + Postgres + `Claim` CRUD exist. Per the
README, the scaffold was generated in a sandbox that could not reach Maven
Central, so **it has never actually been built or run**, and there is no git
repository yet. That is where we start.

**Rule for every milestone:** it is not done until the tests pass, the commit is
pushed, and the README reflects it. A milestone half-finished and abandoned is
worse than one not started.

---

## Two decisions to make before M0

### D1 — Repository layout · **DECIDED: monorepo**

Done in M0. The previous standalone `claimguard-backend/` directory had no git
history, which made this the cheapest possible moment to restructure. Layout:

```
claimguard/                  ← one repo, one GitHub link, one README
├── backend/                 ← move the current project here unchanged
├── scoring/                 ← Python FastAPI fraud service
├── tools/                   ← data generators, loaders, eval harness
├── infra/                   ← docker-compose, Kafka/Redis/Postgres
└── docs/                    ← APPROACH.md, EXECUTION_PLAN.md, scoring-contract.md
```

Why one repo: a reviewer follows one link and sees the whole system, the two
services visibly talk to each other, and `docker compose up` brings up
everything. Two separate repos means two links, each looking like half a project.
The "separate services" architecture story survives perfectly well inside a
monorepo — the services are separate processes with separate build tooling and a
versioned HTTP/Kafka contract, which is the actual claim.

If you'd rather keep two repos, that's defensible too, but then the root README
of each must link the other and explain the split in its first paragraph.

### D2 — Where entity resolution runs · *recommend: Java, deterministic only, for now*

Deterministic normalisation (phone → E.164, address and shop canonicalisation)
runs in **Java at intake**, in the same transaction as the claim insert, so
`claim_entities` is always consistent with `claims` and Postgres stays the single
source of truth for the graph. Fuzzy/probabilistic merging is deliberately
deferred to M9 as a Python batch job, so it cannot block the spine.

---

## M0 — Make it real · ~0.5 day · **DONE**

Nothing here is fraud detection. Do it anyway; everything else stands on it.

- [ ] Apply D1 (restructure, or consciously decline)
- [ ] `git init`, `.gitignore` check (`target/`, `__pycache__/`, `.env`, `data/`)
- [ ] First commit, create the GitHub repo, push
- [ ] `mvn wrapper:wrapper` so `./mvnw` works for anyone who clones
- [ ] `docker compose up -d` → `./mvnw clean verify` → `./mvnw spring-boot:run`
- [ ] Fix whatever the first real build surfaces (it has never run)
- [ ] Verify Docker is reachable for Testcontainers later. On macOS with Colima
      you will need `DOCKER_HOST` and `TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock`

**Done when:** `GET /api/health` returns `UP`, a `POST /api/claims` round-trips
and comes back from `GET /api/claims`, and the repo is pushed.

**Commit from day one, in small pieces.** A portfolio repo whose entire history
is one "initial commit" of 4,000 lines reads as generated. The commit log is part
of what gets reviewed.

---

## M1 — Foundations: migrations, service layer, errors, test harness · ~1.5 days · **DONE**

- [ ] Add Flyway (`flyway-core` + `flyway-database-postgresql`)
- [ ] `V1__claims.sql` — hand-write the DDL to match the current `Claim` entity
- [ ] Switch `spring.jpa.hibernate.ddl-auto` to **`validate`**
- [ ] `V2__entities.sql`:
      ```sql
      CREATE TABLE entities (
        id             UUID PRIMARY KEY,
        entity_type    TEXT NOT NULL,      -- PHONE | ADDRESS | SHOP
        canonical_value TEXT NOT NULL,
        claim_count    INT  NOT NULL DEFAULT 0,
        first_seen_at  TIMESTAMPTZ NOT NULL,
        UNIQUE (entity_type, canonical_value)
      );
      CREATE TABLE claim_entities (
        claim_id  UUID NOT NULL REFERENCES claims(id),
        entity_id UUID NOT NULL REFERENCES entities(id),
        role      TEXT NOT NULL,
        raw_value TEXT NOT NULL,
        PRIMARY KEY (claim_id, entity_id, role)
      );
      CREATE INDEX ON claim_entities (entity_id);
      CREATE INDEX ON claims (claimant_phone);
      CREATE INDEX ON claims (repair_shop_name);
      ```
- [ ] `@Version private long version;` on `Claim` (optimistic locking)
- [ ] `ClaimResponse` record; stop returning the JPA entity from the controller
- [ ] `ClaimService` — controller no longer touches the repository
- [ ] `GlobalExceptionHandler` (`@ControllerAdvice`) returning `ProblemDetail` (RFC 7807)
- [ ] Testcontainers (`spring-boot-testcontainers`, `postgresql`) + `@ServiceConnection`
- [ ] First integration test: create claim → 201 → fetch it back

**Done when:** `./mvnw verify` starts Postgres in Docker, runs migrations,
passes. A bad payload returns an RFC 7807 body. `ddl-auto: validate` passing is
itself the proof that migrations and entities agree — keep it that way for the
rest of the project.

---

## M2 — Entity resolution and the graph's raw material · ~2 days

- [ ] `libphonenumber` dependency
- [ ] `Normalizer` per type:
      - `PhoneNormalizer` → E.164, default region configurable
      - `AddressNormalizer` → lowercase, strip punctuation, expand `rd`→`road`
        etc., extract postal code, sort tokens
      - `ShopNormalizer` → strip `pvt ltd`/`private limited`/`& sons`, collapse whitespace
- [ ] `EntityService.resolveAndLink(Claim)` — upsert entity
      (`ON CONFLICT (entity_type, canonical_value) DO UPDATE SET claim_count = claim_count + 1`),
      insert `claim_entities`, **in the same transaction as the claim insert**
- [ ] Keep `raw_value` on the link row. Never overwrite what the claimant typed.
- [ ] Table-driven unit tests on each normaliser, with the genuinely messy cases:
      `+91-9876500011` / `9876500011` / `098765 00011` / `+91 98765 00011`
- [ ] `GET /api/entities/{id}/claims` (you will use this constantly while debugging)

**Done when:** posting three claims whose phone numbers are the same number in
three different formats produces **one** `entities` row with `claim_count = 3`,
and the entity endpoint returns all three claims.

This milestone is the one that decides whether the graph has edges at all. Spend
the time on the test table.

---

## M3 — Workflow state machine + hash-chained audit log · ~2.5 days

**This is the project's headline feature. Do not rush it and do not skip it.**

- [ ] `V3__audit.sql`:
      ```sql
      CREATE TABLE claim_audit_events (
        id             UUID PRIMARY KEY,
        claim_id       UUID NOT NULL REFERENCES claims(id),
        seq            INT  NOT NULL,
        event_type     TEXT NOT NULL,     -- CLAIM_CREATED | STATUS_CHANGED | FRAUD_SCORED | HUMAN_OVERRIDE
        from_status    TEXT,
        to_status      TEXT,
        actor_id       TEXT NOT NULL,
        actor_role     TEXT NOT NULL,
        reason         TEXT,
        fraud_score    NUMERIC(5,4),
        ring_id        TEXT,
        explanation_json JSONB,
        model_version  TEXT,
        occurred_at    TIMESTAMPTZ NOT NULL,
        prev_hash      TEXT NOT NULL,
        hash           TEXT NOT NULL,
        UNIQUE (claim_id, seq)
      );
      ```
- [ ] Append-only trigger — enforced by the **database**, not by convention:
      ```sql
      CREATE FUNCTION audit_is_append_only() RETURNS trigger AS $$
      BEGIN RAISE EXCEPTION 'claim_audit_events is append-only'; END;
      $$ LANGUAGE plpgsql;

      CREATE TRIGGER no_mutate BEFORE UPDATE OR DELETE ON claim_audit_events
        FOR EACH ROW EXECUTE FUNCTION audit_is_append_only();
      ```
- [ ] `ClaimTransitions` — the legal transition map, rejecting anything else with 409:

      | From | To | Who | Notes |
      |---|---|---|---|
      | SUBMITTED | UNDER_REVIEW | adjuster, system | |
      | SUBMITTED | FLAGGED | system | fraud score above flag threshold |
      | UNDER_REVIEW | FLAGGED | adjuster | manual escalation |
      | UNDER_REVIEW | APPROVED / DENIED | adjuster | |
      | FLAGGED | UNDER_REVIEW | investigator | flag cleared |
      | FLAGGED | DENIED | investigator | fraud confirmed |
      | FLAGGED | APPROVED | investigator | **human override — `reason` mandatory** |
      | APPROVED / DENIED | — | — | terminal |

- [ ] `AuditService.append(...)`:
      `hash = sha256(prev_hash || canonicalJson(row))`, genesis `prev_hash` = 64 zeros.
      Take the previous row with `SELECT ... FOR UPDATE` (or lock the claim row) so
      concurrent appends cannot interleave and fork the chain.
- [ ] **Canonical JSON must be deterministic** — sorted keys, no insignificant
      whitespace, fixed timestamp format, fixed numeric scale. Write one
      `CanonicalJson` helper and a test asserting two differently-ordered maps
      hash identically. Get this wrong and verification fails mysteriously later.
- [ ] `POST /api/claims/{id}/transitions` `{ "toStatus": "...", "reason": "..." }`
- [ ] `GET /api/claims/{id}/audit` and `GET /api/claims/{id}/audit/verify`
- [ ] Actor comes from a request header stub for now (`X-Actor-Id`, `X-Actor-Role`);
      M8 swaps in the real authenticated principal. One-line change — not a rewrite.
- [ ] Tests: illegal transition → 409 · chain verifies → `{valid:true}` ·
      `FLAGGED → APPROVED` without a reason → 400 ·
      direct SQL `UPDATE` on an audit row → exception

**Done when:** `/audit/verify` returns `{"valid": true, "events": n}`, and trying
to alter a past decision through raw SQL fails at the database.

---

## M4 — Data: generate it, load it, know the ground truth · ~1.5 days

You need data before the detector, and you need **labelled** data or you cannot
report a number.

- [ ] `tools/gen_rings.py` — synthetic claims with planted rings:
      - `--claims 50000 --rings 120`
      - ring size distribution, and entity-sharing density inside a ring
      - `--camouflage` — legitimate-looking claims each ring also files
      - `--background-collision-rate` — **required.** Legitimate people do share
        a repair shop and do live at the same address. With this at zero, your
        precision number is meaningless and a reviewer will say so.
      - emits `claims.csv` **and** `ground_truth_rings.csv` (claim_id → ring_id)
- [ ] Loader: small demo set (~200 claims) goes in through `POST /api/claims` so
      it exercises entity resolution and the audit log; the 50k eval set goes in
      via `COPY` plus a one-off resolution pass, because 50k HTTP calls is a waste
- [ ] iFraudSimulator export (see `APPROACH.md` §3 for the Docker one-liner) plus
      a small mapping script into the ClaimGuard schema

**Done when:** 50k claims are in Postgres with `claim_entities` populated, and
you have a ground-truth file naming every planted ring's membership.

---

## M5 — Python scoring service: contract first, algorithm later · ~1.5 days

Get the two services talking **before** the detector is any good. A stub score
that flows end to end is worth more than a brilliant detector nothing can call.

- [ ] `scoring/` — FastAPI, `uv` or Poetry, `ruff` + `pytest`
- [ ] Read-only Postgres user: `GRANT SELECT` on `claims`, `entities`,
      `claim_entities` only. This *enforces* "Java owns writes" rather than
      merely asserting it, and it is a good detail to be able to point at.
- [ ] `GET /health`, `POST /score/batch` (batch, not one-claim-per-call)
- [ ] Pydantic models for the contract, written down in `docs/scoring-contract.md`:
      ```json
      {
        "claim_id": "…",
        "model_version": "ring-detector-0.1.0",
        "scored_at": "2026-09-13T10:22:31Z",
        "fraud_score": 0.87,
        "decision_hint": "FLAG",
        "ring_id": "ring-8f21",
        "rung": "leiden_community",
        "explanation": {
          "summary": "Shares a phone number and a repair shop with 4 other claims filed within 9 days.",
          "evidence": [
            { "type": "SHARED_ENTITY", "entity_type": "PHONE",
              "entity_value": "+919876500011", "entity_degree": 5,
              "edge_weight": 0.56, "shared_with_claim_ids": ["…"] },
            { "type": "RING_METRIC", "metric": "claimants_per_entity",
              "value": 5.0, "baseline": 1.1 }
          ],
          "thresholds": { "flag_at": 0.75, "tuned_for": "precision" }
        }
      }
      ```
- [ ] `model_version` is **mandatory on every response** and is what the audit
      row records. Bump it whenever the algorithm or a threshold changes.
- [ ] Stub the score (e.g. component size) so the contract can be exercised now
- [ ] Mask entity values in API responses; store the full value in the audit row —
      an auditor needs the real one, a dashboard does not

**Done when:** `POST /score/batch` with three claim ids returns three scored
responses validating against the documented schema.

---

## M6 — The detector · ~4 days

The AI core. Build the rungs in order and keep each one switchable, because you
will want to report what each contributes.

- [ ] Build the bipartite graph with `python-igraph` from `claim_entities`
- [ ] IDF hub weights: `w = 1 / log(1 + degree(entity))`
- [ ] **Rung 1** — prune entities above a degree threshold, then k-core; emit
      surviving components
- [ ] **Rung 2** — `leidenalg` communities, then *suspiciousness* per community:
      - internal density vs. a configuration-model null expectation
      - `distinct_claimants / distinct_entities` (the ring fingerprint)
      - filing-window burstiness
      - claim-amount concentration, and amounts just under a review threshold
- [ ] **Rung 3** — personalized PageRank seeded on known-fraud claims, giving a
      continuous per-claim score for claims that are *near* a ring rather than in one
- [ ] Combine into one `fraud_score`, and record **which rung fired** in `rung`
- [ ] `ExplanationBuilder` — walk the claim's bipartite neighbourhood, take the
      highest-weight shared-entity paths, and emit the `evidence` array. The
      explanation is read off the graph; it is not a separate model.
- [ ] `tools/eval.py` against `ground_truth_rings.csv`: ring-level recall,
      claim-level precision@k, lift at top 1% / 5%, plus the same numbers for a
      single-claim baseline so the comparison is explicit

**Done when:** the eval script prints a numbers table, and the explanation for a
claim in a known planted ring names the actual entity that was planted. Check
that by hand on three rings — if the explanation is wrong, the score is luck.

---

## M7 — Async wiring: the end-to-end demo · ~2 days

This milestone is what makes it a *system*. After this, the project demos.

- [ ] Kafka (single-broker KRaft, no ZooKeeper) and Redis into `docker-compose.yml`
- [ ] `V4__outbox.sql` — `outbox(id, aggregate_id, topic, payload, created_at, sent_at)`
- [ ] **Transactional outbox:** insert the outbox row in the same transaction as
      the claim; a `@Scheduled` poller publishes to `claim.submitted` and stamps
      `sent_at`. Publishing inside the transaction, or after committing without an
      outbox, silently loses scoring triggers on a crash.
- [ ] Python consumer on `claim.submitted` → score → publish `claim.scored`
- [ ] Java consumer on `claim.scored` → append a `FRAUD_SCORED` audit event with
      `explanation_json` + `model_version` → transition to `FLAGGED` or
      `UNDER_REVIEW` per `decision_hint`
- [ ] Idempotency: unique on `(claim_id, model_version)` for scoring events.
      At-least-once delivery means you *will* score the same claim twice.
- [ ] Redis: cache entity → claim-id postings list, and the ring verdict per
      `(ring_id, graph_version)`; invalidate on the nightly pass

**Done when:** `POST /api/claims` returns `201 SUBMITTED` immediately; a few
seconds later `GET /api/claims/{id}` shows `FLAGGED`, and
`GET /api/claims/{id}/audit` contains the scoring event with its explanation,
model version, and an intact hash chain. **Record this as a terminal session or
GIF — it is the single most convincing thing in the repo.**

---

## M8 — RBAC · ~1.5 days

- [ ] Spring Security + JWT. Scope discipline: one `POST /api/auth/login`, a
      `users` table, no registration flow, no refresh tokens.
- [ ] Roles `ADJUSTER`, `INVESTIGATOR`, `AUDITOR` — auditor is read-only,
      including the audit log
- [ ] Audit `actor_id` / `actor_role` now come from the authenticated principal;
      delete the header stub from M3
- [ ] Enforce the transition table's "who" column at the service layer
- [ ] Tests: adjuster approving a `FLAGGED` claim → 403 · investigator → 200 ·
      auditor on any write → 403 · audit rows carry the correct actor

**Done when:** the transition table's authority column is enforced and tested,
and every audit row names a real authenticated actor.

---

## M9 — Efficiency proof, evaluation, README · ~2.5 days

Numbers, not adjectives. This milestone is what a reviewer actually reads.

- [ ] **Local-push approximate personalized PageRank** (Andersen–Chung–Lang) for
      the incremental path: a new claim pushes only within its own neighbourhood
- [ ] Benchmark it against full graph rebuild at 10k / 50k / 200k claims and put
      the speedup in the README as a measured number
- [ ] Nightly global Leiden pass (`@Scheduled` or a cron container) refreshing
      ring IDs; real-time scoring serves from the last good partition
- [ ] Fuzzy entity merging as a Python batch job (the deferred half of D2):
      postal-code blocking + `rapidfuzz.token_set_ratio`, writing merges back
- [ ] Validate against the real Medicare provider-fraud dataset (`APPROACH.md` §3)
- [ ] Final README:
      - [ ] one-sentence problem statement
      - [ ] architecture diagram
      - [ ] one screenshot of a detected ring
      - [ ] measured numbers table: ring recall, precision@k, p95 scoring latency,
            incremental-vs-full speedup
      - [ ] the precision/recall trade-off stated as a deliberate choice, with the
            recall you gave up and why
      - [ ] a plain sentence that the data is simulated, and why, citing the paper

**Done when:** every number in the README is one you measured. No placeholders,
no rounded-up guesses.

---

## M10 — Optional: ring visualisation · ~2 days

Highest return of anything optional, because one screenshot explains the entire
project in two seconds — but worthless without M0–M7 behind it.

- [ ] One page, cytoscape.js or vis-network
- [ ] Claims and entities as distinct node shapes, edges labelled with the shared
      entity type, edge thickness from weight
- [ ] Side panel showing the audit trail for the selected claim

---

## Timeline

| Path | Milestones | Focused days |
|---|---|---|
| **Minimum that tells the whole story** | M0–M7 + the README half of M9 | ~16 |
| **Complete as designed** | M0–M9 | ~20 |
| **With the visualisation** | M0–M10 | ~22 |

Double these if you are working evenings and weekends. If you run out of time,
**stop after M7 and write the README** — a project that ingests a claim, detects
a ring asynchronously, explains the detection, and proves the audit log wasn't
tampered with is complete and impressive. A project with a GNN and no audit trail
is neither.

---

## Tripwires — where the time will actually go

1. **Entity resolution thresholds.** Too loose and unrelated people merge into one
   entity, manufacturing fake rings; too tight and you get no edges. Budget real
   time for the test table in M2, and keep the threshold configurable.
2. **Leiden's resolution parameter** changes community sizes dramatically. Sweep
   it against ground truth in M6 rather than accepting the default, and report the
   value you chose.
3. **Canonical JSON.** Non-deterministic key ordering or timestamp formatting
   breaks hash verification in a way that looks like a chain bug. Nail it in M3.
4. **Local Kafka.** Use single-broker KRaft; do not spend a day on a ZooKeeper
   setup you don't need.
5. **Testcontainers on macOS** needs a reachable Docker socket. Sort this in M0,
   not in the middle of M1.
6. **Scope creep toward the GNN.** It is P2 in `APPROACH.md` for good reasons.
   Don't start it until M9 is committed.

---

## Definition of done, per milestone

Every milestone: tests green · `./mvnw verify` passing · committed and pushed in
small commits · the README section for it updated · anything you measured written
down with the command that produced it, so you can reproduce the number when
someone asks in an interview.

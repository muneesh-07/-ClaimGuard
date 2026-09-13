# backend — claims intake, workflow, audit

The Java half of ClaimGuard. Owns claim intake, the workflow state machine, RBAC,
and the audit log, and is the source of truth for the claims database. Fraud
scoring lives in `../scoring/` and is reached over a versioned HTTP contract and
Kafka events.

Start here instead: the [root README](../README.md) for quick start, and
[docs/EXECUTION_PLAN.md](../docs/EXECUTION_PLAN.md) for what is built and what
is next.

## Stack

Java 21 (compiles and runs on 22+) · Spring Boot 3.5.16 · Postgres · Maven

## Running it directly

From the repository root, `make up` then `make run`. Or from this directory:

```bash
docker compose -f ../infra/docker-compose.yml up -d
./mvnw spring-boot:run
```

## Layout

```
src/main/java/com/claimguard/
├── controller/   HTTP endpoints
├── domain/       JPA entities and enums
├── dto/          request/response records — never expose entities
└── repository/   Spring Data repositories
```

Entity fields `claimantPhone`, `claimantAddress` and `repairShopName` look like
ordinary contact details but are the ones that become graph nodes: two claims
sharing a normalised phone number or repair shop is how a fraud ring surfaces.
They are first-class columns so that link is visible from the schema itself.

## Conventions

- **Migrations, not `ddl-auto`.** Schema changes go in a Flyway migration;
  `ddl-auto: validate` then proves the entities and the migrations agree.
- **Controllers don't touch repositories.** Business logic and transaction
  boundaries live in the service layer — a status transition and its audit entry
  must commit together or not at all.
- **The audit log is append-only**, enforced by a database trigger, and each row
  hashes the previous one. Never add an update or delete path to it.

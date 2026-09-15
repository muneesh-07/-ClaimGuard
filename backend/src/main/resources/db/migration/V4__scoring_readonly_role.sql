-- The Python scoring service (M5) reads the graph's raw material
-- (claims, entities, claim_entities) but must never write to it - "Java
-- owns writes" is enforced here by Postgres itself, not by convention or
-- code review. This role can SELECT from exactly these three tables and
-- nothing else: it cannot see claim_audit_events, cannot write anywhere,
-- and cannot alter schema.
--
-- Dev-only password, committed in plaintext exactly like docker-compose.yml's
-- POSTGRES_PASSWORD - not a real credential, same convention already in use
-- for local development in this repo.

-- current_database() rather than a hardcoded "claimguard": this migration
-- also runs against Testcontainers' ephemeral Postgres in every
-- integration test, which names its database "test", not "claimguard".
-- A hardcoded name here broke every Testcontainers-based test the
-- moment this migration was added - caught by actually running the
-- full suite, not by inspection.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'claimguard_scoring') THEN
        CREATE ROLE claimguard_scoring LOGIN PASSWORD 'claimguard_scoring_dev_password';
    END IF;

    EXECUTE format('GRANT CONNECT ON DATABASE %I TO claimguard_scoring', current_database());
END
$$;

GRANT USAGE ON SCHEMA public TO claimguard_scoring;
GRANT SELECT ON claims, entities, claim_entities TO claimguard_scoring;

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

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'claimguard_scoring') THEN
        CREATE ROLE claimguard_scoring LOGIN PASSWORD 'claimguard_scoring_dev_password';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE claimguard TO claimguard_scoring;
GRANT USAGE ON SCHEMA public TO claimguard_scoring;
GRANT SELECT ON claims, entities, claim_entities TO claimguard_scoring;

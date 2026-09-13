-- Bulk-loads a generated claims.csv straight into Postgres via COPY,
-- bypassing POST /api/claims entirely - the "50k HTTP calls is a waste"
-- path from docs/EXECUTION_PLAN.md M4. Run through tools/load_bulk.sh,
-- not directly - it substitutes __CSV_PATH__ below with the real path
-- before invoking psql. (psql's own -v variable substitution inside
-- \copy's filename argument is unreliable across psql client versions,
-- so the substitution is done in the shell script instead.)
--
-- The CSV only has the 8 raw claim fields; status/created_at/updated_at/
-- version have no database default (see V1__claims.sql) and are filled
-- in here to match exactly what ClaimService.createClaim() would set for
-- a brand-new claim. Rows loaded this way have NO entity links and NO
-- audit trail yet - POST /api/entities/resolve-backlog (run by
-- load_bulk.sh right after this) fills in the entity links; there is
-- deliberately no bulk backfill for the audit trail, since "created by
-- COPY, not through a real submission" is itself worth being honest
-- about rather than fabricating a CLAIM_CREATED event that never happened.

CREATE TEMP TABLE claims_staging (
    claim_id          UUID,
    claimant_name     TEXT,
    policy_number     TEXT,
    claim_amount      NUMERIC(14, 2),
    incident_date     DATE,
    claimant_phone    TEXT,
    claimant_address  TEXT,
    repair_shop_name  TEXT
);

\copy claims_staging FROM '__CSV_PATH__' WITH (FORMAT csv, HEADER true)

INSERT INTO claims (id, claimant_name, policy_number, claim_amount, incident_date,
                     claimant_phone, claimant_address, repair_shop_name,
                     status, created_at, updated_at, version)
SELECT claim_id, claimant_name, policy_number, claim_amount, incident_date,
       claimant_phone, claimant_address, NULLIF(repair_shop_name, ''),
       'SUBMITTED', now(), now(), 0
FROM claims_staging
ON CONFLICT (id) DO NOTHING;

SELECT count(*) AS rows_loaded FROM claims_staging;

DROP TABLE claims_staging;

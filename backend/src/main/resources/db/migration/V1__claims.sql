-- Matches com.claimguard.domain.Claim exactly. Columns, types and
-- nullability here are the contract hibernate.hbm2ddl.auto=validate checks
-- against on every startup - if this drifts from the entity, the app
-- refuses to start rather than silently running on the wrong schema.

CREATE TABLE claims (
    id               UUID PRIMARY KEY,
    claimant_name    TEXT NOT NULL,
    policy_number    TEXT NOT NULL,
    claim_amount     NUMERIC(14, 2) NOT NULL,
    incident_date    DATE NOT NULL,
    claimant_phone   TEXT NOT NULL,
    claimant_address TEXT NOT NULL,
    repair_shop_name TEXT,
    status           TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL,
    updated_at       TIMESTAMPTZ NOT NULL,
    version          BIGINT NOT NULL DEFAULT 0
);

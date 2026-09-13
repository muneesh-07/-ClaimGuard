-- The append-only, hash-chained record of every decision made about a
-- claim: created, status changed, scored by the fraud model, or
-- overridden by a human. `prev_hash`/`hash` form a chain per claim (see
-- AuditService) so tampering with a past row is detectable, and the
-- trigger below makes tampering with a past row *impossible* through
-- normal SQL, not just discouraged by convention.

CREATE TABLE claim_audit_events (
    id                UUID PRIMARY KEY,
    claim_id          UUID NOT NULL REFERENCES claims(id),
    seq               INT NOT NULL,
    event_type        TEXT NOT NULL,     -- CLAIM_CREATED | STATUS_CHANGED | FRAUD_SCORED | HUMAN_OVERRIDE
    from_status       TEXT,
    to_status         TEXT,
    actor_id          TEXT NOT NULL,
    actor_role        TEXT NOT NULL,
    reason            TEXT,
    fraud_score       NUMERIC(5, 4),
    ring_id           TEXT,
    explanation_json  JSONB,
    model_version     TEXT,
    occurred_at       TIMESTAMPTZ NOT NULL,
    prev_hash         TEXT NOT NULL,
    hash              TEXT NOT NULL,
    UNIQUE (claim_id, seq)
);

-- Enforced by the database, not by convention: nobody, including a
-- future version of this codebase, can edit or delete a past decision.
CREATE FUNCTION audit_is_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'claim_audit_events is append-only';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER no_mutate
    BEFORE UPDATE OR DELETE ON claim_audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_is_append_only();

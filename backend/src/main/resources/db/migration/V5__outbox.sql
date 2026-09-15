-- The transactional outbox for M7's async scoring wiring. Writing a
-- claim and publishing to Kafka are two separate systems; inserting
-- this row in the SAME transaction as the claim insert (see
-- ClaimService.createClaim) means a crash between "claim saved" and
-- "event published" is impossible - the row is either committed with
-- the claim or not at all, and a scheduled poller (OutboxPublisher)
-- is what actually talks to Kafka, on its own schedule, outside the
-- claim's transaction.

CREATE TABLE outbox (
    id           UUID PRIMARY KEY,
    aggregate_id UUID NOT NULL,
    topic        TEXT NOT NULL,
    payload      JSONB NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL,
    sent_at      TIMESTAMPTZ
);

-- The poller's hot-path query is "find unsent rows, oldest first".
CREATE INDEX ON outbox (created_at) WHERE sent_at IS NULL;

-- Idempotency for the claim.scored consumer: at-least-once Kafka
-- delivery means the same score WILL be processed more than once
-- eventually. Enforced by the database, not by the consumer
-- remembering what it already saw - a partial unique index scoped to
-- just FRAUD_SCORED rows, since model_version is null/irrelevant for
-- every other event type.
CREATE UNIQUE INDEX claim_audit_events_fraud_scored_dedup
    ON claim_audit_events (claim_id, model_version)
    WHERE event_type = 'FRAUD_SCORED';

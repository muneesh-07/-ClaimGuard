-- Raw material for the fraud-ring graph: entities() is one row per
-- resolved real-world thing (a phone number, an address, a repair shop);
-- claim_entities links claims to the entities they reference. No JPA
-- entity maps to these yet - that lands in M2 with the normalisers that
-- actually populate them. Hibernate's schema validator ignores unmapped
-- tables, so Flyway owns this DDL outright in the meantime.

CREATE TABLE entities (
    id              UUID PRIMARY KEY,
    entity_type     TEXT NOT NULL,      -- PHONE | ADDRESS | SHOP
    canonical_value TEXT NOT NULL,
    claim_count     INT NOT NULL DEFAULT 0,
    first_seen_at   TIMESTAMPTZ NOT NULL,
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

-- Hot-path lookups ("has this phone/address/shop appeared before?") run
-- constantly once entity resolution lands - index them now so M2 doesn't
-- need a follow-up migration just to make itself fast.
CREATE INDEX ON claims (claimant_phone);
CREATE INDEX ON claims (claimant_address);
CREATE INDEX ON claims (repair_shop_name);

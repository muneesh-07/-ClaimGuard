"""
Shared test fixtures. Tests run against the real local dev Postgres
(the same one `make up` starts) rather than a mock - consistent with
this project's preference for exercising real SQL over mocked
behaviour. Fixture setup/teardown uses the full read-write `claimguard`
user (the scoring role can't insert its own test data, by design);
the code under test always goes through the read-only `claimguard_scoring`
role, exactly like it would in production.

`refreshed_scoring_cache` is session-scoped deliberately: building the
graph and running the full detector ladder over the real dev database
(~51k claims as of M4) takes several seconds, so every test that needs
scored data shares ONE refresh rather than paying that cost per test.
"""

import os
import uuid
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, create_engine, text

from app.db import SessionLocal
from app.main import app

ADMIN_DATABASE_URL = os.environ.get(
    "ADMIN_DATABASE_URL",
    "postgresql+psycopg://claimguard:claimguard_dev_password@localhost:5434/claimguard",
)


@pytest.fixture(scope="session")
def admin_engine():
    return create_engine(ADMIN_DATABASE_URL)


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def scoring_session():
    session = SessionLocal()
    yield session
    session.close()


def _insert_claim(conn, claim_id, phone):
    conn.execute(text("""
        INSERT INTO claims (id, claimant_name, policy_number, claim_amount, incident_date,
                             claimant_phone, claimant_address, repair_shop_name, status,
                             created_at, updated_at, version)
        VALUES (:id, 'Test Claimant', 'POL-TEST', 1000.00, :incident_date,
                :phone, 'Test Address', 'Test Shop', 'SUBMITTED', :now, :now, 0)
    """), {"id": str(claim_id), "incident_date": date(2026, 1, 1), "phone": phone,
           "now": datetime.now(UTC)})


def _link_entity(conn, claim_id, entity_id, canonical_phone):
    conn.execute(text("""
        INSERT INTO entities (id, entity_type, canonical_value, claim_count, first_seen_at)
        VALUES (:id, 'PHONE', :value, 1, :now)
        ON CONFLICT (entity_type, canonical_value)
        DO UPDATE SET claim_count = entities.claim_count + 1
    """), {"id": str(entity_id), "value": canonical_phone, "now": datetime.now(UTC)})
    conn.execute(text("""
        INSERT INTO claim_entities (claim_id, entity_id, role, raw_value)
        VALUES (:claim_id, :entity_id, 'CLAIMANT_PHONE', :raw_value)
    """), {"claim_id": str(claim_id), "entity_id": str(entity_id), "raw_value": canonical_phone})


@pytest.fixture(scope="session")
def small_ring_claim_ids(admin_engine):
    """Three claims sharing one fresh, uniquely-generated, low-degree phone - a real ring
    by the detector's own definition (min_ring_size=3), isolated from anything else in
    the dev database. Session-scoped so this data exists before the one session-scoped
    graph refresh below runs."""
    claim_ids = [uuid.uuid4() for _ in range(3)]
    entity_id = uuid.uuid4()
    phone = f"+91{uuid.uuid4().int % 10_000_000_000:010d}"

    with admin_engine.begin() as conn:
        for claim_id in claim_ids:
            _insert_claim(conn, claim_id, phone)
            _link_entity(conn, claim_id, entity_id, phone)

    yield claim_ids

    id_strings = [str(c) for c in claim_ids]
    with admin_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM claim_entities WHERE claim_id IN :ids").bindparams(
                bindparam("ids", expanding=True)),
            {"ids": id_strings},
        )
        conn.execute(
            text("DELETE FROM claims WHERE id IN :ids").bindparams(bindparam("ids", expanding=True)),
            {"ids": id_strings},
        )
        conn.execute(text("DELETE FROM entities WHERE id = :id"), {"id": str(entity_id)})


@pytest.fixture(scope="session")
def refreshed_scoring_cache(small_ring_claim_ids):
    """Builds the graph and runs the full detector ladder ONCE for the whole test
    session, after small_ring_claim_ids has inserted its fixture ring."""
    from app.scoring import refresh

    session = SessionLocal()
    try:
        refresh(session)
    finally:
        session.close()
    return small_ring_claim_ids

"""
Shared test fixtures. Tests run against the real local dev Postgres
(the same one `make up` starts) rather than a mock - consistent with
this project's preference for exercising real SQL over mocked
behaviour. Fixture setup/teardown uses the full read-write `claimguard`
user (the scoring role can't insert its own test data, by design);
the code under test always goes through the read-only `claimguard_scoring`
role, exactly like it would in production.
"""

import os
import uuid
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

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


@pytest.fixture()
def two_linked_claims(admin_engine):
    """Two claims sharing one fresh, uniquely-generated phone entity -
    isolated test data that can't collide with anything else in the dev database."""
    claim_a = uuid.uuid4()
    claim_b = uuid.uuid4()
    entity_id = uuid.uuid4()
    phone = f"+91{uuid.uuid4().int % 10_000_000_000:010d}"

    with admin_engine.begin() as conn:
        _insert_claim(conn, claim_a, phone)
        _insert_claim(conn, claim_b, phone)
        _link_entity(conn, claim_a, entity_id, phone)
        _link_entity(conn, claim_b, entity_id, phone)

    yield claim_a, claim_b

    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM claim_entities WHERE claim_id IN (:a, :b)"),
                      {"a": str(claim_a), "b": str(claim_b)})
        conn.execute(text("DELETE FROM claims WHERE id IN (:a, :b)"),
                      {"a": str(claim_a), "b": str(claim_b)})
        conn.execute(text("DELETE FROM entities WHERE id = :id"), {"id": str(entity_id)})


@pytest.fixture()
def unlinked_claim(admin_engine):
    """One claim with no entity links at all - the score_claim(None) case."""
    claim_id = uuid.uuid4()
    phone = f"+91{uuid.uuid4().int % 10_000_000_000:010d}"

    with admin_engine.begin() as conn:
        _insert_claim(conn, claim_id, phone)

    yield claim_id

    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM claims WHERE id = :id"), {"id": str(claim_id)})

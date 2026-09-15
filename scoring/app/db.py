"""
Database access for the scoring service - deliberately the ONLY file in
this service that talks to Postgres, and it connects with the read-only
`claimguard_scoring` role (see backend/.../V4__scoring_readonly_role.sql).
That role can SELECT from claims/entities/claim_entities and nothing
else, so "the scoring service never writes to the database" is a fact
Postgres enforces, not a rule this code has to remember to follow.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://claimguard_scoring:claimguard_scoring_dev_password"
    "@localhost:5434/claimguard"
)


# Builds the SQLAlchemy engine from DATABASE_URL, falling back to the local dev connection string.
def make_engine():
    database_url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    return create_engine(database_url, pool_pre_ping=True)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


# FastAPI dependency: yields one DB session per request and always closes it, even on error.
def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

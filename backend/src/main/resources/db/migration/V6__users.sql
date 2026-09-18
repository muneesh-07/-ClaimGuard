-- RBAC. Deliberately minimal: no registration flow, no refresh tokens,
-- no password reset. Demo accounts are seeded at application startup (see
-- DemoUserSeeder), not with a hash literal baked into this migration -
-- that keeps the migration itself free of anything that looks like a
-- credential, and means the seeded password is generated through the
-- exact same BCryptPasswordEncoder that verifies it at login.

CREATE TABLE users (
    id            UUID PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL,     -- ADJUSTER | INVESTIGATOR | AUDITOR
    created_at    TIMESTAMPTZ NOT NULL
);

package com.claimguard.domain;

/**
 * What kind of thing happened to a claim, recorded as one audit event.
 * FRAUD_SCORED and its explanation/model-version fields aren't populated
 * until the Python scoring service lands (M5-M7); the column exists now
 * because retrofitting an append-only table's shape later is painful.
 */
public enum AuditEventType {
    CLAIM_CREATED,
    STATUS_CHANGED,
    FRAUD_SCORED,
    HUMAN_OVERRIDE
}

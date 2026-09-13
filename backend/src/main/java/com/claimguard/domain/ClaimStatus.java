package com.claimguard.domain;

/**
 * The lifecycle a claim moves through. Transitions between these states
 * are what the audit log will record once we add it (Step 4-ish).
 * <p>
 * SUBMITTED -> UNDER_REVIEW -> (FLAGGED ->) APPROVED | DENIED
 */
public enum ClaimStatus {
    SUBMITTED,
    UNDER_REVIEW,
    FLAGGED,
    APPROVED,
    DENIED
}

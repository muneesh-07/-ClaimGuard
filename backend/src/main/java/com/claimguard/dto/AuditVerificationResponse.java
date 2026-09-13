package com.claimguard.dto;

/** The result of recomputing a claim's audit hash chain: whether it's intact, and how many events it covers. */
public record AuditVerificationResponse(boolean valid, long events) {
}

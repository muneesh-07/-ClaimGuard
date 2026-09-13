package com.claimguard.dto;

import com.claimguard.domain.Claim;
import com.claimguard.domain.ClaimStatus;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.util.UUID;

/**
 * What a client sees back. Deliberately separate from the Claim entity -
 * this is the seam that lets the persisted schema evolve (new columns,
 * renamed fields) without silently changing the API shape.
 */
public record ClaimResponse(
        UUID id,
        String claimantName,
        String policyNumber,
        BigDecimal claimAmount,
        LocalDate incidentDate,
        String claimantPhone,
        String claimantAddress,
        String repairShopName,
        ClaimStatus status,
        Instant createdAt,
        Instant updatedAt
) {
    public static ClaimResponse from(Claim claim) {
        return new ClaimResponse(
                claim.getId(),
                claim.getClaimantName(),
                claim.getPolicyNumber(),
                claim.getClaimAmount(),
                claim.getIncidentDate(),
                claim.getClaimantPhone(),
                claim.getClaimantAddress(),
                claim.getRepairShopName(),
                claim.getStatus(),
                claim.getCreatedAt(),
                claim.getUpdatedAt()
        );
    }
}

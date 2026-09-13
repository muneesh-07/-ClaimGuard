package com.claimguard.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;

import java.math.BigDecimal;
import java.time.LocalDate;

/**
 * What a client sends us to create a claim. Deliberately separate from
 * the Claim entity - callers shouldn't be able to set id, status,
 * createdAt, etc. directly; the server controls those.
 */
public record ClaimRequest(
        @NotBlank String claimantName,
        @NotBlank String policyNumber,
        @NotNull @Positive BigDecimal claimAmount,
        @NotNull LocalDate incidentDate,
        @NotBlank String claimantPhone,
        @NotBlank String claimantAddress,
        String repairShopName
) {
}

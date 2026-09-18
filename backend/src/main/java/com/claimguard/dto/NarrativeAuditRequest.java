package com.claimguard.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

/**
 * What the frontend sends after the Python scoring service generates an
 * investigator narrative (POST /score/narrative there) and the viewer
 * wants it made part of the claim's permanent record. Deliberately just
 * these three fields - Java trusts the narrative text and grounded flag
 * verbatim, the same way it already trusts explanation_json's shape for
 * a FRAUD_SCORED event (see ScoringResultConsumer), rather than
 * re-deriving or re-checking either service's own computation.
 */
public record NarrativeAuditRequest(
        @NotBlank String narrative,
        @NotNull Boolean grounded,
        @NotBlank String modelVersion
) {
}

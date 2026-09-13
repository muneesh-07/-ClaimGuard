package com.claimguard.dto;

import com.claimguard.domain.ClaimStatus;
import jakarta.validation.constraints.NotNull;

/** What a client sends to move a claim to a new status. `reason` is optional except for a human override (FLAGGED -> APPROVED), which ClaimService rejects without one. */
public record TransitionRequest(
        @NotNull ClaimStatus toStatus,
        String reason
) {
}

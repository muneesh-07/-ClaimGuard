package com.claimguard.dto;

import jakarta.validation.constraints.NotBlank;

/** Credentials posted to POST /api/auth/login. */
public record LoginRequest(
        @NotBlank String username,
        @NotBlank String password
) {
}

package com.claimguard.dto;

/** What a successful login returns: a bearer token to send back as Authorization, and the role it was issued for (so a client doesn't have to decode the JWT just to know that). */
public record LoginResponse(String token, String role) {
}

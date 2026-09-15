package com.claimguard.security;

import com.claimguard.domain.ActorRole;

/**
 * The principal JwtAuthenticationFilter attaches to the security
 * context for a valid request: who's asking, and in what role. A
 * controller reads this straight off {@code Authentication.getPrincipal()}
 * instead of re-parsing the JWT or trusting a client-supplied header
 * (compare to the X-Actor-Id/X-Actor-Role stub this replaces).
 */
public record AuthenticatedActor(String username, ActorRole role) {
}

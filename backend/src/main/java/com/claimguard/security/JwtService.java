package com.claimguard.security;

import com.claimguard.domain.User;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Date;

/**
 * Issues and verifies the JWTs that stand in for a session in this
 * stateless API. Deliberately simple per docs/EXECUTION_PLAN.md M8's
 * scope discipline: one claim ("role") beyond the standard subject/
 * issued-at/expiry, no refresh tokens, no revocation list - a token is
 * valid until it expires, full stop.
 */
@Component
public class JwtService {

    private static final String ROLE_CLAIM = "role";

    private final SecretKey key;
    private final long expirationMinutes;

    public JwtService(@Value("${claimguard.jwt.secret}") String secret,
                       @Value("${claimguard.jwt.expiration-minutes:60}") long expirationMinutes) {
        this.key = Keys.hmacShaKeyFor(secret.getBytes(StandardCharsets.UTF_8));
        this.expirationMinutes = expirationMinutes;
    }

    /** Builds a signed JWT carrying the user's username (as subject) and role, valid for expirationMinutes. */
    public String generateToken(User user) {
        Instant now = Instant.now();
        return Jwts.builder()
                .subject(user.getUsername())
                .claim(ROLE_CLAIM, user.getRole().name())
                .issuedAt(Date.from(now))
                .expiration(Date.from(now.plus(expirationMinutes, ChronoUnit.MINUTES)))
                .signWith(key)
                .compact();
    }

    /** Verifies the token's signature and expiry and returns its claims, or throws JwtException if it's invalid/expired/tampered. */
    public Claims parse(String token) throws JwtException {
        return Jwts.parser().verifyWith(key).build().parseSignedClaims(token).getPayload();
    }

    /** The role claim from an already-parsed token. */
    public String roleFrom(Claims claims) {
        return claims.get(ROLE_CLAIM, String.class);
    }
}

package com.claimguard.security;

import com.claimguard.domain.ActorRole;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.List;

/**
 * Runs once per request: if a valid {@code Authorization: Bearer <jwt>}
 * header is present, populates the Spring Security context with an
 * {@link AuthenticatedActor}. Does NOT reject requests with a missing
 * or invalid token here - that's the security filter chain's job for
 * endpoints that require authentication (see SecurityConfig); a public
 * endpoint should still work with no token at all.
 */
@Component
public class JwtAuthenticationFilter extends OncePerRequestFilter {

    private static final Logger log = LoggerFactory.getLogger(JwtAuthenticationFilter.class);
    private static final String BEARER_PREFIX = "Bearer ";

    private final JwtService jwtService;

    public JwtAuthenticationFilter(JwtService jwtService) {
        this.jwtService = jwtService;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String header = request.getHeader("Authorization");

        if (header != null && header.startsWith(BEARER_PREFIX)) {
            try {
                Claims claims = jwtService.parse(header.substring(BEARER_PREFIX.length()));
                AuthenticatedActor actor = new AuthenticatedActor(
                        claims.getSubject(), ActorRole.valueOf(jwtService.roleFrom(claims)));

                var authorities = List.of(new SimpleGrantedAuthority("ROLE_" + actor.role()));
                var authentication = new UsernamePasswordAuthenticationToken(actor, null, authorities);
                SecurityContextHolder.getContext().setAuthentication(authentication);
            } catch (JwtException | IllegalArgumentException e) {
                log.debug("Rejected an invalid bearer token: {}", e.getMessage());
            }
        }

        chain.doFilter(request, response);
    }
}

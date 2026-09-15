package com.claimguard.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ProblemDetail;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

/**
 * The security filter chain. Scope is deliberately narrow, per
 * docs/EXECUTION_PLAN.md M8: only POST /api/claims/{id}/transitions
 * requires authentication. Everything else - claim intake, reads, the
 * scoring endpoints - stays open, exactly like it was before M8; RBAC
 * here is about *who may change a claim's workflow state*, not a
 * blanket login wall in front of the whole API.
 * <p>
 * Role enforcement itself (which role may perform which transition)
 * is NOT done here with {@code hasRole(...)} matchers - it stays at
 * the service layer (see ClaimTransitions/ClaimService.transitionStatus),
 * per the plan's explicit instruction. This filter chain only answers
 * "is there a valid authenticated actor at all"; ClaimService answers
 * "is *this* actor allowed to do *this*".
 */
@Configuration
public class SecurityConfig {

    private final JwtAuthenticationFilter jwtAuthenticationFilter;
    private final ObjectMapper objectMapper;

    public SecurityConfig(JwtAuthenticationFilter jwtAuthenticationFilter, ObjectMapper objectMapper) {
        this.jwtAuthenticationFilter = jwtAuthenticationFilter;
        this.objectMapper = objectMapper;
    }

    /** BCrypt for password hashing - what DemoUserSeeder hashes with and AuthController verifies against. */
    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    @Bean
    public SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
        http
                .csrf(AbstractHttpConfigurer::disable)
                .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .exceptionHandling(ex -> ex.authenticationEntryPoint(problemDetailEntryPoint()))
                .authorizeHttpRequests(auth -> auth
                        .requestMatchers(HttpMethod.POST, "/api/claims/*/transitions").authenticated()
                        .anyRequest().permitAll())
                .addFilterBefore(jwtAuthenticationFilter, UsernamePasswordAuthenticationFilter.class);
        return http.build();
    }

    /** A missing/invalid bearer token on a protected endpoint returns the same RFC 7807 ProblemDetail shape as every other error in this API, not Spring Security's default plain-text 401. */
    private org.springframework.security.web.AuthenticationEntryPoint problemDetailEntryPoint() {
        return (request, response, authException) -> {
            ProblemDetail problem = ProblemDetail.forStatus(HttpStatus.UNAUTHORIZED);
            problem.setTitle("Unauthorized");
            problem.setDetail("A valid Bearer token is required for this request.");
            response.setStatus(HttpStatus.UNAUTHORIZED.value());
            response.setContentType(MediaType.APPLICATION_PROBLEM_JSON_VALUE);
            objectMapper.writeValue(response.getWriter(), problem);
        };
    }
}

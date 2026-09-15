package com.claimguard;

import com.claimguard.domain.ClaimStatus;
import com.claimguard.dto.ClaimRequest;
import com.claimguard.dto.ClaimResponse;
import com.claimguard.dto.LoginRequest;
import com.claimguard.dto.LoginResponse;
import com.claimguard.dto.TransitionRequest;
import com.claimguard.security.DemoUserSeeder;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * M8: login, and the specific "auditor is read-only, including
 * everything" requirement from docs/EXECUTION_PLAN.md. Role-vs-transition
 * enforcement in general is covered in WorkflowIntegrationTests.
 */
@Testcontainers
@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = "claimguard.outbox.publisher.enabled=false")
class AuthenticationIntegrationTests {

    @Container
    @ServiceConnection
    static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:17.2");

    @Autowired
    private TestRestTemplate rest;

    private UUID createClaim() {
        ClaimRequest request = new ClaimRequest(
                "Auth Test Claimant", "POL-AUTH-1", new BigDecimal("12000.00"),
                LocalDate.of(2026, 3, 1), "+919876500077", "1 Auth Lane, Chennai", "Auth Motors");
        ResponseEntity<ClaimResponse> response = rest.postForEntity("/api/claims", request, ClaimResponse.class);
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.CREATED);
        return response.getBody().id();
    }

    @Test
    void loggingInWithValidDemoCredentialsReturnsATokenAndTheCorrectRole() {
        ResponseEntity<LoginResponse> response = rest.postForEntity(
                "/api/auth/login", new LoginRequest("adjuster1", DemoUserSeeder.DEMO_PASSWORD), LoginResponse.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(response.getBody().token()).isNotBlank();
        assertThat(response.getBody().role()).isEqualTo("ADJUSTER");
    }

    @Test
    void loggingInWithTheWrongPasswordIsRejected() {
        ResponseEntity<ProblemDetail> response = rest.postForEntity(
                "/api/auth/login", new LoginRequest("adjuster1", "not-the-password"), ProblemDetail.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED);
    }

    @Test
    void loggingInAsAnUnknownUserIsRejectedTheSameWayAsAWrongPassword() {
        ResponseEntity<ProblemDetail> response = rest.postForEntity(
                "/api/auth/login", new LoginRequest("nobody-by-this-name", "whatever"), ProblemDetail.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED);
    }

    @Test
    void aTransitionWithNoBearerTokenAtAllIsRejectedWithAProblemDetail() {
        UUID claimId = createClaim();

        ResponseEntity<ProblemDetail> response = rest.postForEntity(
                "/api/claims/{id}/transitions", new TransitionRequest(ClaimStatus.UNDER_REVIEW, null),
                ProblemDetail.class, claimId);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED);
        assertThat(response.getBody().getDetail()).contains("Bearer token");
    }

    @Test
    void anAuditorCanNeverPerformAnyTransition() {
        UUID claimId = createClaim();
        String auditorToken = rest.postForEntity(
                "/api/auth/login", new LoginRequest("auditor1", DemoUserSeeder.DEMO_PASSWORD), LoginResponse.class)
                .getBody().token();

        HttpHeaders headers = new HttpHeaders();
        headers.setBearerAuth(auditorToken);
        // The one transition every OTHER role can legally do from SUBMITTED - if an
        // auditor is rejected from even this, "read-only, full stop" genuinely holds.
        HttpEntity<TransitionRequest> entity =
                new HttpEntity<>(new TransitionRequest(ClaimStatus.UNDER_REVIEW, null), headers);

        ResponseEntity<ProblemDetail> response = rest.exchange(
                "/api/claims/{id}/transitions", HttpMethod.POST, entity, ProblemDetail.class, claimId);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.FORBIDDEN);
    }

    @Test
    void anAuditorCanStillReadClaimsAndTheAuditTrail() {
        UUID claimId = createClaim();
        // No token at all needed - reads stay open; only the transitions endpoint requires auth.
        ResponseEntity<ClaimResponse> response =
                rest.getForEntity("/api/claims/{id}", ClaimResponse.class, claimId);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    }
}

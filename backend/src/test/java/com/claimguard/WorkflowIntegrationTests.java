package com.claimguard;

import com.claimguard.domain.ClaimStatus;
import com.claimguard.dto.AuditEventResponse;
import com.claimguard.dto.AuditVerificationResponse;
import com.claimguard.dto.ClaimRequest;
import com.claimguard.dto.ClaimResponse;
import com.claimguard.dto.LoginRequest;
import com.claimguard.dto.LoginResponse;
import com.claimguard.dto.NarrativeAuditRequest;
import com.claimguard.dto.TransitionRequest;
import com.claimguard.security.DemoUserSeeder;
import com.claimguard.service.ClaimService;
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
import org.springframework.jdbc.core.JdbcTemplate;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * Covers the workflow acceptance tests: illegal transition -> 409, a
 * fraud-flag override without a reason -> 400, the chain verifies once
 * a claim has moved through a few states, and a raw SQL UPDATE against
 * claim_audit_events fails at the database. Human-actor transitions go
 * through real login (M8) rather than the old X-Actor-Id/X-Actor-Role
 * header stub; getting a claim into FLAGGED (the SYSTEM-only transition
 * that in production happens via the M7 Kafka pipeline, not this HTTP
 * endpoint) uses ClaimService.applyScore() directly, the same way
 * OutboxAndScoringIntegrationTests does.
 */
@Testcontainers
@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = "claimguard.outbox.publisher.enabled=false")
class WorkflowIntegrationTests {

    @Container
    @ServiceConnection
    static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:17.2");

    @Autowired
    private TestRestTemplate rest;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Autowired
    private ClaimService claimService;

    private UUID createClaim() {
        ClaimRequest request = new ClaimRequest(
                "Ravi Kumar",
                "POL-30001",
                new BigDecimal("20000.00"),
                LocalDate.of(2026, 2, 1),
                "+91-9876500099",
                "9 MG Road, Bengaluru",
                "Metro Motors");

        ResponseEntity<ClaimResponse> response = rest.postForEntity("/api/claims", request, ClaimResponse.class);
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.CREATED);
        return response.getBody().id();
    }

    private String loginAndGetToken(String username) {
        ResponseEntity<LoginResponse> response = rest.postForEntity(
                "/api/auth/login", new LoginRequest(username, DemoUserSeeder.DEMO_PASSWORD), LoginResponse.class);
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        return response.getBody().token();
    }

    private <T> ResponseEntity<T> transitionAs(UUID claimId, ClaimStatus toStatus, String reason,
                                                String username, Class<T> responseType) {
        HttpHeaders headers = new HttpHeaders();
        headers.setBearerAuth(loginAndGetToken(username));
        HttpEntity<TransitionRequest> entity = new HttpEntity<>(new TransitionRequest(toStatus, reason), headers);
        return rest.exchange("/api/claims/{id}/transitions", HttpMethod.POST, entity, responseType, claimId);
    }

    /** Flags a claim the way M7's Kafka pipeline actually does in production - not through the human-facing HTTP endpoint, which SYSTEM can't authenticate against. */
    private void flagClaim(UUID claimId) {
        claimService.applyScore(claimId, new BigDecimal("0.9000"), "FLAG", "test-ring",
                null, "test-model-workflow");
    }

    @Test
    void creatingAClaimRecordsAClaimCreatedAuditEvent() {
        UUID claimId = createClaim();

        ResponseEntity<AuditEventResponse[]> audit =
                rest.getForEntity("/api/claims/{id}/audit", AuditEventResponse[].class, claimId);

        assertThat(audit.getBody()).hasSize(1);
        assertThat(audit.getBody()[0].eventType().name()).isEqualTo("CLAIM_CREATED");
        assertThat(audit.getBody()[0].toStatus().name()).isEqualTo("SUBMITTED");
    }

    @Test
    void aLegalTransitionSucceedsAndTheChainVerifies() {
        UUID claimId = createClaim();

        ResponseEntity<ClaimResponse> response =
                transitionAs(claimId, ClaimStatus.UNDER_REVIEW, null, "adjuster1", ClaimResponse.class);
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(response.getBody().status().name()).isEqualTo("UNDER_REVIEW");

        ResponseEntity<AuditVerificationResponse> verify =
                rest.getForEntity("/api/claims/{id}/audit/verify", AuditVerificationResponse.class, claimId);

        assertThat(verify.getBody().valid()).isTrue();
        assertThat(verify.getBody().events()).isEqualTo(2);
    }

    @Test
    void anIllegalTransitionIsRejectedWithConflict() {
        UUID claimId = createClaim();

        ResponseEntity<ProblemDetail> response =
                transitionAs(claimId, ClaimStatus.APPROVED, null, "adjuster1", ProblemDetail.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.CONFLICT);
    }

    @Test
    void aRoleMismatchedTransitionIsRejectedWithForbidden() {
        UUID claimId = createClaim();
        flagClaim(claimId);

        // FLAGGED -> APPROVED exists in the transition table, but only for INVESTIGATOR -
        // an ADJUSTER attempting it is an authorization failure (403), not "no such transition" (409).
        ResponseEntity<ProblemDetail> response = transitionAs(
                claimId, ClaimStatus.APPROVED, "trying anyway", "adjuster1", ProblemDetail.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.FORBIDDEN);
    }

    @Test
    void overridingAFraudFlagWithoutAReasonIsRejected() {
        UUID claimId = createClaim();
        flagClaim(claimId);

        ResponseEntity<ProblemDetail> response =
                transitionAs(claimId, ClaimStatus.APPROVED, null, "investigator1", ProblemDetail.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
    }

    @Test
    void overridingAFraudFlagWithAReasonSucceedsAndIsRecordedAsHumanOverride() {
        UUID claimId = createClaim();
        flagClaim(claimId);

        ResponseEntity<ClaimResponse> response = transitionAs(claimId, ClaimStatus.APPROVED,
                "Investigated - shared shop was coincidental, not fraud", "investigator1", ClaimResponse.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(response.getBody().status().name()).isEqualTo("APPROVED");

        ResponseEntity<AuditEventResponse[]> audit =
                rest.getForEntity("/api/claims/{id}/audit", AuditEventResponse[].class, claimId);
        AuditEventResponse last = audit.getBody()[audit.getBody().length - 1];
        assertThat(last.eventType().name()).isEqualTo("HUMAN_OVERRIDE");
        assertThat(last.reason()).isNotBlank();
        assertThat(last.actorId()).isEqualTo("investigator1");
    }

    @Test
    void recordingANarrativeAppendsAHashChainedEventAndTheChainStillVerifies() {
        UUID claimId = createClaim();

        NarrativeAuditRequest request = new NarrativeAuditRequest(
                "Shares a phone number with two other claims filed the same week.",
                true, "ollama:llama3.2:3b");
        ResponseEntity<Void> response =
                rest.postForEntity("/api/claims/{id}/audit/narrative", request, Void.class, claimId);
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NO_CONTENT);

        ResponseEntity<AuditEventResponse[]> audit =
                rest.getForEntity("/api/claims/{id}/audit", AuditEventResponse[].class, claimId);
        assertThat(audit.getBody()).hasSize(2);
        AuditEventResponse last = audit.getBody()[1];
        assertThat(last.eventType().name()).isEqualTo("NARRATIVE_GENERATED");
        assertThat(last.modelVersion()).isEqualTo("ollama:llama3.2:3b");
        assertThat(last.explanationJson()).contains("Shares a phone number");
        // Not a workflow transition - the claim's status shouldn't have moved.
        assertThat(last.fromStatus()).isEqualTo(last.toStatus());

        ResponseEntity<AuditVerificationResponse> verify =
                rest.getForEntity("/api/claims/{id}/audit/verify", AuditVerificationResponse.class, claimId);
        assertThat(verify.getBody().valid()).isTrue();
        assertThat(verify.getBody().events()).isEqualTo(2);
    }

    @Test
    void tamperingWithAnAuditRowThroughRawSqlIsRejectedByTheDatabase() {
        UUID claimId = createClaim();

        assertThatThrownBy(() -> jdbcTemplate.update(
                "UPDATE claim_audit_events SET reason = 'tampered' WHERE claim_id = ?", claimId))
                .hasMessageContaining("append-only");
    }
}

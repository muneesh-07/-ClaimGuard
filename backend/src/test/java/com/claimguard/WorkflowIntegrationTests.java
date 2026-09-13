package com.claimguard;

import com.claimguard.dto.AuditEventResponse;
import com.claimguard.dto.AuditVerificationResponse;
import com.claimguard.dto.ClaimRequest;
import com.claimguard.dto.ClaimResponse;
import com.claimguard.dto.TransitionRequest;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
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
 * Covers the M3 acceptance tests named directly in
 * docs/EXECUTION_PLAN.md: illegal transition -> 409, a fraud-flag
 * override without a reason -> 400, the chain verifies once a claim has
 * moved through a few states, and a raw SQL UPDATE against
 * claim_audit_events fails at the database.
 */
@Testcontainers
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class WorkflowIntegrationTests {

    @Container
    @ServiceConnection
    static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:17.2");

    @Autowired
    private TestRestTemplate rest;

    @Autowired
    private JdbcTemplate jdbcTemplate;

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

    private ResponseEntity<ClaimResponse> transition(UUID claimId, String toStatus, String reason,
                                                       String actorId, String actorRole) {
        HttpHeaders headers = new HttpHeaders();
        headers.set("X-Actor-Id", actorId);
        headers.set("X-Actor-Role", actorRole);
        HttpEntity<TransitionRequest> entity = new HttpEntity<>(
                new TransitionRequest(com.claimguard.domain.ClaimStatus.valueOf(toStatus), reason), headers);

        return rest.exchange("/api/claims/{id}/transitions", org.springframework.http.HttpMethod.POST,
                entity, ClaimResponse.class, claimId);
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

        ResponseEntity<ClaimResponse> response = transition(claimId, "UNDER_REVIEW", null, "adjuster-1", "ADJUSTER");
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

        ResponseEntity<ProblemDetail> response = rest.exchange(
                "/api/claims/{id}/transitions", org.springframework.http.HttpMethod.POST,
                new HttpEntity<>(new TransitionRequest(com.claimguard.domain.ClaimStatus.APPROVED, null),
                        headersFor("adjuster-1", "ADJUSTER")),
                ProblemDetail.class, claimId);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.CONFLICT);
    }

    @Test
    void overridingAFraudFlagWithoutAReasonIsRejected() {
        UUID claimId = createClaim();
        // SUBMITTED -> FLAGGED as SYSTEM, then try to clear it as an override without a reason.
        assertThat(transition(claimId, "FLAGGED", null, "fraud-model", "SYSTEM").getStatusCode())
                .isEqualTo(HttpStatus.OK);

        ResponseEntity<ProblemDetail> response = rest.exchange(
                "/api/claims/{id}/transitions", org.springframework.http.HttpMethod.POST,
                new HttpEntity<>(new TransitionRequest(com.claimguard.domain.ClaimStatus.APPROVED, null),
                        headersFor("investigator-1", "INVESTIGATOR")),
                ProblemDetail.class, claimId);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
    }

    @Test
    void overridingAFraudFlagWithAReasonSucceedsAndIsRecordedAsHumanOverride() {
        UUID claimId = createClaim();
        transition(claimId, "FLAGGED", null, "fraud-model", "SYSTEM");

        ResponseEntity<ClaimResponse> response = transition(
                claimId, "APPROVED", "Investigated - shared shop was coincidental, not fraud", "investigator-1", "INVESTIGATOR");

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(response.getBody().status().name()).isEqualTo("APPROVED");

        ResponseEntity<AuditEventResponse[]> audit =
                rest.getForEntity("/api/claims/{id}/audit", AuditEventResponse[].class, claimId);
        AuditEventResponse last = audit.getBody()[audit.getBody().length - 1];
        assertThat(last.eventType().name()).isEqualTo("HUMAN_OVERRIDE");
        assertThat(last.reason()).isNotBlank();
    }

    @Test
    void tamperingWithAnAuditRowThroughRawSqlIsRejectedByTheDatabase() {
        UUID claimId = createClaim();

        assertThatThrownBy(() -> jdbcTemplate.update(
                "UPDATE claim_audit_events SET reason = 'tampered' WHERE claim_id = ?", claimId))
                .hasMessageContaining("append-only");
    }

    private HttpHeaders headersFor(String actorId, String actorRole) {
        HttpHeaders headers = new HttpHeaders();
        headers.set("X-Actor-Id", actorId);
        headers.set("X-Actor-Role", actorRole);
        return headers;
    }
}

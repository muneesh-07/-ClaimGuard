package com.claimguard;

import com.claimguard.domain.Claim;
import com.claimguard.domain.ClaimAuditEvent;
import com.claimguard.domain.OutboxEvent;
import com.claimguard.dto.ClaimRequest;
import com.claimguard.repository.ClaimAuditEventRepository;
import com.claimguard.repository.OutboxEventRepository;
import com.claimguard.service.AuditService;
import com.claimguard.service.ClaimService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Covers the M7 async wiring at the Java-service level: the
 * transactional outbox row a new claim produces, and
 * ClaimService.applyScore()'s transition + idempotency behavior when a
 * claim.scored result comes back. Doesn't spin up a real Kafka broker -
 * that path is covered by actually running the full stack (backend +
 * scoring service + consumer) end to end; this covers the logic each
 * side owns once a message has been produced or is about to be sent.
 */
@Testcontainers
@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = "claimguard.outbox.publisher.enabled=false")
class OutboxAndScoringIntegrationTests {

    @Container
    @ServiceConnection
    static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:17.2");

    @Autowired
    private ClaimService claimService;

    @Autowired
    private OutboxEventRepository outboxEventRepository;

    @Autowired
    private ClaimAuditEventRepository claimAuditEventRepository;

    @Autowired
    private AuditService auditService;

    private Claim createClaim() {
        return claimService.createClaim(new ClaimRequest(
                "Outbox Test Claimant", "POL-OUTBOX-1", new BigDecimal("15000.00"),
                LocalDate.of(2026, 4, 1), "+919876500088", "5 Outbox Lane, Pune", "Test Motors"));
    }

    @Test
    void creatingAClaimQueuesAClaimSubmittedOutboxEvent() {
        Claim claim = createClaim();

        List<OutboxEvent> pending = outboxEventRepository.findBySentAtIsNullOrderByCreatedAtAsc();
        OutboxEvent event = pending.stream()
                .filter(e -> e.getAggregateId().equals(claim.getId()))
                .findFirst()
                .orElseThrow(() -> new AssertionError("No outbox row for claim " + claim.getId()));

        assertThat(event.getTopic()).isEqualTo(ClaimService.CLAIM_SUBMITTED_TOPIC);
        assertThat(event.getPayload()).contains(claim.getId().toString());
        assertThat(event.getSentAt()).isNull();
    }

    @Test
    void applyScoreWithFlagHintTransitionsToFlaggedAndRecordsFraudScoredEvent() {
        Claim claim = createClaim();

        claimService.applyScore(claim.getId(), new BigDecimal("0.9000"), "FLAG", "kcore-1",
                "{\"summary\":\"test\"}", "ring-detector-test-1");

        Claim reloaded = claimService.getClaim(claim.getId());
        assertThat(reloaded.getStatus().name()).isEqualTo("FLAGGED");

        List<ClaimAuditEvent> events = claimAuditEventRepository.findByClaimIdOrderBySeq(claim.getId());
        ClaimAuditEvent fraudScored = events.get(events.size() - 1);
        assertThat(fraudScored.getEventType().name()).isEqualTo("FRAUD_SCORED");
        assertThat(fraudScored.getFraudScore()).isEqualByComparingTo("0.9000");
        assertThat(fraudScored.getRingId()).isEqualTo("kcore-1");
        assertThat(fraudScored.getModelVersion()).isEqualTo("ring-detector-test-1");
    }

    @Test
    void applyScoreWithReviewHintTransitionsToUnderReview() {
        Claim claim = createClaim();

        claimService.applyScore(claim.getId(), new BigDecimal("0.5000"), "REVIEW", null, null,
                "ring-detector-test-2");

        assertThat(claimService.getClaim(claim.getId()).getStatus().name()).isEqualTo("UNDER_REVIEW");
    }

    @Test
    void applyingTheSameScoreTwiceIsIdempotent() {
        Claim claim = createClaim();

        claimService.applyScore(claim.getId(), new BigDecimal("0.9000"), "FLAG", "kcore-2", null,
                "ring-detector-test-3");
        int eventsAfterFirst = claimAuditEventRepository.findByClaimIdOrderBySeq(claim.getId()).size();

        claimService.applyScore(claim.getId(), new BigDecimal("0.9000"), "FLAG", "kcore-2", null,
                "ring-detector-test-3");
        int eventsAfterSecond = claimAuditEventRepository.findByClaimIdOrderBySeq(claim.getId()).size();

        assertThat(eventsAfterSecond).isEqualTo(eventsAfterFirst);
    }

    @Test
    void applyScoreAfterAHumanAlreadyMovedTheClaimStillRecordsTheScoreWithoutForcingATransition() {
        Claim claim = createClaim();
        claimService.transitionStatus(claim.getId(), com.claimguard.domain.ClaimStatus.UNDER_REVIEW, null,
                "adjuster.demo", com.claimguard.domain.ActorRole.ADJUSTER);
        claimService.transitionStatus(claim.getId(), com.claimguard.domain.ClaimStatus.APPROVED, null,
                "adjuster.demo", com.claimguard.domain.ActorRole.ADJUSTER);

        // The score arrives late (e.g. Kafka was briefly unavailable) - APPROVED -> FLAGGED
        // isn't a legal transition, so the claim's status must stay APPROVED, but the
        // score itself still gets recorded in the audit trail.
        claimService.applyScore(claim.getId(), new BigDecimal("0.9500"), "FLAG", "kcore-3", null,
                "ring-detector-test-4");

        assertThat(claimService.getClaim(claim.getId()).getStatus().name()).isEqualTo("APPROVED");
        List<ClaimAuditEvent> events = claimAuditEventRepository.findByClaimIdOrderBySeq(claim.getId());
        ClaimAuditEvent fraudScored = events.get(events.size() - 1);
        assertThat(fraudScored.getEventType().name()).isEqualTo("FRAUD_SCORED");
        assertThat(fraudScored.getFromStatus().name()).isEqualTo("APPROVED");
        assertThat(fraudScored.getToStatus().name()).isEqualTo("APPROVED");
    }

    /**
     * Regression test for a real bug found by actually running the full Kafka pipeline
     * end to end: Jackson's JsonNode.decimalValue() on a JSON number like "0.0" produces a
     * BigDecimal with scale 1, not the column's declared scale of 4 - but the hash was
     * computed from that as-parsed scale in append(), while verify() later re-read the
     * same value back from the NUMERIC(5,4) column at scale 4, producing a different
     * hash for an logically-unchanged value. This deliberately passes a BigDecimal with a
     * non-standard scale (matching what JSON parsing actually produces) to prove the fix
     * (AuditService fixes the scale to 4 before hashing) holds.
     */
    @Test
    void chainStaysValidWhenFraudScoreArrivesWithANonStandardDecimalScale() {
        Claim claim = createClaim();

        claimService.applyScore(claim.getId(), new BigDecimal("0.0"), "REVIEW", null, null,
                "ring-detector-test-scale");

        assertThat(auditService.verify(claim.getId())).isTrue();
    }

    /**
     * Regression test for a second real bug found by the same live run: Postgres jsonb
     * columns re-serialize on every read (different whitespace/formatting from what was
     * inserted), so hashing explanationJson as a raw string made verify() recompute a
     * different hash than append() did, even for an unchanged value. Deliberately passes
     * JSON with non-canonical spacing (extra whitespace, unsorted keys) to prove the fix
     * (parse-then-canonicalize instead of hashing raw text) holds regardless of exactly
     * how the input string was formatted.
     */
    @Test
    void chainStaysValidWhenExplanationJsonHasNonCanonicalFormatting() {
        Claim claim = createClaim();
        String messyJson = "{  \"zebra\" : 1,\n\"apple\":  [1,2,3] }";

        claimService.applyScore(claim.getId(), new BigDecimal("0.9000"), "FLAG", "kcore-99", messyJson,
                "ring-detector-test-json");

        assertThat(auditService.verify(claim.getId())).isTrue();
    }
}

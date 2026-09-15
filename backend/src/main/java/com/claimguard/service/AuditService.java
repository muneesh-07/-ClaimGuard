package com.claimguard.service;

import com.claimguard.audit.CanonicalJson;
import com.claimguard.domain.ActorRole;
import com.claimguard.domain.AuditEventType;
import com.claimguard.domain.ClaimAuditEvent;
import com.claimguard.domain.ClaimStatus;
import com.claimguard.repository.ClaimAuditEventRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * Appends events to a claim's audit trail as a hash chain: each row's
 * hash commits to the previous row's hash plus its own canonical
 * content, so altering or deleting a past decision - even directly in
 * the database, bypassing this service entirely - breaks the chain, and
 * verify() proves that on demand. This is the project's headline
 * feature; re-read docs/EXECUTION_PLAN.md M3 before changing the hashing
 * here, since a subtly different field list between append() and
 * verify() would make every claim's chain silently "invalid" forever.
 */
@Service
public class AuditService {

    /** The hash a claim's first audit event chains from - 64 zero characters standing in for "no previous event". */
    public static final String GENESIS_HASH = "0".repeat(64);

    private final ClaimAuditEventRepository auditEventRepository;

    public AuditService(ClaimAuditEventRepository auditEventRepository) {
        this.auditEventRepository = auditEventRepository;
    }

    /**
     * Appends one event to a claim's chain. Callers that are recording a
     * status transition must already hold a row lock on the claim (see
     * ClaimRepository.findByIdForUpdate) for the whole transaction, or
     * two concurrent appends for the same claim could both read the same
     * "latest event" and fork the chain.
     */
    @Transactional
    public ClaimAuditEvent append(UUID claimId,
                                   AuditEventType eventType,
                                   ClaimStatus fromStatus,
                                   ClaimStatus toStatus,
                                   String actorId,
                                   ActorRole actorRole,
                                   String reason,
                                   BigDecimal fraudScore,
                                   String ringId,
                                   String explanationJson,
                                   String modelVersion) {

        ClaimAuditEvent previous = auditEventRepository.findFirstByClaimIdOrderBySeqDesc(claimId).orElse(null);
        int seq = previous == null ? 1 : previous.getSeq() + 1;
        String prevHash = previous == null ? GENESIS_HASH : previous.getHash();
        Instant occurredAt = Instant.now().truncatedTo(ChronoUnit.MILLIS);

        Map<String, Object> fields = fieldsFor(claimId, seq, eventType, fromStatus, toStatus, actorId, actorRole,
                reason, fraudScore, ringId, explanationJson, modelVersion, occurredAt, prevHash);
        String hash = sha256(prevHash + CanonicalJson.canonicalize(fields));

        ClaimAuditEvent event = ClaimAuditEvent.builder()
                .claimId(claimId)
                .seq(seq)
                .eventType(eventType)
                .fromStatus(fromStatus)
                .toStatus(toStatus)
                .actorId(actorId)
                .actorRole(actorRole)
                .reason(reason)
                .fraudScore(fraudScore)
                .ringId(ringId)
                .explanationJson(explanationJson)
                .modelVersion(modelVersion)
                .occurredAt(occurredAt)
                .prevHash(prevHash)
                .hash(hash)
                .build();

        return auditEventRepository.save(event);
    }

    /** Every audit event for a claim, oldest first. */
    @Transactional(readOnly = true)
    public List<ClaimAuditEvent> history(UUID claimId) {
        return auditEventRepository.findByClaimIdOrderBySeq(claimId);
    }

    /**
     * Recomputes the hash chain from scratch and compares it against
     * what's stored. Returns false the moment one row's prevHash doesn't
     * match the previous row's actual hash, or one row's own hash doesn't
     * match its recomputed content - which is exactly what a tampered,
     * reordered, or deleted-and-reinserted row looks like.
     */
    @Transactional(readOnly = true)
    public boolean verify(UUID claimId) {
        List<ClaimAuditEvent> events = auditEventRepository.findByClaimIdOrderBySeq(claimId);
        String expectedPrevHash = GENESIS_HASH;

        for (ClaimAuditEvent event : events) {
            if (!expectedPrevHash.equals(event.getPrevHash())) {
                return false;
            }
            Map<String, Object> fields = fieldsFor(event.getClaimId(), event.getSeq(), event.getEventType(),
                    event.getFromStatus(), event.getToStatus(), event.getActorId(), event.getActorRole(),
                    event.getReason(), event.getFraudScore(), event.getRingId(), event.getExplanationJson(),
                    event.getModelVersion(), event.getOccurredAt(), event.getPrevHash());
            String recomputedHash = sha256(event.getPrevHash() + CanonicalJson.canonicalize(fields));
            if (!recomputedHash.equals(event.getHash())) {
                return false;
            }
            expectedPrevHash = event.getHash();
        }
        return true;
    }

    /**
     * The single field list that gets hashed - used identically by
     * append() (building a new row) and verify() (rebuilding a stored
     * row's fields to check its hash). Keeping this in one place is what
     * guarantees the two can never drift apart.
     */
    private Map<String, Object> fieldsFor(UUID claimId, int seq, AuditEventType eventType,
                                           ClaimStatus fromStatus, ClaimStatus toStatus,
                                           String actorId, ActorRole actorRole, String reason,
                                           BigDecimal fraudScore, String ringId, String explanationJson,
                                           String modelVersion, Instant occurredAt, String prevHash) {
        Map<String, Object> fields = new LinkedHashMap<>();
        fields.put("claimId", claimId.toString());
        fields.put("seq", seq);
        fields.put("eventType", eventType.name());
        fields.put("fromStatus", fromStatus == null ? null : fromStatus.name());
        fields.put("toStatus", toStatus == null ? null : toStatus.name());
        fields.put("actorId", actorId);
        fields.put("actorRole", actorRole.name());
        fields.put("reason", reason);
        // Fixed scale (4), matching the fraud_score NUMERIC(5,4) column, BEFORE
        // toPlainString(): append() hashes whatever scale the caller's BigDecimal
        // happened to carry (e.g. "0.0" from a JSON value with one decimal digit),
        // but Postgres normalizes the stored value to the column's declared scale,
        // so verify() re-reading the row later saw "0.0000" and produced a
        // different hash for an unchanged value. Caught by actually running the
        // Kafka scoring pipeline and calling /audit/verify on the result - the
        // exact "fixed numeric scale" tripwire named in docs/EXECUTION_PLAN.md M3.
        fields.put("fraudScore", fraudScore == null ? null : fraudScore.setScale(4, RoundingMode.HALF_UP).toPlainString());
        fields.put("ringId", ringId);
        // Parsed, not the raw string: explanationJson is stored in a Postgres jsonb
        // column, which re-serializes on every read (different whitespace, possibly
        // different formatting) - hashing the raw text would make verify() recompute
        // a different hash for an unchanged value the moment it round-trips through
        // the database once. Parsing first lets canonicalize() re-derive a stable
        // form from the actual content, the same way it already does for this
        // method's top-level fields.
        fields.put("explanationJson", explanationJson == null ? null : CanonicalJson.parse(explanationJson));
        fields.put("modelVersion", modelVersion);
        fields.put("occurredAt", occurredAt.toString());
        fields.put("prevHash", prevHash);
        return fields;
    }

    /** SHA-256 of a UTF-8 string, hex-encoded. */
    private String sha256(String input) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] hashBytes = digest.digest(input.getBytes(StandardCharsets.UTF_8));
            StringBuilder hex = new StringBuilder();
            for (byte b : hashBytes) {
                hex.append(String.format("%02x", b));
            }
            return hex.toString();
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 not available", e);
        }
    }
}

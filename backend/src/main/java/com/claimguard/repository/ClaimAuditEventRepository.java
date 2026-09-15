package com.claimguard.repository;

import com.claimguard.domain.AuditEventType;
import com.claimguard.domain.ClaimAuditEvent;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface ClaimAuditEventRepository extends JpaRepository<ClaimAuditEvent, UUID> {

    /** The most recent event for a claim - its hash becomes the next event's prevHash. */
    Optional<ClaimAuditEvent> findFirstByClaimIdOrderBySeqDesc(UUID claimId);

    /** The full chain for a claim, oldest first, for display and for chain verification. */
    List<ClaimAuditEvent> findByClaimIdOrderBySeq(UUID claimId);

    /**
     * Backs the claim.scored consumer's idempotency check: has this
     * exact (claim, model version) score already been recorded? Mirrors
     * the database-enforced unique index in V5__outbox.sql - this is
     * the fast, proactive check; the index is the guarantee if a race
     * ever slips past it.
     */
    boolean existsByClaimIdAndModelVersionAndEventType(UUID claimId, String modelVersion, AuditEventType eventType);
}

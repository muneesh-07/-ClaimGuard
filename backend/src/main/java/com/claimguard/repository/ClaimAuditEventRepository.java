package com.claimguard.repository;

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
}

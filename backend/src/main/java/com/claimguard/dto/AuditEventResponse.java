package com.claimguard.dto;

import com.claimguard.domain.ActorRole;
import com.claimguard.domain.AuditEventType;
import com.claimguard.domain.ClaimAuditEvent;
import com.claimguard.domain.ClaimStatus;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

/** One entry in a claim's audit trail, as returned to a caller. */
public record AuditEventResponse(
        UUID id,
        UUID claimId,
        int seq,
        AuditEventType eventType,
        ClaimStatus fromStatus,
        ClaimStatus toStatus,
        String actorId,
        ActorRole actorRole,
        String reason,
        BigDecimal fraudScore,
        String ringId,
        String modelVersion,
        Instant occurredAt,
        String prevHash,
        String hash
) {
    public static AuditEventResponse from(ClaimAuditEvent event) {
        return new AuditEventResponse(
                event.getId(),
                event.getClaimId(),
                event.getSeq(),
                event.getEventType(),
                event.getFromStatus(),
                event.getToStatus(),
                event.getActorId(),
                event.getActorRole(),
                event.getReason(),
                event.getFraudScore(),
                event.getRingId(),
                event.getModelVersion(),
                event.getOccurredAt(),
                event.getPrevHash(),
                event.getHash()
        );
    }
}

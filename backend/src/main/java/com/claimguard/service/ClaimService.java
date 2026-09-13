package com.claimguard.service;

import com.claimguard.domain.ActorRole;
import com.claimguard.domain.AuditEventType;
import com.claimguard.domain.Claim;
import com.claimguard.domain.ClaimStatus;
import com.claimguard.dto.ClaimRequest;
import com.claimguard.repository.ClaimRepository;
import com.claimguard.workflow.ClaimTransitions;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;
import java.util.UUID;

/**
 * Owns the transaction boundary for claim intake, lookup, and workflow
 * transitions. Controllers never talk to ClaimRepository directly: a
 * status transition and its audit entry have to commit together or not
 * at all, and that only works if the boundary is already here rather
 * than split across a controller method.
 */
@Service
public class ClaimService {

    /** Claim intake isn't performed by staff, so audit events for it are attributed to the intake channel itself rather than a header-supplied actor. */
    private static final String INTAKE_ACTOR_ID = "intake-system";

    private final ClaimRepository claimRepository;
    private final EntityService entityService;
    private final AuditService auditService;

    public ClaimService(ClaimRepository claimRepository, EntityService entityService, AuditService auditService) {
        this.claimRepository = claimRepository;
        this.entityService = entityService;
        this.auditService = auditService;
    }

    /** Persists a new claim and, in the same transaction, resolves and links its entities and appends the CLAIM_CREATED audit event - a claim never exists without its graph edges or its first audit row. */
    @Transactional
    public Claim createClaim(ClaimRequest request) {
        Claim claim = Claim.builder()
                .claimantName(request.claimantName())
                .policyNumber(request.policyNumber())
                .claimAmount(request.claimAmount())
                .incidentDate(request.incidentDate())
                .claimantPhone(request.claimantPhone())
                .claimantAddress(request.claimantAddress())
                .repairShopName(request.repairShopName())
                .build();

        Claim saved = claimRepository.save(claim);
        entityService.resolveAndLink(saved);
        auditService.append(saved.getId(), AuditEventType.CLAIM_CREATED, null, saved.getStatus(),
                INTAKE_ACTOR_ID, ActorRole.SYSTEM, null, null, null, null, null);
        return saved;
    }

    /**
     * Moves a claim to a new status, enforcing the legal transition map
     * (ClaimTransitions) and, for a human override of a fraud flag, that
     * a reason was given. Locks the claim row for the whole transaction
     * so a concurrent transition on the same claim can't interleave and
     * fork the audit hash chain.
     */
    @Transactional
    public Claim transitionStatus(UUID claimId, ClaimStatus toStatus, String reason,
                                   String actorId, ActorRole actorRole) {
        Claim claim = claimRepository.findByIdForUpdate(claimId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Claim not found: " + claimId));

        ClaimStatus fromStatus = claim.getStatus();
        if (!ClaimTransitions.isAllowed(fromStatus, toStatus, actorRole)) {
            throw new ResponseStatusException(HttpStatus.CONFLICT,
                    "Cannot transition claim from " + fromStatus + " to " + toStatus + " as " + actorRole);
        }
        boolean isOverride = ClaimTransitions.requiresReason(fromStatus, toStatus);
        if (isOverride && (reason == null || reason.isBlank())) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "A reason is required to override " + fromStatus + " -> " + toStatus);
        }

        claim.setStatus(toStatus);
        Claim saved = claimRepository.save(claim);

        AuditEventType eventType = isOverride ? AuditEventType.HUMAN_OVERRIDE : AuditEventType.STATUS_CHANGED;
        auditService.append(claimId, eventType, fromStatus, toStatus, actorId, actorRole, reason,
                null, null, null, null);

        return saved;
    }

    /** Fetches one claim by id, or a 404 ProblemDetail if it doesn't exist. */
    @Transactional(readOnly = true)
    public Claim getClaim(UUID id) {
        return claimRepository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Claim not found: " + id));
    }

    /** Every claim in the system - fine at today's scale, will need pagination once volume grows. */
    @Transactional(readOnly = true)
    public List<Claim> listClaims() {
        return claimRepository.findAll();
    }
}

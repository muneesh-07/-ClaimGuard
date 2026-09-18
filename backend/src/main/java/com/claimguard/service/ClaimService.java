package com.claimguard.service;

import com.claimguard.domain.ActorRole;
import com.claimguard.domain.AuditEventType;
import com.claimguard.domain.Claim;
import com.claimguard.domain.ClaimStatus;
import com.claimguard.dto.ClaimRequest;
import com.claimguard.messaging.ClaimSubmittedEvent;
import com.claimguard.repository.ClaimAuditEventRepository;
import com.claimguard.repository.ClaimRepository;
import com.claimguard.workflow.ClaimTransitions;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
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
    private static final String SCORING_ACTOR_ID = "scoring-service";
    public static final String CLAIM_SUBMITTED_TOPIC = "claim.submitted";

    private final ClaimRepository claimRepository;
    private final ClaimAuditEventRepository claimAuditEventRepository;
    private final EntityService entityService;
    private final AuditService auditService;
    private final OutboxService outboxService;
    private final ObjectMapper objectMapper;

    public ClaimService(ClaimRepository claimRepository, ClaimAuditEventRepository claimAuditEventRepository,
                         EntityService entityService, AuditService auditService, OutboxService outboxService,
                         ObjectMapper objectMapper) {
        this.claimRepository = claimRepository;
        this.claimAuditEventRepository = claimAuditEventRepository;
        this.entityService = entityService;
        this.auditService = auditService;
        this.outboxService = outboxService;
        this.objectMapper = objectMapper;
    }

    /**
     * Persists a new claim and, in the same transaction: resolves and
     * links its entities, appends the CLAIM_CREATED audit event, and
     * queues a claim.submitted outbox event - a claim never exists
     * without its graph edges, its first audit row, or the trigger that
     * gets it scored. The outbox row is published by OutboxPublisher on
     * its own schedule, not here, so a slow or unreachable Kafka broker
     * can never make claim creation itself fail or block.
     */
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
        outboxService.enqueue(saved.getId(), CLAIM_SUBMITTED_TOPIC, new ClaimSubmittedEvent(saved.getId()));
        return saved;
    }

    /**
     * Moves a claim to a new status, enforcing the legal transition map
     * (ClaimTransitions) and, for a human override of a fraud flag, that
     * a reason was given. Locks the claim row for the whole transaction
     * so a concurrent transition on the same claim can't interleave and
     * fork the audit hash chain.
     * <p>
     * Two distinct failure modes, two distinct statuses (M8): a
     * transition that doesn't exist for ANY role (e.g. skipping review
     * entirely) is a 409 - the request doesn't make sense regardless of
     * who's asking. A transition that exists but not for this actor's
     * role (e.g. an ADJUSTER trying to clear a fraud flag) is a 403 -
     * an authorization failure. Conflating these into one CONFLICT
     * response, as this method did before M8, made "wrong role" and
     * "no such transition" indistinguishable to a caller.
     */
    @Transactional
    public Claim transitionStatus(UUID claimId, ClaimStatus toStatus, String reason,
                                   String actorId, ActorRole actorRole) {
        Claim claim = claimRepository.findByIdForUpdate(claimId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Claim not found: " + claimId));

        ClaimStatus fromStatus = claim.getStatus();
        if (!ClaimTransitions.isDefined(fromStatus, toStatus)) {
            throw new ResponseStatusException(HttpStatus.CONFLICT,
                    "No such transition: " + fromStatus + " -> " + toStatus);
        }
        if (!ClaimTransitions.isAllowed(fromStatus, toStatus, actorRole)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN,
                    actorRole + " may not perform " + fromStatus + " -> " + toStatus);
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

    /**
     * Applies a scoring result consumed from the claim.scored Kafka
     * topic: appends a FRAUD_SCORED audit event carrying the score,
     * explanation, and model version, and transitions the claim to
     * FLAGGED (if decisionHint is "FLAG") or UNDER_REVIEW otherwise -
     * but only if that transition is legal from the claim's current
     * state. A human may already have acted on the claim by the time
     * the score arrives; when that happens, the score is still
     * recorded for the audit trail, it just doesn't force a transition.
     * <p>
     * Idempotent by construction: at-least-once Kafka delivery means
     * the same (claimId, modelVersion) score WILL arrive more than
     * once eventually, and reprocessing it must be a safe no-op rather
     * than a duplicate audit row or a rejected illegal transition.
     */
    @Transactional
    public void applyScore(UUID claimId, BigDecimal fraudScore, String decisionHint, String ringId,
                            String explanationJson, String modelVersion) {
        if (claimAuditEventRepository.existsByClaimIdAndModelVersionAndEventType(
                claimId, modelVersion, AuditEventType.FRAUD_SCORED)) {
            return;
        }

        Claim claim = claimRepository.findByIdForUpdate(claimId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Claim not found: " + claimId));

        ClaimStatus fromStatus = claim.getStatus();
        ClaimStatus targetStatus = "FLAG".equals(decisionHint) ? ClaimStatus.FLAGGED : ClaimStatus.UNDER_REVIEW;
        ClaimStatus toStatus = fromStatus;

        if (ClaimTransitions.isAllowed(fromStatus, targetStatus, ActorRole.SYSTEM)) {
            claim.setStatus(targetStatus);
            claimRepository.save(claim);
            toStatus = targetStatus;
        }

        auditService.append(claimId, AuditEventType.FRAUD_SCORED, fromStatus, toStatus, SCORING_ACTOR_ID,
                ActorRole.SYSTEM, null, fraudScore, ringId, explanationJson, modelVersion);
    }

    /**
     * Records an already-generated investigator narrative (the local-LLM
     * text from scoring/app/narrative.py, sent here once a viewer decides
     * it's worth keeping) as a NARRATIVE_GENERATED audit event, so it gets
     * the same tamper-evident, hash-chained treatment as every other
     * decision on this claim - reproducible proof of exactly what an
     * investigator read and which model version produced it, not just a
     * response that flowed through a browser once and was gone. Never a
     * status transition (fromStatus/toStatus are both the claim's current
     * status): generating a narrative doesn't change what the claim IS,
     * only what's on record about it. Reuses AuditService.append() and its
     * existing field list unchanged - see docs/EXECUTION_PLAN.md M3 on why
     * that list must never drift between append() and verify().
     */
    @Transactional
    public void recordNarrative(UUID claimId, String narrative, boolean grounded, String modelVersion,
                                 String actorId, ActorRole actorRole) {
        Claim claim = claimRepository.findByIdForUpdate(claimId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Claim not found: " + claimId));

        Map<String, Object> explanation = new LinkedHashMap<>();
        explanation.put("narrative", narrative);
        explanation.put("grounded", grounded);
        String explanationJson;
        try {
            explanationJson = objectMapper.writeValueAsString(explanation);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("Could not serialize narrative for the audit log", e);
        }

        auditService.append(claimId, AuditEventType.NARRATIVE_GENERATED, claim.getStatus(), claim.getStatus(),
                actorId, actorRole, null, null, null, explanationJson, modelVersion);
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

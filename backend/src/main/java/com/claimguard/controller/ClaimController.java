package com.claimguard.controller;

import com.claimguard.domain.ActorRole;
import com.claimguard.domain.Claim;
import com.claimguard.dto.AuditEventResponse;
import com.claimguard.dto.AuditVerificationResponse;
import com.claimguard.dto.ClaimRequest;
import com.claimguard.dto.ClaimResponse;
import com.claimguard.dto.TransitionRequest;
import com.claimguard.service.AuditService;
import com.claimguard.service.ClaimService;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.net.URI;
import java.util.List;
import java.util.UUID;

/**
 * Claim intake, read, workflow transitions, and audit trail access. No
 * fraud scoring yet - that lands once the Python scoring service
 * (M5-M7) is wired up.
 * <p>
 * The actor identity for a transition comes from request headers
 * (X-Actor-Id, X-Actor-Role) as a stand-in for a real authenticated
 * principal; M8 replaces these two headers with the real thing without
 * changing anything below the controller.
 */
@RestController
@RequestMapping("/api/claims")
public class ClaimController {

    private final ClaimService claimService;
    private final AuditService auditService;

    public ClaimController(ClaimService claimService, AuditService auditService) {
        this.claimService = claimService;
        this.auditService = auditService;
    }

    @PostMapping
    public ResponseEntity<ClaimResponse> createClaim(@Valid @RequestBody ClaimRequest request) {
        Claim saved = claimService.createClaim(request);
        return ResponseEntity
                .created(URI.create("/api/claims/" + saved.getId()))
                .body(ClaimResponse.from(saved));
    }

    @GetMapping("/{id}")
    public ClaimResponse getClaim(@PathVariable UUID id) {
        return ClaimResponse.from(claimService.getClaim(id));
    }

    @GetMapping
    public List<ClaimResponse> listClaims() {
        return claimService.listClaims().stream()
                .map(ClaimResponse::from)
                .toList();
    }

    /** Moves a claim to a new status if the transition is legal for the calling actor's role, appending an audit event either way (success updates the claim; failure never gets this far). */
    @PostMapping("/{id}/transitions")
    public ClaimResponse transition(@PathVariable UUID id,
                                     @Valid @RequestBody TransitionRequest request,
                                     @RequestHeader("X-Actor-Id") String actorId,
                                     @RequestHeader("X-Actor-Role") ActorRole actorRole) {
        Claim updated = claimService.transitionStatus(id, request.toStatus(), request.reason(), actorId, actorRole);
        return ClaimResponse.from(updated);
    }

    /** The full audit trail for a claim, oldest first. */
    @GetMapping("/{id}/audit")
    public List<AuditEventResponse> audit(@PathVariable UUID id) {
        return auditService.history(id).stream()
                .map(AuditEventResponse::from)
                .toList();
    }

    /** Recomputes the claim's hash chain and reports whether it's intact. */
    @GetMapping("/{id}/audit/verify")
    public AuditVerificationResponse verifyAudit(@PathVariable UUID id) {
        List<AuditEventResponse> events = audit(id);
        boolean valid = auditService.verify(id);
        return new AuditVerificationResponse(valid, events.size());
    }
}

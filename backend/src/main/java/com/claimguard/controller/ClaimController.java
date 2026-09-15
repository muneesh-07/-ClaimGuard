package com.claimguard.controller;

import com.claimguard.domain.Claim;
import com.claimguard.dto.AuditEventResponse;
import com.claimguard.dto.AuditVerificationResponse;
import com.claimguard.dto.ClaimRequest;
import com.claimguard.dto.ClaimResponse;
import com.claimguard.dto.TransitionRequest;
import com.claimguard.security.AuthenticatedActor;
import com.claimguard.service.AuditService;
import com.claimguard.service.ClaimService;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.net.URI;
import java.util.List;
import java.util.UUID;

/**
 * Claim intake, read, workflow transitions, and audit trail access.
 * <p>
 * The actor identity for a transition comes from the authenticated
 * principal (see security/) - JwtAuthenticationFilter populates it from
 * a bearer token issued by POST /api/auth/login. Only the transitions
 * endpoint requires authentication at all (see SecurityConfig); which
 * role may perform which transition is enforced in
 * ClaimService.transitionStatus, not here.
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

    /** Moves a claim to a new status if the transition is legal for the calling actor's role. Requires authentication - see SecurityConfig. */
    @PostMapping("/{id}/transitions")
    public ClaimResponse transition(@PathVariable UUID id,
                                     @Valid @RequestBody TransitionRequest request,
                                     Authentication authentication) {
        AuthenticatedActor actor = (AuthenticatedActor) authentication.getPrincipal();
        Claim updated = claimService.transitionStatus(id, request.toStatus(), request.reason(),
                actor.username(), actor.role());
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

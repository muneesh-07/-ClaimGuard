package com.claimguard.controller;

import com.claimguard.domain.Claim;
import com.claimguard.dto.ClaimRequest;
import com.claimguard.dto.ClaimResponse;
import com.claimguard.service.ClaimService;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.net.URI;
import java.util.List;
import java.util.UUID;

/**
 * Claim intake and read. No workflow transitions or fraud scoring yet -
 * those land once the state machine and audit log (M3) and the Python
 * scoring service (M5-M7) are wired up.
 */
@RestController
@RequestMapping("/api/claims")
public class ClaimController {

    private final ClaimService claimService;

    public ClaimController(ClaimService claimService) {
        this.claimService = claimService;
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
}

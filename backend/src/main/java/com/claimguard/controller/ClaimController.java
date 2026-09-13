package com.claimguard.controller;

import com.claimguard.domain.Claim;
import com.claimguard.dto.ClaimRequest;
import com.claimguard.repository.ClaimRepository;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;

import java.util.UUID;

/**
 * Deliberately minimal for this step: create a claim, fetch a claim.
 * No workflow transitions, no fraud scoring, no Kafka events yet -
 * this step is only about proving Java <-> Postgres persistence works.
 */
@RestController
@RequestMapping("/api/claims")
public class ClaimController {

    private final ClaimRepository claimRepository;

    public ClaimController(ClaimRepository claimRepository) {
        this.claimRepository = claimRepository;
    }

    @PostMapping
    public ResponseEntity<Claim> createClaim(@Valid @RequestBody ClaimRequest request) {
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
        return ResponseEntity.ok(saved);
    }

    @GetMapping("/{id}")
    public ResponseEntity<Claim> getClaim(@PathVariable UUID id) {
        Claim claim = claimRepository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Claim not found: " + id));
        return ResponseEntity.ok(claim);
    }

    @GetMapping
    public ResponseEntity<Iterable<Claim>> listClaims() {
        return ResponseEntity.ok(claimRepository.findAll());
    }
}

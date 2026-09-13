package com.claimguard.service;

import com.claimguard.domain.Claim;
import com.claimguard.dto.ClaimRequest;
import com.claimguard.repository.ClaimRepository;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;
import java.util.UUID;

/**
 * Owns the transaction boundary for claim intake and lookup. Controllers
 * never talk to ClaimRepository directly: once the workflow state machine
 * and the audit log land, a status transition and its audit entry have to
 * commit together or not at all, and that only works if the boundary is
 * already here rather than split across a controller method.
 */
@Service
public class ClaimService {

    private final ClaimRepository claimRepository;
    private final EntityService entityService;

    public ClaimService(ClaimRepository claimRepository, EntityService entityService) {
        this.claimRepository = claimRepository;
        this.entityService = entityService;
    }

    /** Persists a new claim and, in the same transaction, resolves and links the entities (phone/address/shop) it references - a claim never exists without its graph edges. */
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

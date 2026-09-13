package com.claimguard.controller;

import com.claimguard.dto.ClaimResponse;
import com.claimguard.dto.ResolveBacklogResponse;
import com.claimguard.service.EntityService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.UUID;

/**
 * Read access into the entity graph's raw material, plus the maintenance
 * endpoint that resolves entities for bulk-loaded claims. Mainly a
 * debugging and demo tool today - "does this phone number really tie
 * these claims together?" - ahead of the Python service that will query
 * the graph properly once M5/M6 land.
 */
@RestController
@RequestMapping("/api/entities")
public class EntityController {

    private final EntityService entityService;

    public EntityController(EntityService entityService) {
        this.entityService = entityService;
    }

    /** All claims that reference the given entity (same phone number, address, or shop). */
    @GetMapping("/{id}/claims")
    public List<ClaimResponse> claimsForEntity(@PathVariable UUID id) {
        return entityService.claimsForEntity(id).stream()
                .map(ClaimResponse::from)
                .toList();
    }

    /**
     * Resolves entities for every claim that doesn't have any yet - for
     * claims loaded straight into Postgres via COPY (see
     * tools/gen_rings.py) rather than through POST /api/claims. Safe to
     * call repeatedly; already-resolved claims are skipped.
     */
    @PostMapping("/resolve-backlog")
    public ResolveBacklogResponse resolveBacklog() {
        return new ResolveBacklogResponse(entityService.resolveBacklog());
    }
}

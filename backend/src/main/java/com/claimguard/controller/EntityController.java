package com.claimguard.controller;

import com.claimguard.dto.ClaimResponse;
import com.claimguard.service.EntityService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.UUID;

/**
 * Read access into the entity graph's raw material. Mainly a debugging
 * and demo tool today - "does this phone number really tie these claims
 * together?" - ahead of the Python service that will query the graph
 * properly once M5/M6 land.
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
}

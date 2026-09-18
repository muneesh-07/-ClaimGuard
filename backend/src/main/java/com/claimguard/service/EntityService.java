package com.claimguard.service;

import com.claimguard.domain.Claim;
import com.claimguard.domain.ClaimEntityLink;
import com.claimguard.domain.ClaimEntityLinkId;
import com.claimguard.domain.EntityType;
import com.claimguard.entityresolution.AddressNormalizer;
import com.claimguard.entityresolution.PhoneNormalizer;
import com.claimguard.entityresolution.ShopNormalizer;
import com.claimguard.repository.ClaimEntityLinkRepository;
import com.claimguard.repository.ClaimRepository;
import com.claimguard.repository.ResolvedEntityRepository;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

/**
 * Turns a claim's raw contact fields into graph edges: normalizes each
 * field, upserts the resulting canonical entity, and records the link
 * back to the claim. This is the raw material the fraud-ring graph is
 * built from - without it `entities`/`claim_entities` stay empty and
 * there is no graph, just claims that happen to have phone numbers.
 */
@Service
public class EntityService {

    private final ResolvedEntityRepository resolvedEntityRepository;
    private final ClaimEntityLinkRepository claimEntityLinkRepository;
    private final ClaimRepository claimRepository;
    private final PhoneNormalizer phoneNormalizer;
    private final AddressNormalizer addressNormalizer;
    private final ShopNormalizer shopNormalizer;
    private final TransactionTemplate newTransaction;

    public EntityService(ResolvedEntityRepository resolvedEntityRepository,
                          ClaimEntityLinkRepository claimEntityLinkRepository,
                          ClaimRepository claimRepository,
                          PhoneNormalizer phoneNormalizer,
                          AddressNormalizer addressNormalizer,
                          ShopNormalizer shopNormalizer,
                          PlatformTransactionManager transactionManager) {
        this.resolvedEntityRepository = resolvedEntityRepository;
        this.claimEntityLinkRepository = claimEntityLinkRepository;
        this.claimRepository = claimRepository;
        this.phoneNormalizer = phoneNormalizer;
        this.addressNormalizer = addressNormalizer;
        this.shopNormalizer = shopNormalizer;
        this.newTransaction = new TransactionTemplate(transactionManager);
        this.newTransaction.setPropagationBehavior(TransactionTemplate.PROPAGATION_REQUIRES_NEW);
    }

    /**
     * Resolves and links every entity a claim references (phone, address,
     * and - if present - repair shop). Must run in the same transaction as
     * the claim insert: if the claim commits but this doesn't, the graph
     * silently loses an edge for a claim that looks perfectly normal.
     */
    @Transactional
    public void resolveAndLink(Claim claim) {
        link(claim, EntityType.PHONE, "CLAIMANT_PHONE",
                claim.getClaimantPhone(), phoneNormalizer.normalize(claim.getClaimantPhone()));

        link(claim, EntityType.ADDRESS, "CLAIMANT_ADDRESS",
                claim.getClaimantAddress(), addressNormalizer.normalize(claim.getClaimantAddress()));

        String repairShopName = claim.getRepairShopName();
        if (repairShopName != null && !repairShopName.isBlank()) {
            link(claim, EntityType.SHOP, "REPAIR_SHOP",
                    repairShopName, shopNormalizer.normalize(repairShopName));
        }
    }

    /** Upserts the canonical entity for one (type, raw value) pair and records the claim's link to it, keeping the original raw value for the audit trail. */
    private void link(Claim claim, EntityType entityType, String role, String rawValue, String canonicalValue) {
        UUID entityId = resolvedEntityRepository.upsert(
                UUID.randomUUID(), entityType.name(), canonicalValue, Instant.now());

        ClaimEntityLinkId linkId = new ClaimEntityLinkId(claim.getId(), entityId, role);
        claimEntityLinkRepository.save(ClaimEntityLink.builder()
                .id(linkId)
                .rawValue(rawValue)
                .build());
    }

    /** All claims that share the given entity - e.g. every claim filed with the same phone number. */
    @Transactional(readOnly = true)
    public List<Claim> claimsForEntity(UUID entityId) {
        if (!resolvedEntityRepository.existsById(entityId)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Entity not found: " + entityId);
        }
        List<UUID> claimIds = claimEntityLinkRepository.findClaimIdsByEntityId(entityId);
        return claimRepository.findAllById(claimIds);
    }

    /**
     * Runs resolveAndLink() over every claim that doesn't have entity
     * links yet - a one-off resolution pass for claims that were
     * bulk-loaded straight into Postgres via COPY (see tools/gen_rings.py)
     * instead of through POST /api/claims. Reuses the exact same
     * normalizers and linking logic as live intake, rather than
     * reimplementing them, so a bulk-loaded claim and an API-submitted
     * claim can never resolve differently. Safe to re-run: claims that
     * already have links are skipped.
     * <p>
     * Deliberately NOT one big @Transactional method: at 50k+ claims,
     * a single Hibernate session accumulating tens of thousands of
     * managed entities gets progressively slower with every flush (each
     * one re-checks the whole session for dirty entities), which in
     * practice made this pass effectively never finish. Each claim gets
     * its own short-lived transaction instead, so the persistence context
     * never grows past one claim's worth of state.
     */
    public int resolveBacklog() {
        List<UUID> unresolvedIds = claimRepository.findIdsWithoutEntityLinks();
        for (UUID claimId : unresolvedIds) {
            newTransaction.executeWithoutResult(status ->
                    claimRepository.findById(claimId).ifPresent(this::resolveAndLink));
        }
        return unresolvedIds.size();
    }
}

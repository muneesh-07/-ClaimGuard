package com.claimguard.domain;

import jakarta.persistence.Embeddable;
import lombok.AllArgsConstructor;
import lombok.EqualsAndHashCode;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.io.Serializable;
import java.util.UUID;

/**
 * The composite primary key of a claim-to-entity link: which claim,
 * which entity, and in what role (e.g. CLAIMANT_PHONE). A claim can
 * reference the same entity twice only under different roles.
 */
@Embeddable
@Getter
@NoArgsConstructor
@AllArgsConstructor
@EqualsAndHashCode
public class ClaimEntityLinkId implements Serializable {

    private UUID claimId;
    private UUID entityId;
    private String role;
}

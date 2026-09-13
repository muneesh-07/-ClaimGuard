package com.claimguard.domain;

import jakarta.persistence.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * Links one claim to one resolved entity: "this claim referenced this
 * phone number, as its claimant phone". Keeps the raw, as-typed value
 * alongside the link so the audit trail never has to reconstruct what
 * the claimant actually entered from the normalized form. Maps to the
 * `claim_entities` table from V2__entities.sql.
 */
@Entity
@Table(name = "claim_entities")
@Getter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class ClaimEntityLink {

    @EmbeddedId
    private ClaimEntityLinkId id;

    @Column(name = "raw_value", nullable = false)
    private String rawValue;
}

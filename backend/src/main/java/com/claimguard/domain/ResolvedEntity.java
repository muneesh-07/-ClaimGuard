package com.claimguard.domain;

import jakarta.persistence.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.Instant;
import java.util.UUID;

/**
 * One resolved real-world thing (a phone number, an address, a repair
 * shop) that one or more claims reference. This is the graph's raw
 * material: two claims sharing a row here is what a fraud ring is built
 * out of. Maps to the `entities` table from V2__entities.sql.
 */
@Entity
@Table(name = "entities")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class ResolvedEntity {

    @Id
    private UUID id;

    @Enumerated(EnumType.STRING)
    @Column(name = "entity_type", nullable = false)
    private EntityType entityType;

    @Column(name = "canonical_value", nullable = false)
    private String canonicalValue;

    @Column(name = "claim_count", nullable = false)
    private int claimCount;

    @Column(name = "first_seen_at", nullable = false)
    private Instant firstSeenAt;
}

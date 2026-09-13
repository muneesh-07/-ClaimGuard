package com.claimguard.repository;

import com.claimguard.domain.EntityType;
import com.claimguard.domain.ResolvedEntity;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

public interface ResolvedEntityRepository extends JpaRepository<ResolvedEntity, UUID> {

    /** Looks up the single entity row for a given type + canonical value - mainly useful for tests and debugging, since production code goes through upsert(). */
    Optional<ResolvedEntity> findByEntityTypeAndCanonicalValue(EntityType entityType, String canonicalValue);

    /**
     * Inserts a new entity row, or - if one already exists for this
     * (entityType, canonicalValue) pair - bumps its claim_count instead.
     * Done as a single atomic upsert (not find-then-insert) so two claims
     * for the same phone number arriving at the same time can't race and
     * create two entity rows for what is really one phone number.
     */
    @Query(value = """
            INSERT INTO entities (id, entity_type, canonical_value, claim_count, first_seen_at)
            VALUES (:id, :entityType, :canonicalValue, 1, :firstSeenAt)
            ON CONFLICT (entity_type, canonical_value)
            DO UPDATE SET claim_count = entities.claim_count + 1
            RETURNING id
            """, nativeQuery = true)
    UUID upsert(@Param("id") UUID id,
                @Param("entityType") String entityType,
                @Param("canonicalValue") String canonicalValue,
                @Param("firstSeenAt") Instant firstSeenAt);
}

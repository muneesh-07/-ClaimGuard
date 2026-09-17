package com.claimguard.repository;

import com.claimguard.domain.OutboxEvent;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

public interface OutboxEventRepository extends JpaRepository<OutboxEvent, UUID> {

    /** Unsent rows, oldest first - what OutboxPublisher polls on its schedule. */
    List<OutboxEvent> findBySentAtIsNullOrderByCreatedAtAsc();

    /**
     * Stamps one row sent, as a single UPDATE issued through this repository's own
     * Spring Data JPA proxy - deliberately NOT an entity fetch + setter + implicit
     * flush called from inside OutboxPublisher, because that pattern only commits
     * if the calling method's @Transactional actually applies, and a same-class
     * ("self-invocation") call bypasses Spring's transactional proxy silently: no
     * exception, no warning, the entity is mutated in memory and then just discarded
     * once the method returns. That's exactly what let OutboxPublisher republish the
     * same row every 2-second poll forever - Kafka delivery always succeeded, but
     * sent_at was never actually persisted. @Transactional here (not on the caller)
     * is what makes this method carry its own real transaction no matter who calls it,
     * which a bare @Modifying @Query alone does not guarantee - Hibernate refuses to
     * execute an update/delete query outside an active transaction.
     */
    @Transactional
    @Modifying
    @Query("UPDATE OutboxEvent e SET e.sentAt = :sentAt WHERE e.id = :id")
    void markSent(@Param("id") UUID id, @Param("sentAt") Instant sentAt);
}

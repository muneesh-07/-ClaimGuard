package com.claimguard.repository;

import com.claimguard.domain.OutboxEvent;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.UUID;

public interface OutboxEventRepository extends JpaRepository<OutboxEvent, UUID> {

    /** Unsent rows, oldest first - what OutboxPublisher polls on its schedule. */
    List<OutboxEvent> findBySentAtIsNullOrderByCreatedAtAsc();
}

package com.claimguard.service;

import com.claimguard.domain.OutboxEvent;
import com.claimguard.repository.OutboxEventRepository;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.UUID;

/**
 * Writes outbox rows - the "transactional" half of the transactional
 * outbox pattern. Callers use this from within their own
 * {@code @Transactional} method (see ClaimService.createClaim) so the
 * outbox row commits or rolls back together with whatever domain
 * change produced it. Nothing here talks to Kafka directly - that's
 * OutboxPublisher's job, on its own schedule.
 */
@Service
public class OutboxService {

    private final OutboxEventRepository outboxEventRepository;
    private final ObjectMapper objectMapper;

    public OutboxService(OutboxEventRepository outboxEventRepository, ObjectMapper objectMapper) {
        this.outboxEventRepository = outboxEventRepository;
        this.objectMapper = objectMapper;
    }

    /** Serializes the payload to JSON and queues it for publishing to the given Kafka topic. */
    @Transactional
    public void enqueue(UUID aggregateId, String topic, Object payload) {
        String json;
        try {
            json = objectMapper.writeValueAsString(payload);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("Failed to serialize outbox payload for " + topic, e);
        }

        outboxEventRepository.save(OutboxEvent.builder()
                .id(UUID.randomUUID())
                .aggregateId(aggregateId)
                .topic(topic)
                .payload(json)
                .createdAt(Instant.now())
                .build());
    }
}

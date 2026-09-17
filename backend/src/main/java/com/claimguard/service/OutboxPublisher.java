package com.claimguard.service;

import com.claimguard.domain.OutboxEvent;
import com.claimguard.repository.OutboxEventRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.List;
import java.util.concurrent.TimeUnit;

/**
 * The other half of the transactional outbox pattern: on a fixed
 * schedule, publish every unsent row to Kafka and mark it sent -
 * outside the transaction that created it, so a slow or unreachable
 * broker never blocks claim creation itself. An unsent row (send
 * failed, or the app crashed before this ran) is simply retried on the
 * next tick, which is what makes the whole thing at-least-once instead
 * of "usually once, silently dropped on a bad day."
 * <p>
 * Disableable via claimguard.outbox.publisher.enabled=false (see
 * src/test/resources/application.yml) - without this, every
 * Testcontainers-based test kept this bean polling on a schedule after
 * that test's Postgres container was already torn down, spamming
 * connection-timeout errors and delaying the surefire JVM's exit by
 * ~30s per test class. None of the current tests assert on Kafka
 * delivery, so disabling the publisher (not the outbox rows themselves,
 * which still get written) costs nothing in test coverage.
 */
@Service
@ConditionalOnProperty(name = "claimguard.outbox.publisher.enabled", havingValue = "true", matchIfMissing = true)
public class OutboxPublisher {

    private static final Logger log = LoggerFactory.getLogger(OutboxPublisher.class);

    private final OutboxEventRepository outboxEventRepository;
    private final KafkaTemplate<String, String> kafkaTemplate;

    public OutboxPublisher(OutboxEventRepository outboxEventRepository, KafkaTemplate<String, String> kafkaTemplate) {
        this.outboxEventRepository = outboxEventRepository;
        this.kafkaTemplate = kafkaTemplate;
    }

    /** Publishes every unsent outbox row, oldest first. Runs every 2 seconds. */
    @Scheduled(fixedDelay = 2000)
    public void publishPending() {
        List<OutboxEvent> pending = outboxEventRepository.findBySentAtIsNullOrderByCreatedAtAsc();
        for (OutboxEvent event : pending) {
            try {
                kafkaTemplate.send(event.getTopic(), event.getAggregateId().toString(), event.getPayload())
                        .get(5, TimeUnit.SECONDS);
                outboxEventRepository.markSent(event.getId(), Instant.now());
            } catch (Exception e) {
                log.warn("Failed to publish outbox event {} to {} - will retry next poll",
                        event.getId(), event.getTopic(), e);
            }
        }
    }
}

package com.claimguard.domain;

import jakarta.persistence.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.time.Instant;
import java.util.UUID;

/**
 * One row in the transactional outbox: a Kafka message that needs to
 * be published, written in the same transaction as whatever domain
 * event caused it. {@link com.claimguard.service.OutboxPublisher}
 * is the only thing that ever reads {@code sent_at IS NULL} rows and
 * marks them sent - nothing else should touch this table.
 */
@Entity
@Table(name = "outbox")
@Getter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class OutboxEvent {

    @Id
    private UUID id;

    @Column(name = "aggregate_id", nullable = false)
    private UUID aggregateId;

    @Column(nullable = false)
    private String topic;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(nullable = false, columnDefinition = "jsonb")
    private String payload;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "sent_at")
    private Instant sentAt;

    /** Stamps this row as published. Called only by OutboxPublisher after a successful Kafka send. */
    public void markSent(Instant sentAt) {
        this.sentAt = sentAt;
    }
}

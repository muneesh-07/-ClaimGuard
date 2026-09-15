package com.claimguard.messaging;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.util.UUID;

/**
 * The payload published to the {@code claim.submitted} Kafka topic.
 * Snake-case on purpose (unlike the rest of the Java API, which is
 * camelCase) - this crosses into the Python service, and its Pydantic
 * models use Python's native snake_case field names. Matching that
 * here means the Python consumer needs zero name-mapping.
 */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record ClaimSubmittedEvent(UUID claimId) {
}

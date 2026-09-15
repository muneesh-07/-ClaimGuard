package com.claimguard;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * Entry point for the ClaimGuard Java backend.
 * <p>
 * This service owns claim intake, workflow state, RBAC, and the audit
 * log. Fraud scoring is delegated to the Python scoring service (see
 * scoring/) and wired in asynchronously via a transactional outbox and
 * Kafka - see OutboxPublisher and ScoringResultConsumer.
 */
@SpringBootApplication
@EnableScheduling
public class ClaimGuardApplication {

    public static void main(String[] args) {
        SpringApplication.run(ClaimGuardApplication.class, args);
    }

}

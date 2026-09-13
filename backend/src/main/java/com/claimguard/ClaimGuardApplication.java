package com.claimguard;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Entry point for the ClaimGuard Java backend.
 * <p>
 * This service owns claim intake, workflow state, RBAC, and the audit log.
 * Fraud scoring and document extraction are delegated to the Python AI
 * service (see claimguard-ai/) and called over REST.
 */
@SpringBootApplication
public class ClaimGuardApplication {

    public static void main(String[] args) {
        SpringApplication.run(ClaimGuardApplication.class, args);
    }

}

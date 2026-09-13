package com.claimguard.controller;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.Instant;
import java.util.Map;

/**
 * Minimal endpoint to confirm the service is up before we wire in
 * claim intake, Postgres, and Kafka. Intentionally has no dependencies
 * on anything else so it's the first thing that should ever go green.
 */
@RestController
public class HealthController {

    @GetMapping("/api/health")
    public Map<String, Object> health() {
        return Map.of(
                "status", "UP",
                "service", "claimguard-backend",
                "timestamp", Instant.now().toString()
        );
    }

}

package com.claimguard.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.UUID;

/**
 * Consumes the claim.scored topic the Python scoring service publishes
 * to, and closes the async loop: appends a FRAUD_SCORED audit event and
 * transitions the claim (see ClaimService.applyScore). Deserializes
 * into a plain JsonNode rather than a typed DTO deliberately - Java
 * only needs to read a handful of top-level scalar fields to decide
 * what to do; the full "explanation" object is Python's structure to
 * own, and gets stored into explanation_json verbatim without Java
 * needing to understand its internal shape.
 */
@Service
public class ScoringResultConsumer {

    public static final String CLAIM_SCORED_TOPIC = "claim.scored";

    private static final Logger log = LoggerFactory.getLogger(ScoringResultConsumer.class);

    private final ClaimService claimService;
    private final ObjectMapper objectMapper;

    public ScoringResultConsumer(ClaimService claimService, ObjectMapper objectMapper) {
        this.claimService = claimService;
        this.objectMapper = objectMapper;
    }

    @KafkaListener(topics = CLAIM_SCORED_TOPIC, groupId = "claimguard-backend")
    public void onClaimScored(String payload) {
        JsonNode node;
        try {
            node = objectMapper.readTree(payload);
        } catch (Exception e) {
            log.error("Malformed claim.scored payload, dropping it: {}", payload, e);
            return;
        }

        UUID claimId = UUID.fromString(node.get("claim_id").asText());
        String modelVersion = node.get("model_version").asText();
        BigDecimal fraudScore = node.get("fraud_score").decimalValue();
        String decisionHint = node.get("decision_hint").asText();
        String ringId = node.hasNonNull("ring_id") ? node.get("ring_id").asText() : null;
        String explanationJson = node.has("explanation") ? node.get("explanation").toString() : null;

        claimService.applyScore(claimId, fraudScore, decisionHint, ringId, explanationJson, modelVersion);
    }
}

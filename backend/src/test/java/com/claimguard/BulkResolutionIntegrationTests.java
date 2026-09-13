package com.claimguard;

import com.claimguard.domain.EntityType;
import com.claimguard.dto.ClaimResponse;
import com.claimguard.dto.ResolveBacklogResponse;
import com.claimguard.repository.ResolvedEntityRepository;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.sql.Timestamp;
import java.time.LocalDate;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Simulates the M4 bulk-load path: a claim inserted straight into
 * Postgres via raw SQL (standing in for the `COPY` the plan calls for
 * at 50k scale) never goes through EntityService, so it has no
 * claim_entities rows. POST /api/entities/resolve-backlog is the
 * one-off pass that catches those claims up.
 */
@Testcontainers
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class BulkResolutionIntegrationTests {

    @Container
    @ServiceConnection
    static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:17.2");

    @Autowired
    private TestRestTemplate rest;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Autowired
    private ResolvedEntityRepository resolvedEntityRepository;

    // Inserts a claim directly with SQL, bypassing ClaimService/EntityService entirely - exactly what a COPY-loaded row looks like.
    private UUID insertClaimDirectly(String phone) {
        UUID id = UUID.randomUUID();
        jdbcTemplate.update("""
                INSERT INTO claims (id, claimant_name, policy_number, claim_amount, incident_date,
                                     claimant_phone, claimant_address, repair_shop_name, status,
                                     created_at, updated_at, version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'SUBMITTED', ?, ?, 0)
                """,
                id, "Bulk Loaded Claimant", "POL-90001", new java.math.BigDecimal("15000.00"),
                LocalDate.of(2026, 3, 1), phone, "1 Bulk Lane, Chennai", "Bulk Motors",
                Timestamp.from(java.time.Instant.now()), Timestamp.from(java.time.Instant.now()));
        return id;
    }

    @Test
    void resolveBacklogLinksEntitiesForClaimsLoadedOutsideTheApi() {
        UUID claimId = insertClaimDirectly("+91-9876500055");

        ResponseEntity<ResolveBacklogResponse> response =
                rest.postForEntity("/api/entities/resolve-backlog", null, ResolveBacklogResponse.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(response.getBody().claimsResolved()).isEqualTo(1);

        var entity = resolvedEntityRepository
                .findByEntityTypeAndCanonicalValue(EntityType.PHONE, "+919876500055")
                .orElseThrow();

        ResponseEntity<ClaimResponse[]> claimsForEntity = rest.getForEntity(
                "/api/entities/{id}/claims", ClaimResponse[].class, entity.getId());
        assertThat(claimsForEntity.getBody()).extracting(ClaimResponse::id).containsExactly(claimId);
    }

    @Test
    void resolveBacklogIsSafeToRunTwice() {
        insertClaimDirectly("+91-9876500066");

        rest.postForEntity("/api/entities/resolve-backlog", null, ResolveBacklogResponse.class);
        ResponseEntity<ResolveBacklogResponse> secondRun =
                rest.postForEntity("/api/entities/resolve-backlog", null, ResolveBacklogResponse.class);

        assertThat(secondRun.getBody().claimsResolved()).isEqualTo(0);
    }
}

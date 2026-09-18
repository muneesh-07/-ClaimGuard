package com.claimguard;

import com.claimguard.domain.EntityType;
import com.claimguard.domain.ResolvedEntity;
import com.claimguard.dto.ClaimRequest;
import com.claimguard.dto.ClaimResponse;
import com.claimguard.repository.ResolvedEntityRepository;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.math.BigDecimal;
import java.time.LocalDate;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * The entity-resolution acceptance test: three claims whose phone
 * numbers are the same real number in three different formats must
 * resolve to one entities row with claim_count = 3, and that entity's
 * claims endpoint must return all three claims.
 */
@Testcontainers
@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = "claimguard.outbox.publisher.enabled=false")
class EntityResolutionIntegrationTests {

    @Container
    @ServiceConnection
    static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:17.2");

    @Autowired
    private TestRestTemplate rest;

    @Autowired
    private ResolvedEntityRepository resolvedEntityRepository;

    @Test
    void sameNumberInThreeFormatsResolvesToOneEntityLinkedToAllThreeClaims() {
        String[] phoneFormats = {"+91-9876500011", "9876500011", "098765 00011"};
        String[] claimIds = new String[phoneFormats.length];

        for (int i = 0; i < phoneFormats.length; i++) {
            ClaimRequest request = new ClaimRequest(
                    "Claimant " + i,
                    "POL-2000" + i,
                    new BigDecimal("10000.00"),
                    LocalDate.of(2026, 1, 1 + i),
                    phoneFormats[i],
                    "Address " + i,
                    null);

            ResponseEntity<ClaimResponse> response = rest.postForEntity("/api/claims", request, ClaimResponse.class);
            assertThat(response.getStatusCode()).isEqualTo(HttpStatus.CREATED);
            claimIds[i] = response.getBody().id().toString();
        }

        ResolvedEntity entity = resolvedEntityRepository
                .findByEntityTypeAndCanonicalValue(EntityType.PHONE, "+919876500011")
                .orElseThrow();
        assertThat(entity.getClaimCount()).isEqualTo(3);

        ResponseEntity<ClaimResponse[]> claimsForEntity =
                rest.getForEntity("/api/entities/{id}/claims", ClaimResponse[].class, entity.getId());

        assertThat(claimsForEntity.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(claimsForEntity.getBody()).hasSize(3)
                .extracting(c -> c.id().toString())
                .containsExactlyInAnyOrder(claimIds);
    }
}

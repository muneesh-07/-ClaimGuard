package com.claimguard;

import com.claimguard.dto.ClaimRequest;
import com.claimguard.dto.ClaimResponse;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Runs the whole stack - Spring context, Flyway migrations, JPA - against
 * a real Postgres in a container. Also the proof that ddl-auto=validate
 * and the migrations actually agree: if V1/V2 drift from the entities,
 * the context fails to start and every test here fails with it.
 */
@Testcontainers
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class ClaimLifecycleTests {

    @Container
    @ServiceConnection
    static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:17.2");

    @Autowired
    private TestRestTemplate rest;

    @Test
    void createdClaimCanBeFetchedBack() {
        ClaimRequest request = new ClaimRequest(
                "Asha Menon",
                "POL-10021",
                new BigDecimal("45000.00"),
                LocalDate.of(2026, 8, 14),
                "+91-9876500011",
                "12 Lake View Road, Coimbatore",
                "SpeedFix Auto Works");

        ResponseEntity<ClaimResponse> createResponse = rest.postForEntity("/api/claims", request, ClaimResponse.class);

        assertThat(createResponse.getStatusCode()).isEqualTo(HttpStatus.CREATED);
        ClaimResponse created = createResponse.getBody();
        assertThat(created).isNotNull();
        assertThat(created.status().name()).isEqualTo("SUBMITTED");
        assertThat(created.id()).isNotNull();

        ResponseEntity<ClaimResponse> fetchResponse =
                rest.getForEntity("/api/claims/{id}", ClaimResponse.class, created.id());

        assertThat(fetchResponse.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(fetchResponse.getBody()).isNotNull();
        assertThat(fetchResponse.getBody().claimantName()).isEqualTo("Asha Menon");
        assertThat(fetchResponse.getBody().claimantPhone()).isEqualTo("+91-9876500011");
    }

    @Test
    void fetchingAnUnknownClaimReturnsAProblemDetail() {
        ResponseEntity<ProblemDetail> response =
                rest.getForEntity("/api/claims/{id}", ProblemDetail.class, UUID.randomUUID());

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
        assertThat(response.getBody()).isNotNull();
        assertThat(response.getBody().getDetail()).contains("Claim not found");
    }

    @Test
    void blankClaimantNameIsRejectedWithAProblemDetail() {
        ClaimRequest invalid = new ClaimRequest(
                "",
                "POL-10022",
                new BigDecimal("1000.00"),
                LocalDate.of(2026, 1, 1),
                "+91-9876500099",
                "1 Any Street",
                null);

        ResponseEntity<ProblemDetail> response = rest.postForEntity("/api/claims", invalid, ProblemDetail.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(response.getBody()).isNotNull();
        assertThat(response.getBody().getDetail()).contains("claimantName");
    }
}

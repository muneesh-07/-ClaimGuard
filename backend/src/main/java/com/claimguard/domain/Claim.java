package com.claimguard.domain;

import jakarta.persistence.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.util.UUID;

/**
 * A single insurance claim.
 * <p>
 * Note the fields beyond the obvious claim details: claimantPhone,
 * claimantAddress, and repairShopName. These look like plain contact
 * fields here, but they're exactly what the Python fraud service will
 * later use as graph nodes - two claims sharing the same phone number
 * or repair shop is how a fraud ring gets surfaced. They're modeled as
 * first-class columns now so that link is obvious from the schema itself.
 */
@Entity
@Table(name = "claims")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class Claim {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @Column(nullable = false)
    private String claimantName;

    @Column(nullable = false)
    private String policyNumber;

    @Column(nullable = false, precision = 14, scale = 2)
    private BigDecimal claimAmount;

    @Column(nullable = false)
    private LocalDate incidentDate;

    // --- Fields used later for cross-claim entity linking / graph construction ---
    @Column(nullable = false)
    private String claimantPhone;

    @Column(nullable = false)
    private String claimantAddress;

    private String repairShopName;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    @Builder.Default
    private ClaimStatus status = ClaimStatus.SUBMITTED;

    @Column(nullable = false, updatable = false)
    private Instant createdAt;

    @Column(nullable = false)
    private Instant updatedAt;

    // Optimistic locking: two adjusters acting on the same claim at once
    // should get a conflict, not a silently lost update.
    @Version
    private Long version;

    @PrePersist
    protected void onCreate() {
        Instant now = Instant.now();
        this.createdAt = now;
        this.updatedAt = now;
        if (this.status == null) {
            this.status = ClaimStatus.SUBMITTED;
        }
    }

    @PreUpdate
    protected void onUpdate() {
        this.updatedAt = Instant.now();
    }
}

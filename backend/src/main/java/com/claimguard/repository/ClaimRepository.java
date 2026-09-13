package com.claimguard.repository;

import com.claimguard.domain.Claim;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.UUID;

public interface ClaimRepository extends JpaRepository<Claim, UUID> {
    // Spring Data generates the implementation. We'll add query methods
    // here (e.g. findByClaimantPhone) once the graph-linking step needs them.
}

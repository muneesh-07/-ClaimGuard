package com.claimguard.repository;

import com.claimguard.domain.Claim;
import jakarta.persistence.LockModeType;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.Optional;
import java.util.UUID;

public interface ClaimRepository extends JpaRepository<Claim, UUID> {
    // Spring Data generates the implementation. We'll add query methods
    // here (e.g. findByClaimantPhone) once the graph-linking step needs them.

    /**
     * Fetches a claim with a Postgres row lock (SELECT ... FOR UPDATE)
     * held for the rest of the transaction, so two concurrent workflow
     * transitions on the same claim can't both read the same "current
     * status"/"latest audit event" and race each other into forking the
     * audit hash chain. The second caller blocks until the first commits.
     */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select c from Claim c where c.id = :id")
    Optional<Claim> findByIdForUpdate(@Param("id") UUID id);
}

package com.claimguard.repository;

import com.claimguard.domain.ClaimEntityLink;
import com.claimguard.domain.ClaimEntityLinkId;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;
import java.util.UUID;

public interface ClaimEntityLinkRepository extends JpaRepository<ClaimEntityLink, ClaimEntityLinkId> {

    /** All claim ids that reference the given entity - the "who else shares this?" query. */
    @Query("select l.id.claimId from ClaimEntityLink l where l.id.entityId = :entityId")
    List<UUID> findClaimIdsByEntityId(@Param("entityId") UUID entityId);
}

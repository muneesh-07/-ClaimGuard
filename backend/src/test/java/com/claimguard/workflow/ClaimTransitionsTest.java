package com.claimguard.workflow;

import com.claimguard.domain.ActorRole;
import com.claimguard.domain.ClaimStatus;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class ClaimTransitionsTest {

    @Test
    void adjusterCanMoveASubmittedClaimIntoReview() {
        assertThat(ClaimTransitions.isAllowed(ClaimStatus.SUBMITTED, ClaimStatus.UNDER_REVIEW, ActorRole.ADJUSTER))
                .isTrue();
    }

    @Test
    void adjusterCannotApproveASubmittedClaimDirectly() {
        assertThat(ClaimTransitions.isAllowed(ClaimStatus.SUBMITTED, ClaimStatus.APPROVED, ActorRole.ADJUSTER))
                .isFalse();
    }

    @Test
    void onlyAnInvestigatorCanClearAFlag() {
        assertThat(ClaimTransitions.isAllowed(ClaimStatus.FLAGGED, ClaimStatus.UNDER_REVIEW, ActorRole.INVESTIGATOR))
                .isTrue();
        assertThat(ClaimTransitions.isAllowed(ClaimStatus.FLAGGED, ClaimStatus.UNDER_REVIEW, ActorRole.ADJUSTER))
                .isFalse();
    }

    @Test
    void overridingAFlagToApprovedRequiresAReasonButOtherTransitionsDoNot() {
        assertThat(ClaimTransitions.requiresReason(ClaimStatus.FLAGGED, ClaimStatus.APPROVED)).isTrue();
        assertThat(ClaimTransitions.requiresReason(ClaimStatus.SUBMITTED, ClaimStatus.UNDER_REVIEW)).isFalse();
        assertThat(ClaimTransitions.requiresReason(ClaimStatus.FLAGGED, ClaimStatus.DENIED)).isFalse();
    }
}

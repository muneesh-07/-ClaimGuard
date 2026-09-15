package com.claimguard.workflow;

import com.claimguard.domain.ActorRole;
import com.claimguard.domain.ClaimStatus;

import java.util.Map;
import java.util.Set;

/**
 * The one legal transition map for a claim's lifecycle, from
 * docs/EXECUTION_PLAN.md M3. Anything not listed here is illegal no
 * matter who asks - this is what makes "a claim cannot skip review, and
 * only an investigator can overturn a fraud flag" a provable property of
 * the code rather than an assumption baked into scattered if-statements.
 */
public final class ClaimTransitions {

    private record Transition(ClaimStatus from, ClaimStatus to) {
    }

    private static final Map<Transition, Set<ActorRole>> ALLOWED_ROLES = Map.ofEntries(
            Map.entry(new Transition(ClaimStatus.SUBMITTED, ClaimStatus.UNDER_REVIEW),
                    Set.of(ActorRole.ADJUSTER, ActorRole.SYSTEM)),
            Map.entry(new Transition(ClaimStatus.SUBMITTED, ClaimStatus.FLAGGED),
                    Set.of(ActorRole.SYSTEM)),
            Map.entry(new Transition(ClaimStatus.UNDER_REVIEW, ClaimStatus.FLAGGED),
                    Set.of(ActorRole.ADJUSTER)),
            Map.entry(new Transition(ClaimStatus.UNDER_REVIEW, ClaimStatus.APPROVED),
                    Set.of(ActorRole.ADJUSTER)),
            Map.entry(new Transition(ClaimStatus.UNDER_REVIEW, ClaimStatus.DENIED),
                    Set.of(ActorRole.ADJUSTER)),
            Map.entry(new Transition(ClaimStatus.FLAGGED, ClaimStatus.UNDER_REVIEW),
                    Set.of(ActorRole.INVESTIGATOR)),
            Map.entry(new Transition(ClaimStatus.FLAGGED, ClaimStatus.DENIED),
                    Set.of(ActorRole.INVESTIGATOR)),
            Map.entry(new Transition(ClaimStatus.FLAGGED, ClaimStatus.APPROVED),
                    Set.of(ActorRole.INVESTIGATOR))
    );

    /** Transitions that are a human override of the fraud model's flag, and therefore must carry a reason. */
    private static final Set<Transition> REQUIRES_REASON = Set.of(
            new Transition(ClaimStatus.FLAGGED, ClaimStatus.APPROVED)
    );

    private ClaimTransitions() {
    }

    /**
     * Whether this (from, to) pair is a legal transition for ANY role -
     * i.e. whether it's in the map at all. Kept separate from
     * {@link #isAllowed} so a caller can tell "no such transition
     * exists, for anyone" (a 409 - the request doesn't make sense) apart
     * from "this transition exists, but not for this actor's role" (a
     * 403 - an authorization failure). Conflating the two into one
     * boolean is exactly what made every role-mismatch look identical
     * to a structurally-nonexistent transition before M8.
     */
    public static boolean isDefined(ClaimStatus from, ClaimStatus to) {
        return ALLOWED_ROLES.containsKey(new Transition(from, to));
    }

    /** Whether the given actor role is allowed to move a claim from one status directly to another. */
    public static boolean isAllowed(ClaimStatus from, ClaimStatus to, ActorRole actorRole) {
        Set<ActorRole> roles = ALLOWED_ROLES.get(new Transition(from, to));
        return roles != null && roles.contains(actorRole);
    }

    /** Whether this transition overrides a fraud flag and must therefore be justified with a reason. */
    public static boolean requiresReason(ClaimStatus from, ClaimStatus to) {
        return REQUIRES_REASON.contains(new Transition(from, to));
    }
}

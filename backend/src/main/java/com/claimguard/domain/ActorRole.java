package com.claimguard.domain;

/**
 * Who can act on a claim's workflow. ADJUSTER/INVESTIGATOR/AUDITOR are
 * real human roles, backed by a {@link User} row and enforced via JWT
 * authentication (M8); SYSTEM is never a login-able role - it's used
 * for actors that aren't a person: claim intake and the scoring
 * service (see ClaimService's INTAKE_ACTOR_ID/SCORING_ACTOR_ID).
 * AUDITOR is deliberately absent from every entry in
 * {@link com.claimguard.workflow.ClaimTransitions}'s allowed-roles map -
 * "auditor is read-only, including the audit log" isn't a special case
 * anywhere in the code, it falls out naturally from AUDITOR never being
 * listed as allowed to perform any transition.
 */
public enum ActorRole {
    ADJUSTER,
    INVESTIGATOR,
    AUDITOR,
    SYSTEM
}

package com.claimguard.domain;

/**
 * Who can act on a claim's workflow. Comes from a request header stub
 * for now (see ClaimController) - M8 swaps in the real authenticated
 * principal's role without changing anything downstream of this enum.
 */
public enum ActorRole {
    ADJUSTER,
    INVESTIGATOR,
    SYSTEM
}

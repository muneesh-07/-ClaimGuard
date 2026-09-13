package com.claimguard.dto;

/** How many claims the entity-resolution backlog pass processed. */
public record ResolveBacklogResponse(int claimsResolved) {
}

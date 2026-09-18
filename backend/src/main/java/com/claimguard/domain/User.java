package com.claimguard.domain;

import jakarta.persistence.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.Instant;
import java.util.UUID;

/**
 * A human who can log in and act on claims. Deliberately no
 * registration endpoint - accounts exist only via
 * {@link com.claimguard.security.DemoUserSeeder} (dev/demo) - and no
 * refresh tokens.
 */
@Entity
@Table(name = "users")
@Getter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class User {

    @Id
    private UUID id;

    @Column(nullable = false, unique = true)
    private String username;

    @Column(name = "password_hash", nullable = false)
    private String passwordHash;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private ActorRole role;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;
}

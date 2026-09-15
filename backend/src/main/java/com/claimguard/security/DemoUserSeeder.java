package com.claimguard.security;

import com.claimguard.domain.ActorRole;
import com.claimguard.domain.User;
import com.claimguard.repository.UserRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;

import java.time.Instant;
import java.util.UUID;

/**
 * Seeds one demo account per role on first startup, since there's no
 * registration flow (docs/EXECUTION_PLAN.md M8's scope discipline).
 * Password is hashed through the real BCryptPasswordEncoder bean, not
 * a pre-computed literal - so it's guaranteed to verify correctly
 * against whatever encoder AuthController actually uses. Safe to run
 * on every startup: does nothing once the users table is non-empty.
 */
@Component
public class DemoUserSeeder implements ApplicationRunner {

    /** Dev-only demo password, shared by all three seeded accounts - not a real credential, same convention as the dev DB/JWT secret already committed in this repo. Public so tests reference this constant instead of duplicating the literal. */
    public static final String DEMO_PASSWORD = "changeme123";

    private static final Logger log = LoggerFactory.getLogger(DemoUserSeeder.class);

    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;

    public DemoUserSeeder(UserRepository userRepository, PasswordEncoder passwordEncoder) {
        this.userRepository = userRepository;
        this.passwordEncoder = passwordEncoder;
    }

    @Override
    public void run(ApplicationArguments args) {
        if (userRepository.count() > 0) {
            return;
        }
        seed("adjuster1", ActorRole.ADJUSTER);
        seed("investigator1", ActorRole.INVESTIGATOR);
        seed("auditor1", ActorRole.AUDITOR);
        log.info("Seeded demo users adjuster1/investigator1/auditor1 (password: {})", DEMO_PASSWORD);
    }

    private void seed(String username, ActorRole role) {
        userRepository.save(User.builder()
                .id(UUID.randomUUID())
                .username(username)
                .passwordHash(passwordEncoder.encode(DEMO_PASSWORD))
                .role(role)
                .createdAt(Instant.now())
                .build());
    }
}

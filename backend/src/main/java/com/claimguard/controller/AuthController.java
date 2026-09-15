package com.claimguard.controller;

import com.claimguard.domain.User;
import com.claimguard.dto.LoginRequest;
import com.claimguard.dto.LoginResponse;
import com.claimguard.repository.UserRepository;
import com.claimguard.security.JwtService;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

/**
 * The one login endpoint this API has - no registration, no refresh
 * tokens, per docs/EXECUTION_PLAN.md M8's scope discipline. Demo
 * accounts come from DemoUserSeeder.
 */
@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;
    private final JwtService jwtService;

    public AuthController(UserRepository userRepository, PasswordEncoder passwordEncoder, JwtService jwtService) {
        this.userRepository = userRepository;
        this.passwordEncoder = passwordEncoder;
        this.jwtService = jwtService;
    }

    /** Exchanges a username/password for a bearer token. Deliberately the same error for "no such user" and "wrong password" - distinguishing them would tell an attacker which usernames exist. */
    @PostMapping("/login")
    public LoginResponse login(@Valid @RequestBody LoginRequest request) {
        User user = userRepository.findByUsername(request.username())
                .filter(u -> passwordEncoder.matches(request.password(), u.getPasswordHash()))
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Invalid username or password"));

        return new LoginResponse(jwtService.generateToken(user), user.getRole().name());
    }
}

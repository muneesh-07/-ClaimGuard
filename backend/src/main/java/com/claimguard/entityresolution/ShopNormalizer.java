package com.claimguard.entityresolution;

import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Locale;

/**
 * Strips common legal-entity suffixes and collapses whitespace/casing so
 * "SpeedFix Auto Works", "speedfix auto works", and "SPEEDFIX AUTO WORKS
 * PVT LTD" resolve to the same shop entity. Exact-match only, same
 * reasoning as AddressNormalizer - genuinely different spellings (e.g.
 * "Auto Works" vs "Autoworks") are a fuzzy-matching problem deferred to M9.
 */
@Component
public class ShopNormalizer {

    private static final List<String> SUFFIXES = List.of(
            "pvt ltd", "private limited", "pvt. ltd.",
            "& sons", "and sons",
            "ltd", "limited", "inc", "llc"
    );

    /** Lowercases, strips legal-entity suffixes, and collapses whitespace to a single canonical shop name. */
    public String normalize(String rawShopName) {
        String cleaned = rawShopName.toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9\\s&]", " ");
        for (String suffix : SUFFIXES) {
            cleaned = cleaned.replace(suffix, " ");
        }
        return cleaned.trim().replaceAll("\\s+", " ");
    }
}

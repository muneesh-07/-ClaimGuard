package com.claimguard.entityresolution;

import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * Reduces an address to a punctuation-stripped, abbreviation-expanded,
 * token-sorted form, so cosmetic differences - punctuation, casing, word
 * order, "Rd" vs "Road" - don't manufacture a distinct entity for what is
 * really the same address. Deliberately exact-match only: fuzzy matching
 * across genuinely different spellings is a separate Python batch job,
 * not this normalizer's job.
 */
@Component
public class AddressNormalizer {

    private static final Map<String, String> ABBREVIATIONS = Map.ofEntries(
            Map.entry("rd", "road"),
            Map.entry("st", "street"),
            Map.entry("ave", "avenue"),
            Map.entry("apt", "apartment"),
            Map.entry("blvd", "boulevard"),
            Map.entry("ln", "lane"),
            Map.entry("dr", "drive"),
            Map.entry("no", "number")
    );

    /** Lowercases, strips punctuation, expands common abbreviations, and sorts tokens so word order and formatting don't matter. */
    public String normalize(String rawAddress) {
        String cleaned = rawAddress.toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9\\s]", " ");
        List<String> tokens = new ArrayList<>();
        for (String token : cleaned.trim().split("\\s+")) {
            if (token.isBlank()) {
                continue;
            }
            tokens.add(ABBREVIATIONS.getOrDefault(token, token));
        }
        Collections.sort(tokens);
        return String.join(" ", tokens);
    }
}

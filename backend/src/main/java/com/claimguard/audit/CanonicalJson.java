package com.claimguard.audit;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;

import java.util.Map;
import java.util.TreeMap;

/**
 * Deterministic JSON serialization for one audit row's fields: sorted
 * keys, compact (no insignificant whitespace), nulls written out
 * explicitly. The hash chain in AuditService is only tamper-evident if
 * the same logical row always serializes to exactly the same bytes -
 * callers are responsible for pre-formatting values that could otherwise
 * vary (timestamps, decimals) before they reach this class.
 */
public final class CanonicalJson {

    private static final ObjectMapper MAPPER = new ObjectMapper()
            .configure(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS, true)
            .configure(SerializationFeature.INDENT_OUTPUT, false);

    private CanonicalJson() {
    }

    /** Serializes a field map to a canonical JSON string: sorted keys, compact, identical output regardless of the map's insertion order. */
    public static String canonicalize(Map<String, Object> fields) {
        try {
            return MAPPER.writeValueAsString(new TreeMap<>(fields));
        } catch (Exception e) {
            throw new IllegalStateException("Failed to canonicalize audit row for hashing", e);
        }
    }
}

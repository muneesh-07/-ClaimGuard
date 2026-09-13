package com.claimguard.audit;

import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class CanonicalJsonTest {

    @Test
    void keyInsertionOrderDoesNotAffectTheSerializedForm() {
        Map<String, Object> insertedBFirst = new LinkedHashMap<>();
        insertedBFirst.put("b", 2);
        insertedBFirst.put("a", 1);

        Map<String, Object> insertedAFirst = new LinkedHashMap<>();
        insertedAFirst.put("a", 1);
        insertedAFirst.put("b", 2);

        assertThat(CanonicalJson.canonicalize(insertedBFirst))
                .isEqualTo(CanonicalJson.canonicalize(insertedAFirst));
    }

    @Test
    void nullValuesAreWrittenOutExplicitlyRatherThanOmitted() {
        Map<String, Object> fields = new LinkedHashMap<>();
        fields.put("a", null);
        fields.put("b", 1);

        assertThat(CanonicalJson.canonicalize(fields)).contains("\"a\":null");
    }

    @Test
    void differentContentProducesADifferentSerializedForm() {
        Map<String, Object> a = Map.of("x", 1);
        Map<String, Object> b = Map.of("x", 2);

        assertThat(CanonicalJson.canonicalize(a)).isNotEqualTo(CanonicalJson.canonicalize(b));
    }
}

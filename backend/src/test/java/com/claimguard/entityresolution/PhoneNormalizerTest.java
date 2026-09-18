package com.claimguard.entityresolution;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * The messy real-world formats an Indian mobile number actually arrives
 * in must all collapse to the same E.164 value: three claims with the
 * same phone in three formats must produce one entity.
 */
class PhoneNormalizerTest {

    private final PhoneNormalizer normalizer = new PhoneNormalizer("IN");

    @ParameterizedTest
    @ValueSource(strings = {
            "+91-9876500011",
            "9876500011",
            "098765 00011",
            "+91 98765 00011"
    })
    void everyFormatOfTheSameNumberNormalizesIdentically(String rawPhone) {
        assertThat(normalizer.normalize(rawPhone)).isEqualTo("+919876500011");
    }

    @Test
    void differentNumbersNormalizeDifferently() {
        assertThat(normalizer.normalize("+919876500011"))
                .isNotEqualTo(normalizer.normalize("+919876500022"));
    }
}
